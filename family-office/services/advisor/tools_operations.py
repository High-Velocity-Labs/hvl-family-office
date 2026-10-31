"""
services/advisor/tools_operations.py: Private markets LP commitment book,
capital call pacing, tax season document checklist, and operational workflow tools
for the AI Financial Advisor.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from services.request_context import can_mutate
from services.advisor.tools_core import _resolve_tool_family_id
import services.private_markets_service as pms
import services.tax_checklist_service as tcs

logger = logging.getLogger(__name__)


def _is_read_only_mode() -> bool:
    """Write tools only persist when the originating request may change household data (deny by default)."""
    return not can_mutate()


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


def _lp_id_required(existing: List[Dict[str, Any]], fund_name: str, reason: str) -> Dict[str, Any]:
    """Refusal for an LP write that is not pinned to one exact fund id; lists candidates so the model can ask the user."""
    needle = (fund_name or "").strip().lower()
    named = [c for c in existing if needle and needle in str(c.get("fund_name", "")).strip().lower()]
    pool = named or existing
    return {
        "error": f"{reason} Nothing was changed. Confirm the exact fund with the user and call again with commitment_id.",
        "status": "id_required",
        "candidates": [{"id": c.get("id"), "fund_name": c.get("fund_name")} for c in pool],
    }


def manage_lp_commitment(
    action: str = "upsert",
    fund_name: str = "",
    fund_type: Optional[str] = None,
    vintage_year: Optional[int] = None,
    total_commitment: Optional[float] = None,
    capital_called: Optional[float] = None,
    unfunded_commitment: Optional[float] = None,
    distributions_received: Optional[float] = None,
    current_nav: Optional[float] = None,
    last_mark_date: Optional[str] = None,
    expected_call_horizon_years: Optional[int] = None,
    k1_status: Optional[str] = None,
    notes: Optional[str] = None,
    commitment_id: Optional[str] = None,
    family_id: int = 0,
) -> Dict[str, Any]:
    """
    Manages private market LP fund commitments (upsert or delete).
    On update, only the fields passed in change; every omitted field keeps its stored value.
    Updates and deletes require the fund's exact commitment_id; names never select a fund to change.
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
    cid_str = str(commitment_id).strip() if commitment_id else ""
    if cid_str:
        matched = next((c for c in existing if str(c.get("id")) == cid_str), None)
        if not matched:
            return _lp_id_required(existing, fund_name, f"No LP commitment has id '{cid_str}'.")
    elif act == "delete":
        return _lp_id_required(existing, fund_name, "Deleting an LP commitment requires its exact commitment_id.")
    else:
        fn_clean = (fund_name or "").strip().lower()
        if fn_clean and any(str(c.get("fund_name", "")).strip().lower() == fn_clean for c in existing):
            return _lp_id_required(existing, fund_name, f"A fund named '{fund_name}' already exists; updating it requires its exact commitment_id.")

    is_read_only = _is_read_only_mode()

    if act == "delete":
        target_id = matched["id"]
        if is_read_only:
            return {
                "status": "simulated_only",
                "action": "delete",
                "commitment_id": target_id,
                "fund_name": matched.get("fund_name"),
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

    # Upsert branch: explicit arguments win, omitted ones keep the stored value (or a blank for a new fund).
    stored = matched or {}

    def _keep(value: Any, key: str, blank: Any) -> Any:
        return value if value is not None else stored.get(key, blank)

    target_id = matched["id"] if matched else None
    total_c = max(0.0, float(_keep(total_commitment, "total_commitment", 0.0) or 0.0))
    called_c = max(0.0, float(_keep(capital_called, "capital_called", 0.0) or 0.0))
    if unfunded_commitment is not None:
        unf_c = max(0.0, float(unfunded_commitment))
    elif matched and total_commitment is None and capital_called is None:
        unf_c = stored.get("unfunded_commitment")
    else:
        unf_c = max(0.0, total_c - called_c)

    save_payload: Dict[str, Any] = {
        "id": target_id,
        "account_id": stored.get("account_id", ""),
        "fund_name": fund_name or stored.get("fund_name") or "Private Fund",
        "fund_type": _keep(fund_type, "fund_type", "Private Equity"),
        "vintage_year": int(vintage_year) if vintage_year else stored.get("vintage_year"),
        "total_commitment": total_c,
        "capital_called": called_c,
        "unfunded_commitment": unf_c,
        "distributions_received": float(_keep(distributions_received, "distributions_received", 0.0) or 0.0),
        "current_nav": float(_keep(current_nav, "current_nav", 0.0) or 0.0),
        "last_mark_date": _keep(last_mark_date, "last_mark_date", ""),
        "expected_call_horizon_years": int(_keep(expected_call_horizon_years, "expected_call_horizon_years", 3) or 3),
        "k1_status": _keep(k1_status, "k1_status", "Expected"),
        "notes": _keep(notes, "notes", ""),
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
    tax_year: Optional[int] = None,
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

    tax_year = tax_year if tax_year is not None else tcs.default_checklist_tax_year()
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


def search_live_web(query: str, family_id: int = 0) -> Dict[str, Any]:
    """
    Searches the live web via Google Search grounding (with automatic live web fallback)
    for current tax legislation, state/federal statutory effective dates, court challenges,
    IRS limits, market benchmarks, or real-time financial news.
    """
    import config
    from hvl_common.ai.gemini import search_web_grounded
    from services.request_context import DB_PATH

    fam_id = _resolve_tool_family_id(family_id)
    api_key = config.get_household_gemini_api_key(family_id=fam_id, db_path=DB_PATH) if fam_id else ""
    res = search_web_grounded(query=query, api_key=api_key)
    return {
        "success": bool(res.get("success")),
        "query": query,
        "answer": res.get("formatted_reply") or res.get("answer") or "No web results found.",
        "sources": res.get("sources") or [],
    }


_MAX_FETCH_URL_CHARS = 400
_MAX_FETCH_URL_PATH_CHARS = 200
_MAX_FETCH_URL_QUERY_CHARS = 64
_MAX_FETCH_HOST_CHARS = 100
_MAX_FETCH_HOST_LABEL_CHARS = 40


def validate_fetch_url(url: str) -> Optional[str]:
    """Returns a refusal message when a URL could smuggle household data out (scheme, userinfo, long host/path/query/fragment)."""
    from urllib.parse import urlsplit

    raw = str(url or "").strip()
    if not raw or len(raw) > _MAX_FETCH_URL_CHARS:
        return f"Refused: URL must be 1-{_MAX_FETCH_URL_CHARS} characters."
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return "Refused: only absolute http(s) URLs can be fetched."
    host = parts.hostname or ""
    if "@" in parts.netloc or not host:
        return "Refused: URL must not contain credentials."
    if len(host) > _MAX_FETCH_HOST_CHARS or any(len(label) > _MAX_FETCH_HOST_LABEL_CHARS for label in host.split(".")):
        return "Refused: hostname is unusually long; fetch a plain public reference URL."
    if len(parts.path) > _MAX_FETCH_URL_PATH_CHARS:
        return f"Refused: URL path is longer than {_MAX_FETCH_URL_PATH_CHARS} characters."
    if len(parts.query) > _MAX_FETCH_URL_QUERY_CHARS or len(parts.fragment) > _MAX_FETCH_URL_QUERY_CHARS:
        return f"Refused: URL query/fragment is longer than {_MAX_FETCH_URL_QUERY_CHARS} characters; fetch a plain public reference URL."
    return None


def fetch_web_page(url: str, question: str = "", family_id: int = 0) -> Dict[str, Any]:
    """
    Fetches and summarizes a live public web page or statutory/financial reference URL.
    """
    import config
    from hvl_common.ai.gemini import fetch_web_page_grounded
    from services.request_context import DB_PATH

    url_error = validate_fetch_url(url)
    if url_error:
        return {"success": False, "answer": url_error, "sources": [], "status": "refused_url"}
    fam_id = _resolve_tool_family_id(family_id)
    api_key = config.get_household_gemini_api_key(family_id=fam_id, db_path=DB_PATH) if fam_id else ""
    res = fetch_web_page_grounded(url=url, question=question, api_key=api_key)
    return {
        "success": bool(res.get("success")),
        "url": url,
        "answer": res.get("formatted_reply") or res.get("answer") or "Unable to fetch web page.",
        "sources": res.get("sources") or [],
    }

