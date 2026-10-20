"""
Pane Bug Reporter & Triage Service.
Provides deterministic PII/numeric anonymization, domain invariant manifests,
and automated first-line diagnostic analysis for user-reported discrepancies.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any, Optional

from flask import has_request_context, session

VALID_PANES: tuple[str, ...] = (
    "overview", "equity", "scenarios", "holdings", "arbitrage", "compensation",
    "philanthropy", "gifting", "estate", "college", "accounts", "settings",
)
VALID_CATEGORIES: tuple[str, ...] = ("math", "sync", "ui", "permission")
NON_MONETARY_KEYS: frozenset[str] = frozenset({
    "id", "family_id", "user_id", "bug_id", "age", "retirement_age", "year", "years",
    "month", "count", "account_count", "total_count", "rate", "pct", "percent",
    "percentage", "percentile", "trials", "status", "role", "universe",
    "filing_status", "state", "tier", "version", "app_version", "client_version",
    "git_sha", "support_access_enabled", "is_demo", "is_sandbox", "active", "enabled",
})
GENERIC_WORDS: frozenset[str] = frozenset({
    "cash", "stock", "trust", "plan", "the", "family", "bank", "roth", "ira",
    "401k", "loan", "card", "fund", "savings", "checking", "none", "null",
    "true", "false", "holding", "equity", "vested", "unvested", "total",
})

def _m(t: str, m: str, f: str, invs: list[str], gotchas: list[str], mode: str = "isomorphic_scale") -> dict[str, Any]:
    return {"title": t, "suspected_module": m, "formula_summary": f, "invariants": invs, "common_gotchas": gotchas, "anonymization_mode": mode}


PANE_MANIFESTS: dict[str, dict[str, Any]] = {
    "overview": _m("Net Worth & Overview", "monarch_service.py :: get_consolidated_balance_sheet", "Net Worth = Total Assets - Total Liabilities.", ["Net Worth = Sum(Active Balances) + Vested Equity - Liabilities", "Runway = Cash / Spending"], ["Unvested equity excluded from net worth", "Inactive accounts excluded", "Aggregator sync lag may cause divergence"]),
    "equity": _m("Equity & RSUs", "equity_engine.py :: get_equity_summary", "Gross Vest FMV = Shares × Price. Net Proceeds = Gross Spread - Exercise Cost - Withholding.", ["Total Grant Value = Vested Value + Unvested Value", "Net Vest Proceeds = Gross Spread - Strike Cost - Withholding"], ["Federal withholding jumps from 22% to 37% for wages > $1M", "WA 7% LTCG tax applies above $250k deduction", "Unvested grants fluctuate with market price"]),
    "scenarios": _m("Scenarios & Monte Carlo", "forecast_engine.py :: run_financial_forecast", "Terminal Wealth = Beginning Wealth × (1 + Return - Inflation) + Savings - Spending - Taxes.", ["Probability of Success = Percentage of trials with terminal wealth > $0", "Real wealth adjusts cashflows by inflation"], ["Real vs Nominal dollars toggle alters balance view", "Early sequence-of-returns risk affects 10th percentile", "Spending guardrails trigger in drawdown years"]),
    "holdings": _m("Holdings & Asset Allocation", "monarch_service.py :: get_holdings_allocation", "Asset Allocation % = Class Value / Total Investable Value.", ["Sum of all asset allocation percentages equals 100.0%", "Total Investable Assets matches sum of investment balances"], ["Brokerage sweep cash is classified under Cash", "Target drift is relative to policy presets", "Uncategorized tickers fall into Other/Alternatives"]),
    "arbitrage": _m("Tax Arbitrage", "tax_engine.py :: calculate_tax_projection", "Tax Delta = Effective Tax on Conversion - Marginal Tax in Retirement.", ["Tax Delta = Projected Future Tax Saved - Immediate Tax Paid", "Total Conversion = Sum of bracket tranches converted"], ["NIIT (3.8%) and state taxes apply when MAGI exceeds thresholds", "Medicare IRMAA creates cliff brackets 2 years later", "TCJA sunset changes long-term brackets"], "statutory_delta"),
    "compensation": _m("Executive Compensation & W-2", "tax_engine.py :: calculate_tax_projection", "Total Comp = Base Salary + Bonus + Vested Equity. Box 1 Wages = Gross Wages - Pre-Tax Deductions.", ["Taxable Box 1 Wages = Gross Total Comp - Pre-Tax Deductions (401k/HSA)", "Take-Home Pay = Gross Earnings - Taxes - Deductions"], ["Social Security wage base caps at annual limit", "Pre-tax 401(k) reduces Box 1 but not Box 3 wages", "Filing status alters standard deduction and brackets"], "statutory_delta"),
    "philanthropy": _m("Philanthropy & DAF", "tax_engine.py :: calculate_charitable_deduction", "Charitable Tax Savings = Contributed FMV × Marginal Rate. AGI Deduction Cap: 60% cash, 30% assets.", ["Deductible Amount = Min(Charitable Contribution, AGI Limit)", "5-Year Carryforward = Unused Contribution exceeding AGI cap"], ["Donating appreciated stock avoids capital gains tax and deducts full FMV", "Excess contributions carry forward for 5 years", "DAF bunching clears standard deduction hurdle"]),
    "gifting": _m("Annual Exclusion Gifting", "estate.py :: calculate_gifting_allowance", "Tax-Free Annual Exclusion = Statutory Limit per donor per donee. Lifetime Exemption absorbs excess.", ["Annual Tax-Free Gifting = Number of Donees × Annual Exclusion Limit ($19,000 / $38,000 MFJ)", "Taxable Gifts = Max(0, Total Gifts - Annual Exclusions)"], ["Gift-splitting requires filing Form 709", "Direct tuition or medical payments are exempt", "529 superfunding allows 5-year front-loading"]),
    "estate": _m("Estate Planning & Inheritance", "estate.py :: run_estate_distribution", "Gross Estate = Real + Tangible + Intangible Assets + Life Insurance. Taxable = Gross - Deductions.", ["Federal Estate Tax = Max(0, Taxable Estate - Remaining Lifetime Exemption) × 40%", "Net Inheritance = Gross Estate - Taxes - Administrative Costs"], ["WA estate tax has a lower exemption threshold without portability", "ILIT removes life insurance proceeds from estate", "Scheduled sunset of TCJA exemption affects future estates"], "statutory_delta"),
    "college": _m("College Education (529)", "education.py :: project_college_savings", "Future Cost = Tuition × (1 + Inflation)^Years. Projected 529 = Current × (1 + Return)^Years + Contributions.", ["Funding Surplus/Shortfall = Projected 529 Balance - Total Projected Cost", "Qualified Withdrawals = 100% Tax-Free"], ["Higher education inflation typically exceeds CPI", "SECURE 2.0 allows up to $35k rollover into Roth IRA", "Room and board requires at least half-time enrollment"]),
    "accounts": _m("Accounts & Institutions", "monarch_service.py :: list_accounts", "Total Balance = Sum of all active depository, investment, loan, and credit balances.", ["Total Household Accounts = Active Accounts + Inactive Accounts", "Total Net Balance = Positive Assets - Liabilities"], ["Aggregator sync latency may take up to 24 hours", "Duplicate accounts may appear if manually tracked overlap with feeds", "Inverted liability sign depends on institution"]),
    "settings": _m("Household Settings & Access", "security.py :: get_family_key", "Cryptographic Household Vault Protocol: Zero-Knowledge Support Access with Browser/Drive Escrow.", ["Support Access = 0 ensures FEK is completely NULL in database", "Role permissions: Admin > Editor > Viewer"], ["Toggling Support Access OFF purges escrowed FEK immediately", "Sandbox sessions cannot toggle persistent escrow", "Demo persona is strictly read-only"]),
}


def _resolve_app_instance() -> str:
    """Returns the running application instance ('finances-beta', 'finances-local', or 'finances')."""
    import config
    if config.is_local_mode():
        return "finances-local"
    if config.is_beta_instance():
        return "finances-beta"
    return "finances"


def _resolve_app_version(client_context: Optional[dict[str, Any]] = None) -> str:
    """Returns formatted app instance, version, and git SHA, noting if client asset version differs."""
    import config
    instance = _resolve_app_instance()
    semver = str(getattr(config, "APP_VERSION", "0.2.0") or "0.2.0")
    server_asset = ""
    try:
        import app as _app
        server_asset = str(getattr(_app, "ASSET_VERSION", "") or "")
    except Exception:
        pass
    server_sha = server_asset.split("-")[0] if server_asset else ""
    base = f"{instance} v{semver} ({server_sha})" if server_sha else f"{instance} v{semver}"
    client_v = str((client_context or {}).get("client_version") or "").strip()[:40]
    if client_v and server_asset and client_v != server_asset:
        client_sha = client_v.split("-")[0]
        if client_sha and client_sha != server_sha:
            return f"{base} [client: {client_sha}]"
    return base


def _anonymize_structure(obj: Any, scale_factor: float, token_map: dict[str, str], active_key: str = "") -> Any:
    """Recursively replaces sensitive tokens and scales monetary values in nested data."""
    if isinstance(obj, str):
        val = obj
        for phrase, token in sorted(token_map.items(), key=lambda x: len(x[0]), reverse=True):
            if len(phrase) >= 3:
                val = re.sub(re.escape(phrase), token, val, flags=re.IGNORECASE)
        return val
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        key_low = active_key.lower()
        if key_low in NON_MONETARY_KEYS or key_low.endswith(("_id", "_count", "_year", "_age", "_rate", "_pct", "_percent")):
            return obj
        return round(float(obj) * scale_factor, 2)
    if isinstance(obj, dict):
        return {k: _anonymize_structure(v, scale_factor, token_map, active_key=str(k)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_anonymize_structure(item, scale_factor, token_map, active_key=active_key) for item in obj]
    return obj


def collect_and_anonymize_pane_state(
    family_id: int = 0, pane: str = "overview", db_path: Optional[Path] = None,
    scale_factor: Optional[float] = None, client_context: Optional[dict[str, Any]] = None,
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
        "pane": clean_pane, "app_version": envelope["app_version"], "universe": envelope["universe"],
        "anonymization_mode": mode, "family_id": family_id, "user_ref": envelope["user_ref"],
        "support_access_enabled": bool(envelope["support_access_enabled"]), "client_context": client_context or {},
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
            import db, monarch_service
            accs = db.store.get_accounts(family_id=family_id, db_path=db_path)
            totals_by_type: dict[str, float] = {}
            for idx, acc in enumerate(accs[:40], 1):
                aname = str(monarch_service.get_account_name(acc) or acc.get("name") or "").strip()
                if aname and len(aname) >= 3 and aname.lower() not in GENERIC_WORDS:
                    token_map[aname] = f"Account_{idx}"
                raw_inst = acc.get("institution") or ((acc.get("credential") or {}).get("institution") if isinstance(acc.get("credential"), dict) else None)
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
            import equity_engine, monarch_service
            for idx, comp in enumerate(equity_engine.load_equity_companies_summary(family_id=family_id), 1):
                cname = str(comp.get("company_name") or "").strip()
                if cname and len(cname) >= 3 and cname.lower() not in GENERIC_WORDS:
                    token_map[cname] = f"Employer_{idx}"
            share_price = equity_engine.get_current_409a_price(family_id=family_id)
            snap = monarch_service.get_financial_snapshot(share_price=share_price, include_wa_tax=False, family_id=family_id) or {}
            true_nw, agg_nw, non_eq = float(snap.get("true_net_worth") or 0.0), float(snap.get("monarch_reported_net_worth") or 0.0), float(snap.get("non_equity_net_worth") or 0.0)
            eq, cats = snap.get("company_equity") or {}, snap.get("categories") or {}
            raw_snapshot["net_worth_reconciliation"] = {
                "hvl_true_net_worth": round(true_nw, 2), "aggregator_reported_net_worth": round(agg_nw, 2),
                "delta_hvl_minus_aggregator": round(true_nw - agg_nw, 2), "active_non_equity_net_worth": round(non_eq, 2),
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
                for k_cat, v_cat in cats.items() if abs(float((v_cat or {}).get("total") or 0.0)) > 0
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
    cleaned = sanitize_text(str(text or "").strip()[:max_length], max_length=max_length, field_name="description")
    if not cleaned:
        return ""
    for phrase, token in sorted(token_map.items(), key=lambda x: len(x[0]), reverse=True):
        if len(phrase) >= 3:
            cleaned = re.sub(re.escape(phrase), token, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[redacted-email]", cleaned)

    def _scale_dollar(m: re.Match) -> str:
        sign = m.group(1) or m.group(2) or ""
        try:
            val = float(m.group(3).replace(",", ""))
        except ValueError:
            return m.group(0)
        suf = (m.group(4) or "").lower()
        val *= 1000.0 if suf == "k" else (1000000.0 if suf == "m" else (1000000000.0 if suf == "b" else 1.0))
        scaled = val * scale_factor
        return f"{sign}${scaled:,.0f} (scaled)" if scaled >= 10 else f"{sign}${scaled:,.2f} (scaled)"

    return re.sub(
        r"([+-])?\$\s*([+-])?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|\d+(?:\.[0-9]+)?)(?:\s*([kKmMbB])\b)?",
        _scale_dollar,
        cleaned,
    )


def build_session_envelope(
    family_id: int = 0, db_path: Optional[Path] = None, client_context: Optional[dict[str, Any]] = None,
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
        "universe": universe, "app_instance": _resolve_app_instance(),
        "app_version": _resolve_app_version(client_context), "user_role": user_role,
        "support_access_enabled": support_access, "user_ref": user_ref, "family_id": family_id,
    }


def _build_live_numeric_walkthrough(clean_pane: str, family_id: int, db_path: Optional[Path]) -> list[str]:
    """Computes live dollar reconciliation lines for the active pane to show the user how their numbers add up."""
    if family_id <= 0:
        return []
    lines: list[str] = []
    try:
        import equity_engine
        import monarch_service
        share_price = equity_engine.get_current_409a_price(family_id=family_id)
        snap = monarch_service.get_financial_snapshot(share_price=share_price, include_wa_tax=False, family_id=family_id) or {}
        true_nw, agg_nw, non_eq = float(snap.get("true_net_worth") or 0.0), float(snap.get("monarch_reported_net_worth") or 0.0), float(snap.get("non_equity_net_worth") or 0.0)
        eq = snap.get("company_equity") or {}
        eq_net = float(eq.get("true_net_post_tax_value") or 0.0)
        eq_gross = float(eq.get("nominal_gross_equity_value") or eq.get("total_gross_equity_value") or 0.0)
        strike, tax_drag = float(eq.get("total_strike_cost_needed") or 0.0), float(eq.get("total_tax_drag") or 0.0)
        cats = snap.get("categories") or {}
        c_tot = lambda k: float((cats.get(k) or {}).get("total") or 0.0)

        if clean_pane in ("overview", "accounts"):
            delta_nw = true_nw - agg_nw
            delta_fmt = f"+${delta_nw:,.0f}" if delta_nw >= 0 else f"-${abs(delta_nw):,.0f}"
            lines.append(f"• Your Live Figures: HVL True Net Worth = ${true_nw:,.0f} vs. Aggregator Reported Net Worth = ${agg_nw:,.0f} (Delta: {delta_fmt}).")
            lines.append(f"• HVL Formula Breakdown: Active Non-Equity Accounts (${non_eq:,.0f}) + Post-Tax Company Equity (${eq_net:,.0f} [Gross ${eq_gross:,.0f} - Strike ${strike:,.0f} - Tax Drag ${tax_drag:,.0f}]) = ${true_nw:,.0f}.")
            excl_map = [
                ("company_equity_nso", "Raw Aggregator Equity Placeholder (replaced by HVL post-tax model)"),
                ("hidden_from_family_office", "Hidden from Family Office"),
                ("education_529", "529/Custodial Education"),
                ("tax_liability", "Tax Liability Reserve"),
            ]
            excl_parts = [f"{lbl} (${c_tot(key):,.0f})" for key, lbl in excl_map if abs(c_tot(key)) > 0]
            if excl_parts:
                lines.append(f"• Why They Differ: {', '.join(excl_parts)}.")
        elif clean_pane == "equity":
            lines.append(f"• Your Live Equity Figures: Post-Tax Value = ${eq_net:,.0f} (Gross ${eq_gross:,.0f} - Strike Cost ${strike:,.0f} - Estimated Tax Drag ${tax_drag:,.0f} @ ${share_price:,.2f}/sh).")
        elif clean_pane == "holdings":
            lines.append(f"• Your Live Portfolio Breakdown: Public Brokerage (${c_tot('public_brokerage'):,.0f}) + Cash (${c_tot('cash_liquid'):,.0f}) + Retirement (${c_tot('retirement'):,.0f}) + Private (${c_tot('private_investments'):,.0f}) + Post-Tax Equity (${eq_net:,.0f}).")
        else:
            from db import families as db_fam
            hp = (db_fam.get_household_profile(family_id=family_id, db_path=db_path) if db_path else None) or {}
            lines.append(f"• Your Live Context: Baseline True Net Worth = ${true_nw:,.0f} (Liquid & Brokerage ${c_tot('cash_liquid') + c_tot('public_brokerage'):,.0f}, Retirement ${c_tot('retirement'):,.0f}) • Profile: {hp.get('state') or 'WA'} / {hp.get('filing_status') or 'MFJ'}, Target Annual Spend ${float(hp.get('annual_spending') or 0.0):,.0f}.")
    except Exception:
        pass
    return lines


def run_bug_triage_analysis(
    family_id: int = 0, pane: str = "overview", category: str = "math", description: str = "",
    client_context: Optional[dict[str, Any]] = None, scale_factor: Optional[float] = None, db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Runs deterministic diagnostic triage based on active pane mathematical invariants."""
    clean_pane = str(pane or "overview").strip().lower()
    clean_pane = clean_pane if clean_pane in VALID_PANES else "overview"
    clean_cat = str(category or "math").strip().lower()
    clean_cat = clean_cat if clean_cat in VALID_CATEGORIES else "math"

    snapshot, token_map, k, mode = collect_and_anonymize_pane_state(
        family_id=family_id, pane=clean_pane, db_path=db_path, scale_factor=scale_factor, client_context=client_context
    )
    scrubbed_desc = scrub_explanatory_text(description, token_map, k, max_length=500)
    envelope = build_session_envelope(family_id=family_id, db_path=db_path, client_context=client_context)

    manifest = PANE_MANIFESTS[clean_pane]
    module, invariants, gotchas = manifest["suspected_module"], manifest.get("invariants", []), manifest.get("common_gotchas", [])
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
        "pane": clean_pane, "category": clean_cat, "scrubbed_description": scrubbed_desc,
        "ai_explanation": "\n".join(diag_lines), "static_ai_explanation": "\n".join(static_rules),
        "suspected_module": module, "invariant_summary": inv_summary,
        "scale_factor": k, "anonymization_mode": mode, "session_envelope": envelope,
        "sanitized_snapshot": snapshot, "_token_map": token_map,
    }


