"""
Pane Bug Reporter & Triage Service.
Provides deterministic PII/numeric anonymization, domain invariant manifests,
and automated first-line diagnostic analysis for user-reported discrepancies.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Optional

from flask import has_request_context, session
from hvl_common.web import (
    GENERIC_WORDS,
    NON_MONETARY_KEYS,
    anonymize_structure as _anonymize_structure,
    scrub_explanatory_text as _shared_scrub_explanatory_text,
)
from services.bug_reporter_helpers import (
    PANE_MANIFESTS,
    VALID_CATEGORIES,
    VALID_PANES,
    _build_live_numeric_walkthrough,
    _m,
    _resolve_app_instance,
    _resolve_app_version,
    format_antigravity_prompt,
)


def collect_and_anonymize_pane_state(
    family_id: int = 0,
    pane: str = "overview",
    db_path: Optional[Path] = None,
    scale_factor: Optional[float] = None,
    client_context: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, str], float, str]:
    """Gathers state, extracts tokens, isomorphically scales monetary values, and returns sanitized snapshot."""
    clean_pane = str(pane or "overview").strip().lower()
    clean_pane = clean_pane if clean_pane in VALID_PANES else "overview"
    manifest = PANE_MANIFESTS[clean_pane]
    mode = str(manifest.get("anonymization_mode", "isomorphic_scale"))
    k = round(max(0.1, min(10.0, float(scale_factor))), 2) if scale_factor is not None else round(random.uniform(0.37, 0.83), 2)

    token_map: dict[str, str] = {}
    if has_request_context():
        u_name = str(session.get("user") or "").strip()
        if u_name and len(u_name) >= 3 and u_name.lower() not in GENERIC_WORDS:
            token_map[u_name] = "User_Session"
        u_email = str(session.get("user_email") or "").strip()
        if u_email and len(u_email) >= 3:
            token_map[u_email] = "user@anonymized.internal"

    envelope = build_session_envelope(family_id=family_id, db_path=db_path, client_context=client_context)
    raw_snapshot: dict[str, Any] = {
        "pane": clean_pane,
        "app_version": envelope["app_version"],
        "universe": envelope["universe"],
        "anonymization_mode": mode,
        "family_id": family_id,
        "user_ref": envelope["user_ref"],
        "support_access_enabled": bool(envelope["support_access_enabled"]),
        "client_context": client_context or {},
    }

    if family_id > 0:
        try:
            import db

            for idx, m in enumerate(db.store.get_family_members(family_id=family_id, db_path=db_path), 1):
                name = str(m.get("name") or "").strip()
                if name and len(name) >= 3 and name.lower() not in GENERIC_WORDS:
                    token_map[name] = f"Member_{idx}"
        except Exception:
            pass
        try:
            import db
            import monarch_service

            accs = db.store.get_accounts(family_id=family_id, db_path=db_path)
            totals_by_type: dict[str, float] = {}
            for idx, acc in enumerate(accs[:40], 1):
                aname = str(monarch_service.get_account_name(acc) or acc.get("name") or "").strip()
                if aname and len(aname) >= 3 and aname.lower() not in GENERIC_WORDS:
                    token_map[aname] = f"Account_{idx}"
                raw_inst = acc.get("institution") or (
                    (acc.get("credential") or {}).get("institution") if isinstance(acc.get("credential"), dict) else None
                )
                inst = str((raw_inst.get("name") if isinstance(raw_inst, dict) else raw_inst) or "").strip()
                if inst and len(inst) >= 3 and inst.lower() not in GENERIC_WORDS:
                    token_map[inst] = f"Institution_{idx}"
                raw_type = acc.get("type")
                atype = str((raw_type.get("name") if isinstance(raw_type, dict) else raw_type) or "other")
                bal = float(monarch_service.get_account_balance(acc) or acc.get("balance") or 0.0)
                totals_by_type[atype] = round(totals_by_type.get(atype, 0.0) + bal, 2)
            raw_snapshot["accounts_summary"] = {"account_count": len(accs), "totals_by_type": totals_by_type}
        except Exception:
            pass
        try:
            import equity_engine
            import monarch_service

            for idx, comp in enumerate(equity_engine.load_equity_companies_summary(family_id=family_id), 1):
                cname = str(comp.get("company_name") or "").strip()
                if cname and len(cname) >= 3 and cname.lower() not in GENERIC_WORDS:
                    token_map[cname] = f"Employer_{idx}"
            share_price = equity_engine.get_current_409a_price(family_id=family_id)
            snap = monarch_service.get_financial_snapshot(share_price=share_price, include_wa_tax=False, family_id=family_id) or {}
            true_nw = float(snap.get("true_net_worth") or 0.0)
            agg_nw = float(snap.get("monarch_reported_net_worth") or 0.0)
            non_eq = float(snap.get("non_equity_net_worth") or 0.0)
            eq = snap.get("company_equity") or {}
            cats = snap.get("categories") or {}
            raw_snapshot["net_worth_reconciliation"] = {
                "hvl_true_net_worth": round(true_nw, 2),
                "aggregator_reported_net_worth": round(agg_nw, 2),
                "delta_hvl_minus_aggregator": round(true_nw - agg_nw, 2),
                "active_non_equity_net_worth": round(non_eq, 2),
                "post_tax_company_equity": round(float(eq.get("true_net_post_tax_value") or 0.0), 2),
            }
            raw_snapshot["company_equity_breakdown"] = {
                "gross_equity_fmv": round(float(eq.get("nominal_gross_equity_value") or eq.get("total_gross_equity_value") or 0.0), 2),
                "pre_tax_spread_fmv": round(float(eq.get("total_gross_equity_value") or 0.0), 2),
                "strike_cost_needed": round(float(eq.get("total_strike_cost_needed") or 0.0), 2),
                "estimated_tax_drag": round(float(eq.get("total_tax_drag") or 0.0), 2),
                "post_tax_net_value": round(float(eq.get("true_net_post_tax_value") or 0.0), 2),
                "share_price_409a": round(float(share_price or 0.0), 2),
            }
            raw_snapshot["category_totals"] = {
                k_cat: round(float((v_cat or {}).get("total") or 0.0), 2)
                for k_cat, v_cat in cats.items()
                if abs(float((v_cat or {}).get("total") or 0.0)) > 0
            }
        except Exception:
            pass

    sanitized = _anonymize_structure(raw_snapshot, k, token_map)
    if len(json.dumps(sanitized)) > 16000:
        sanitized = {"pane": clean_pane, "truncated": True, "client_context": client_context or {}}
    return sanitized, token_map, k, mode


def scrub_explanatory_text(text: str, token_map: dict[str, str], scale_factor: float, max_length: int = 500) -> str:
    """Sanitizes user description, redacts known tokens and emails, and scales dollar amounts."""
    from routes.helpers import sanitize_text

    return _shared_scrub_explanatory_text(
        text,
        token_map,
        scale_factor,
        max_length=max_length,
        sanitize_fn=lambda s: sanitize_text(s, max_length=max_length, field_name="description"),
    )


def build_session_envelope(
    family_id: int = 0,
    db_path: Optional[Path] = None,
    client_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assembles DB universe ('public', 'demo', 'sandbox', 'test'), app_instance, app_version, role, and user_ref."""
    import config
    from routes.helpers import get_current_universe, is_sandbox_session

    has_ctx = has_request_context()
    universe = "sandbox" if (has_ctx and is_sandbox_session()) else (get_current_universe() if has_ctx else config.normalize_universe())
    user_role = str((session.get("role") or session.get("user_role") or "viewer") if has_ctx else "viewer")
    if universe == "sandbox" or family_id <= 0:
        support_access = 0
    else:
        from db import families as db_fam

        support_access = 1 if db_fam.is_support_access_enabled(family_id=family_id, db_path=db_path) else 0

    if universe == "sandbox":
        sess_token = str((session.get("sandbox_lease_id") if has_ctx else None) or family_id or "sb")
        user_ref = f"sandbox#{family_id} ({hashlib.sha256(sess_token.encode()).hexdigest()[:8]})"
    else:
        user_ref = f"uid#{(session.get('user_id') if has_ctx else 0) or 0} ({user_role})"

    return {
        "universe": universe,
        "app_instance": _resolve_app_instance(),
        "app_version": _resolve_app_version(client_context),
        "user_role": user_role,
        "support_access_enabled": support_access,
        "user_ref": user_ref,
        "family_id": family_id,
    }


