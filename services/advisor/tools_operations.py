"""
services/advisor/tools_operations.py: Private markets LP commitment book,
capital call pacing, tax season document checklist, and operational workflow tools
for the AI Financial Advisor.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from services.advisor.tools_core import _resolve_tool_family_id
import services.private_markets_service as pms
import services.tax_checklist_service as tcs

logger = logging.getLogger(__name__)


def _is_read_only_mode() -> bool:
    """Safely determines if the active context is demo, sandbox, or viewer-restricted."""
    try:
        from services.advisor.chat_service import is_advisor_demo_session
        return bool(is_advisor_demo_session())
    except Exception:
        return False


def get_private_markets_lp_book(family_id: int = 0) -> Dict[str, Any]:
    """
    Retrieves the household's private markets LP fund commitment book, capital called,
    unfunded dry powder, distributions received, TVPI/DPI performance, last mark date,
    liquid cash coverage ratio, standard multi-year call schedule, and accelerated call schedule.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    try:
        summary_payload = pms.get_lp_commitments_summary(family_id=fam_id)
        raw_summary = summary_payload.get("summary") or {}
        commitments_raw = summary_payload.get("commitments") or []
        std_sched = pms.get_lp_call_schedule(family_id=fam_id, accelerate=False)
        acc_sched = pms.get_lp_call_schedule(family_id=fam_id, accelerate=True)

        summary = {
            "total_committed": raw_summary.get("total_committed", 0.0),
            "total_called": raw_summary.get("total_called", 0.0),
            "total_unfunded": raw_summary.get("total_unfunded", 0.0),
            "total_distributions": raw_summary.get("total_distributions", 0.0),
            "total_nav": raw_summary.get("total_nav", 0.0),
            "portfolio_tvpi": raw_summary.get("portfolio_tvpi", 0.0),
            "portfolio_dpi": raw_summary.get("portfolio_dpi", 0.0),
            "liquid_cash_coverage_ratio": raw_summary.get("liquid_cash_coverage_ratio", 0.0),
            "has_stale_mark": bool(raw_summary.get("has_stale_mark", False)),
            "oldest_mark_date": raw_summary.get("oldest_mark_date"),
        }

        commitments: List[Dict[str, Any]] = [
            {
                "id": c.get("id"),
                "fund_name": c.get("fund_name"),
                "fund_type": c.get("fund_type"),
                "vintage_year": c.get("vintage_year"),
                "total_commitment": c.get("total_commitment", 0.0),
                "capital_called": c.get("capital_called", 0.0),
                "unfunded_commitment": c.get("unfunded_commitment", 0.0),
                "distributions_received": c.get("distributions_received", 0.0),
                "current_nav": c.get("current_nav", 0.0),
                "tvpi": c.get("tvpi", 0.0),
                "dpi": c.get("dpi", 0.0),
                "last_mark_date": c.get("last_mark_date"),
                "is_mark_stale": bool(c.get("is_mark_stale", False)),
                "expected_call_horizon_years": c.get("expected_call_horizon_years", 3),
                "k1_status": c.get("k1_status", "Expected"),
                "notes": c.get("notes", ""),
            }
            for c in commitments_raw
        ]

        return {
            "summary": summary,
            "commitments": commitments,
            "standard_call_schedule_by_year": std_sched,
            "accelerated_24m_call_schedule_by_year": acc_sched,
        }
    except Exception as e:
        logger.warning("Error fetching LP commitment book for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def manage_lp_commitment(
    action: str = "upsert",
    fund_name: str = "",
    fund_type: str = "Private Equity",
    vintage_year: int = 2024,
    total_commitment: float = 0.0,
    capital_called: float = 0.0,
    unfunded_commitment: Optional[float] = None,
    distributions_received: float = 0.0,
    current_nav: float = 0.0,
    last_mark_date: str = "2026-06-30",
    expected_call_horizon_years: int = 3,
    k1_status: str = "Expected",
    notes: str = "",
    commitment_id: Optional[str] = None,
    family_id: int = 0,
) -> Dict[str, Any]:
    """
    Manages private market LP fund commitments (upsert or delete).
    In demo / viewer mode, operates strictly in simulated read-only mode without persisting to disk.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    act = str(action or "upsert").strip().lower()
    if act not in ("upsert", "delete"):
        return {"error": f"Unsupported action '{action}'", "status": "invalid_action"}

    existing = pms.get_lp_commitments(family_id=fam_id)
    matched = None
    if commitment_id:
        cid_str = str(commitment_id).strip()
        matched = next((c for c in existing if str(c.get("id")) == cid_str), None)
    if not matched and fund_name:
        fn_clean = fund_name.strip().lower()
        matched = next((c for c in existing if str(c.get("fund_name", "")).strip().lower() == fn_clean), None)
        if not matched:
            matched = next((c for c in existing if fn_clean in str(c.get("fund_name", "")).strip().lower()), None)

    is_read_only = _is_read_only_mode()

    if act == "delete":
        if not matched and not commitment_id:
            return {"error": f"Fund '{fund_name or commitment_id}' not found", "status": "not_found"}
        target_id = matched["id"] if matched else str(commitment_id)
        if is_read_only:
            return {
                "status": "simulated_only",
                "action": "delete",
                "commitment_id": target_id,
                "fund_name": matched.get("fund_name") if matched else fund_name,
            }
        success = pms.delete_lp_commitment(family_id=fam_id, item_id=target_id)
        if not success:
            return {"error": f"Failed deleting LP commitment '{target_id}'", "status": "failed"}
        try:
            from db import store
            store.notify_family_mutation(fam_id, domains=["holdings"])
        except Exception:
            pass
        updated_book = get_private_markets_lp_book(family_id=fam_id)
        return {
            "status": "deleted",
            "commitment_id": target_id,
            "summary": updated_book.get("summary", {}),
            "book": updated_book,
        }

    # Upsert branch
    target_id = matched["id"] if matched else commitment_id
    total_c = max(0.0, float(total_commitment or (matched.get("total_commitment", 0.0) if matched else 0.0)))
    called_c = max(0.0, float(capital_called or (matched.get("capital_called", 0.0) if matched else 0.0)))
    unf_c = unfunded_commitment if unfunded_commitment is not None else (
        matched.get("unfunded_commitment") if matched else max(0.0, total_c - called_c)
    )

    save_payload: Dict[str, Any] = {
        "id": target_id,
        "fund_name": fund_name or (matched.get("fund_name") if matched else "Private Fund"),
        "fund_type": fund_type or (matched.get("fund_type") if matched else "Private Equity"),
        "vintage_year": int(vintage_year or (matched.get("vintage_year", 2024) if matched else 2024)),
        "total_commitment": total_c,
        "capital_called": called_c,
        "unfunded_commitment": unf_c,
        "distributions_received": float(distributions_received or (matched.get("distributions_received", 0.0) if matched else 0.0)),
        "current_nav": float(current_nav or (matched.get("current_nav", 0.0) if matched else 0.0)),
        "last_mark_date": last_mark_date or (matched.get("last_mark_date") if matched else "2026-06-30"),
        "expected_call_horizon_years": int(expected_call_horizon_years or (matched.get("expected_call_horizon_years", 3) if matched else 3)),
        "k1_status": k1_status or (matched.get("k1_status") if matched else "Expected"),
        "notes": notes or (matched.get("notes") if matched else ""),
    }

    if is_read_only:
        return {
            "status": "simulated_only",
            "action": "upsert",
            "commitment": save_payload,
            "summary": get_private_markets_lp_book(family_id=fam_id).get("summary", {}),
        }

    saved = pms.save_lp_commitment(family_id=fam_id, item_data=save_payload)
    try:
        from db import store
        store.notify_family_mutation(fam_id, domains=["holdings"])
    except Exception:
        pass

    updated_book = get_private_markets_lp_book(family_id=fam_id)
    return {
        "status": "saved",
        "commitment": saved,
        "summary": updated_book.get("summary", {}),
        "book": updated_book,
    }


def update_tax_document_checklist_status(
    item_id_or_name: str = "",
    status: str = "received",
    tax_year: int = 2025,
    family_id: int = 0,
) -> Dict[str, Any]:
    """
    Updates or cycles the status of an expected tax document in the household's tax checklist.
    Matches item_id_or_name against id, source, form_type, or form_title.
    In demo / viewer mode, returns simulated status update without persisting to disk.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    target = str(item_id_or_name or "").strip().lower()
    if not target:
        return {"error": "item_id_or_name required", "status": "invalid_input"}

    chk = tcs.get_tax_document_checklist(family_id=fam_id, tax_year=tax_year)
    items = chk.get("items") or chk.get("checklist_items") or []

    matched = next((i for i in items if str(i.get("id", "")).lower() == target), None)
    if not matched:
        matched = next(
            (i for i in items if target in str(i.get("id", "")).lower()
             or target in str(i.get("source", "")).lower()
             or target in str(i.get("form_type", "")).lower()
             or target in str(i.get("form_title", "")).lower()),
            None,
        )

    if not matched:
        return {"error": f"Tax document '{item_id_or_name}' not found", "status": "not_found"}

    norm_status = str(status or "received").strip().lower()
    if norm_status not in ("waiting", "received", "sent_to_cpa", "cycle"):
        norm_status = "received"

    if _is_read_only_mode():
        sim_status = tcs.NEXT_STATUS.get(matched.get("status", "waiting"), "received") if norm_status == "cycle" else norm_status
        return {
            "success": True,
            "status": "simulated_only",
            "item_id": matched["id"],
            "new_status": sim_status,
            "tax_year": tax_year,
            "item": matched,
        }

    return tcs.update_tax_document_status(
        family_id=fam_id,
        item_id=matched["id"],
        status=norm_status,
        tax_year=tax_year,
    )