def submit_bug_report(
    family_id: int = 0, pane: str = "overview", category: str = "math", description: str = "",
    followup_notes: str = "", scale_factor: Optional[float] = None,
    client_context: Optional[dict[str, Any]] = None, db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """High-level submission pipeline: triages, scrubs follow-up, and persists only previewed JSON + static rules (discarding ephemeral scale_factor)."""
    from db import bugs as db_bugs

    triage = run_bug_triage_analysis(
        family_id=family_id, pane=pane, category=category, description=description,
        client_context=client_context, scale_factor=scale_factor, db_path=db_path,
    )
    t_map, k_val = triage.get("_token_map", {}), triage.get("scale_factor", 1.0)
    scrubbed_followup = scrub_explanatory_text(followup_notes, token_map=t_map, scale_factor=k_val, max_length=400) if followup_notes else ""
    persisted_ai_expl = str(triage.get("static_ai_explanation") or "")

    envelope = triage.get("session_envelope") or build_session_envelope(
        family_id=family_id, db_path=db_path, client_context=client_context
    )
    app_inst = _resolve_app_instance()
    bug_proj = "finances-beta" if app_inst == "finances-beta" else "finances"
    bug_id = db_bugs.insert_bug_report(
        db_path=None, project=bug_proj, app_version=envelope.get("app_version", ""), universe=envelope["universe"],
        family_id=family_id, user_role=envelope["user_role"], user_ref=envelope["user_ref"],
        support_access_enabled=envelope["support_access_enabled"], pane=triage["pane"],
        category=triage["category"], scrubbed_description=triage["scrubbed_description"],
        scrubbed_followup=scrubbed_followup, ai_explanation=persisted_ai_expl,
        suspected_module=triage["suspected_module"], invariant_summary=triage["invariant_summary"],
        scale_factor=0.0, anonymization_mode=triage["anonymization_mode"],
        sanitized_snapshot_json=triage["sanitized_snapshot"],
    )
    saved_report = db_bugs.get_bug_report(bug_id) or {}
    return {
        "bug_id": bug_id,
        "report": saved_report,
        "diagnostic_bundle": format_antigravity_prompt(saved_report) if saved_report else "",
    }


def format_antigravity_prompt(report: dict[str, Any]) -> str:
    """Formats an anonymized bug report into a copy-pasteable AI Triage Markdown prompt without leaking scale_factor."""
    support = "ON" if report.get("support_access_enabled") else "OFF"
    follow = report.get("scrubbed_followup", "")
    follow_block = f"\n**User Clarification:**\n{follow}\n" if follow else ""
    app_ver = report.get("app_version") or (report.get("sanitized_snapshot") or {}).get("app_version") or "unknown"
    return (
        f"### Bug Report #{report.get('bug_id', 0)}: [{str(report.get('category', 'math')).upper()}] Pane `{report.get('pane', 'overview')}` ({report.get('universe', 'public')})\n"
        f"- **App Version**: `{app_ver}` • **Universe**: `{report.get('universe', 'public')}`\n"
        f"- **Status**: `{report.get('status', 'open')}`\n"
        f"- **Suspected Module**: `{report.get('suspected_module', '')}`\n"
        f"- **User**: `{report.get('user_ref', '')}` (Support Access: `{support}`)\n"
        f"- **Anonymization**: `{report.get('anonymization_mode', 'isomorphic_scale')}` (ephemeral multiplier discarded)\n\n"
        f"#### Mathematical Invariant\n> {report.get('invariant_summary', '')}\n\n"
        f"#### User Observation (Scrubbed & Scaled)\n{report.get('scrubbed_description', '')}\n{follow_block}\n"
        f"#### AI Diagnostic Triage\n{report.get('ai_explanation', '')}\n\n"
        f"#### Anonymized Household Snapshot\n```json\n{json.dumps(report.get('sanitized_snapshot') or {}, indent=2)}\n```"
    )