def run_bug_triage_analysis(
    family_id: int = 0,
    pane: str = "overview",
    category: str = "math",
    description: str = "",
    client_context: Optional[dict[str, Any]] = None,
    scale_factor: Optional[float] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Runs deterministic diagnostic triage based on active pane mathematical invariants."""
    clean_pane = str(pane or "overview").strip().lower()
    clean_pane = clean_pane if clean_pane in VALID_PANES else "overview"
    clean_cat = str(category or "math").strip().lower()
    clean_cat = clean_cat if clean_cat in VALID_CATEGORIES else "math"

    snapshot, token_map, k, mode = collect_and_anonymize_pane_state(
        family_id=family_id,
        pane=clean_pane,
        db_path=db_path,
        scale_factor=scale_factor,
        client_context=client_context,
    )
    scrubbed_desc = scrub_explanatory_text(description, token_map, k, max_length=500)
    envelope = build_session_envelope(family_id=family_id, db_path=db_path, client_context=client_context)

    manifest = PANE_MANIFESTS[clean_pane]
    module = manifest["suspected_module"]
    invariants = manifest.get("invariants", [])
    gotchas = manifest.get("common_gotchas", [])
    primary_inv = invariants[0] if invariants else "Mathematical consistency across aggregated balances."
    inv_summary = f"[{clean_cat.upper()}] Discrepancy on {clean_pane}: '{scrubbed_desc}'. Expected: {primary_inv}"

    live_lines = _build_live_numeric_walkthrough(clean_pane, family_id, db_path)
    static_rules = [
        f"• Formula: {manifest.get('formula_summary', '')}",
        f"• Key Rules: {'; '.join(invariants[:2])}",
        f"• Common Reasons Figures Differ: {'; '.join(gotchas[:2])}",
    ]
    diag_lines = [
        f"How {manifest['title']} is calculated for your household:",
        *live_lines,
        *static_rules,
    ]
    return {
        "pane": clean_pane,
        "category": clean_cat,
        "scrubbed_description": scrubbed_desc,
        "ai_explanation": "\n".join(diag_lines),
        "static_ai_explanation": "\n".join(static_rules),
        "suspected_module": module,
        "invariant_summary": inv_summary,
        "scale_factor": k,
        "anonymization_mode": mode,
        "session_envelope": envelope,
        "sanitized_snapshot": snapshot,
        "_token_map": token_map,
    }


def submit_bug_report(
    family_id: int = 0,
    pane: str = "overview",
    category: str = "math",
    description: str = "",
    followup_notes: str = "",
    scale_factor: Optional[float] = None,
    client_context: Optional[dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """High-level submission pipeline: triages, scrubs follow-up, and persists only previewed JSON + static rules (discarding ephemeral scale_factor)."""
    from db import bugs as db_bugs

    triage = run_bug_triage_analysis(
        family_id=family_id,
        pane=pane,
        category=category,
        description=description,
        client_context=client_context,
        scale_factor=scale_factor,
        db_path=db_path,
    )
    t_map = triage.get("_token_map", {})
    k_val = triage.get("scale_factor", 1.0)
    scrubbed_followup = (
        scrub_explanatory_text(followup_notes, token_map=t_map, scale_factor=k_val, max_length=400)
        if followup_notes
        else ""
    )
    persisted_ai_expl = str(triage.get("static_ai_explanation") or "")

    envelope = triage.get("session_envelope") or build_session_envelope(
        family_id=family_id,
        db_path=db_path,
        client_context=client_context,
    )
    app_inst = _resolve_app_instance()
    bug_proj = "finances-beta" if app_inst == "finances-beta" else "finances"
    bug_id = db_bugs.insert_bug_report(
        db_path=None,
        project=bug_proj,
        app_version=envelope.get("app_version", ""),
        universe=envelope["universe"],
        family_id=family_id,
        user_role=envelope["user_role"],
        user_ref=envelope["user_ref"],
        support_access_enabled=envelope["support_access_enabled"],
        pane=triage["pane"],
        category=triage["category"],
        scrubbed_description=triage["scrubbed_description"],
        scrubbed_followup=scrubbed_followup,
        ai_explanation=persisted_ai_expl,
        suspected_module=triage["suspected_module"],
        invariant_summary=triage["invariant_summary"],
        scale_factor=0.0,
        anonymization_mode=triage["anonymization_mode"],
        sanitized_snapshot_json=triage["sanitized_snapshot"],
    )
    saved_report = db_bugs.get_bug_report(bug_id) or {}
    return {
        "bug_id": bug_id,
        "report": saved_report,
        "diagnostic_bundle": format_antigravity_prompt(saved_report) if saved_report else "",
    }


__all__ = [
    "NON_MONETARY_KEYS",
    "PANE_MANIFESTS",
    "VALID_CATEGORIES",
    "VALID_PANES",
    "_build_live_numeric_walkthrough",
    "_m",
    "build_session_envelope",
    "collect_and_anonymize_pane_state",
    "format_antigravity_prompt",
    "run_bug_triage_analysis",
    "scrub_explanatory_text",
    "submit_bug_report",
]
