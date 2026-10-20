"""
services/private_markets_service.py: Private Markets & LP Commitment Book Service.
Tracks venture/PE/real estate fund commitments, capital called, unfunded dry powder,
distributions, TVPI/DPI performance, K-1 tax status, and scenario capital call schedules.
Strictly adheres to Database-per-Family physical multi-tenancy and encrypted storage.
"""

from __future__ import annotations
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

import config
from routes.helpers import sanitize_text
import security

logger = logging.getLogger(__name__)

DEFAULT_DEMO_LP_COMMITMENTS: List[Dict[str, Any]] = [
    {
        "id": "lp_demo_1",
        "fund_name": "Horizon Venture Partners VIII",
        "fund_type": "Venture",
        "vintage_year": 2021,
        "total_commitment": 500000.0,
        "capital_called": 425000.0,
        "unfunded_commitment": 75000.0,
        "distributions_received": 110000.0,
        "current_nav": 640000.0,
        "last_mark_date": "2026-06-30",
        "expected_call_horizon_years": 2,
        "k1_status": "Received",
        "notes": "Late-stage AI and cloud enterprise venture portfolio.",
    },
    {
        "id": "lp_demo_2",
        "fund_name": "Beacon Capital Buyout Fund VI",
        "fund_type": "Private Equity",
        "vintage_year": 2022,
        "total_commitment": 750000.0,
        "capital_called": 450000.0,
        "unfunded_commitment": 300000.0,
        "distributions_received": 45000.0,
        "current_nav": 520000.0,
        "last_mark_date": "2026-03-31",
        "expected_call_horizon_years": 3,
        "k1_status": "Sent to CPA",
        "notes": "B2B enterprise software buyout vintage.",
    },
    {
        "id": "lp_demo_3",
        "fund_name": "Pinnacle Real Estate Opportunity II",
        "fund_type": "Real Estate",
        "vintage_year": 2023,
        "total_commitment": 350000.0,
        "capital_called": 175000.0,
        "unfunded_commitment": 175000.0,
        "distributions_received": 18000.0,
        "current_nav": 190000.0,
        "last_mark_date": "2025-12-31",
        "expected_call_horizon_years": 3,
        "k1_status": "Expected",
        "notes": "Logistics and student housing acquisitions.",
    },
]


def _check_stale_mark(date_str: str) -> bool:
    if not date_str:
        return True
    try:
        mark_dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        now_dt = datetime.now(timezone.utc).date()
        return (now_dt - mark_dt).days > 120
    except Exception:
        return False


def _compute_metrics(item: Dict[str, Any]) -> Dict[str, Any]:
    called = float(item.get("capital_called") or 0.0)
    committed = float(item.get("total_commitment") or 0.0)
    unfunded = float(
        item.get("unfunded_commitment")
        if item.get("unfunded_commitment") is not None
        else max(0.0, committed - called)
    )
    dist = float(item.get("distributions_received") or 0.0)
    nav = float(item.get("current_nav") or 0.0)
    mark_date = str(item.get("last_mark_date") or "").strip()

    dpi = round(dist / called, 2) if called > 0 else 0.0
    rvpi = round(nav / called, 2) if called > 0 else 0.0
    tvpi = round((dist + nav) / called, 2) if called > 0 else 0.0
    is_stale = _check_stale_mark(mark_date) if mark_date else True

    item_out = dict(item)
    item_out["capital_called"] = called
    item_out["total_commitment"] = committed
    item_out["unfunded_commitment"] = unfunded
    item_out["distributions_received"] = dist
    item_out["current_nav"] = nav
    item_out["dpi"] = dpi
    item_out["rvpi"] = rvpi
    item_out["tvpi"] = tvpi
    item_out["is_mark_stale"] = is_stale
    item_out["committed_str"] = f"${committed:,.0f}" if committed > 0 else "--"
    item_out["called_str"] = f"${called:,.0f}" if called > 0 else "--"
    item_out["unfunded_str"] = f"${unfunded:,.0f}" if unfunded > 0 else "--"
    item_out["nav_str"] = f"${nav:,.0f}" if nav > 0 else "--"
    item_out["dist_str"] = f"${dist:,.0f}" if dist > 0 else "--"
    item_out["tvpi_str"] = f"{tvpi:.2f}x" if tvpi > 0 else "--"
    item_out["dpi_str"] = f"{dpi:.2f}x" if dpi > 0 else "--"
    return item_out


def _compute_portfolio_summary(items: List[Dict[str, Any]], family_id: int) -> Dict[str, Any]:
    total_committed = sum(float(i.get("total_commitment") or 0.0) for i in items)
    total_called = sum(float(i.get("capital_called") or 0.0) for i in items)
    total_unfunded = sum(float(i.get("unfunded_commitment") or 0.0) for i in items)
    total_dist = sum(float(i.get("distributions_received") or 0.0) for i in items)
    total_nav = sum(float(i.get("current_nav") or 0.0) for i in items)

    portfolio_tvpi = round((total_dist + total_nav) / total_called, 2) if total_called > 0 else 0.0
    portfolio_dpi = round(total_dist / total_called, 2) if total_called > 0 else 0.0

    valid_dates = [i.get("last_mark_date") for i in items if i.get("last_mark_date")]
    oldest_mark_date = min(valid_dates) if valid_dates else None
    has_stale_mark = any(i.get("is_mark_stale", False) for i in items)

    liquid_cash = 0.0
    if family_id > 0:
        try:
            import monarch_service
            snap = monarch_service.get_financial_snapshot(family_id=family_id)
            liquid_cash = float(snap.get("categories", {}).get("cash_liquid", {}).get("total", 0.0) or 0.0)
        except Exception:
            liquid_cash = 0.0

    coverage_ratio = round(liquid_cash / total_unfunded, 2) if total_unfunded > 0 else 999.0

    return {
        "total_committed": total_committed,
        "total_called": total_called,
        "total_unfunded": total_unfunded,
        "total_distributions": total_dist,
        "total_nav": total_nav,
        "portfolio_tvpi": portfolio_tvpi,
        "portfolio_dpi": portfolio_dpi,
        "oldest_mark_date": oldest_mark_date,
        "has_stale_mark": has_stale_mark,
        "liquid_cash_coverage_ratio": coverage_ratio,
        "total_funds_count": len(items),
        "total_committed_str": f"${total_committed:,.0f}" if total_committed > 0 else "--",
        "total_called_str": f"${total_called:,.0f}" if total_called > 0 else "--",
        "total_unfunded_str": f"${total_unfunded:,.0f}" if total_unfunded > 0 else "--",
        "total_nav_str": f"${total_nav:,.0f}" if total_nav > 0 else "--",
        "total_dist_str": f"${total_dist:,.0f}" if total_dist > 0 else "--",
        "portfolio_tvpi_str": f"{portfolio_tvpi:.2f}x" if portfolio_tvpi > 0 else "--",
        "portfolio_dpi_str": f"{portfolio_dpi:.2f}x" if portfolio_dpi > 0 else "--",
        "coverage_ratio_str": f"{coverage_ratio:.1f}x" if coverage_ratio < 999 else "Covered",
    }


def _auto_seed_from_accounts_or_demo(family_id: int, target_db: Path) -> List[Dict[str, Any]]:
    """Seeds LP positions from connected private asset accounts or demo defaults."""
    seeded: List[Dict[str, Any]] = []
    try:
        from ssr.formatting import get_private_investments_data
        priv_data = get_private_investments_data(family_id=family_id) or {}
        items = priv_data.get("items") or []
        for it in items:
            nav = float(it.get("current_value") or 0.0)
            if nav <= 0:
                continue
            name = it.get("name") or "Private Investment"
            cat = str(it.get("category") or "").lower()
            f_type = "Venture" if "venture" in cat or "startup" in cat else (
                "Real Estate" if "real estate" in cat or "property" in cat else "Private Equity"
            )
            seeded.append({
                "id": f"lp_acc_{it.get('account_id') or uuid.uuid4().hex[:6]}",
                "account_id": str(it.get("account_id") or ""),
                "fund_name": name,
                "fund_type": f_type,
                "vintage_year": 2022,
                "total_commitment": round(nav * 1.25, 2),
                "capital_called": nav,
                "unfunded_commitment": round(nav * 0.25, 2),
                "distributions_received": round(nav * 0.10, 2),
                "current_nav": nav,
                "last_mark_date": "2026-06-30",
                "expected_call_horizon_years": 3,
                "k1_status": "Expected",
                "notes": f"Auto-synced from {it.get('institution') or 'connected portfolio account'}.",
            })
    except Exception as e:
        logger.debug("Failed auto-seeding LP commitments from accounts: %s", e)

    if not seeded:
        seeded = [dict(d) for d in DEFAULT_DEMO_LP_COMMITMENTS]

    return seeded


def get_lp_commitments(family_id: int = 0) -> List[Dict[str, Any]]:
    """Loads all annotated LP commitments for the family from encrypted storage."""
    if not family_id or family_id <= 0:
        return []
    target_db = config.get_family_db_path(family_id)
    raw = security.db_load_encrypted(target_db, "lp_commitments", family_id=family_id)
    if raw is None or not isinstance(raw, list):
        items = _auto_seed_from_accounts_or_demo(family_id=family_id, target_db=target_db)
    else:
        items = raw

    return [_compute_metrics(it) for it in items]


def get_lp_commitments_summary(family_id: int = 0) -> Dict[str, Any]:
    """Returns annotated commitments list plus portfolio-wide aggregates and coverage ratios."""
    if not family_id or family_id <= 0:
        return {"commitments": [], "summary": _compute_portfolio_summary([], 0)}
    items = get_lp_commitments(family_id=family_id)
    summary = _compute_portfolio_summary(items, family_id=family_id)
    return {"commitments": items, "summary": summary}


def save_lp_commitment(family_id: int = 0, item_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Creates or updates an LP commitment in the family's encrypted storage."""
    if not family_id or family_id <= 0 or not item_data:
        return {}
    target_db = config.get_family_db_path(family_id)
    raw = security.db_load_encrypted(target_db, "lp_commitments", family_id=family_id)
    items = list(raw) if (raw is not None and isinstance(raw, list)) else _auto_seed_from_accounts_or_demo(family_id, target_db)

    item_id = str(item_data.get("id") or "").strip()
    if not item_id or item_id.startswith("lp_demo_"):
        item_id = f"lp_{uuid.uuid4().hex[:8]}"

    total_c = max(0.0, float(item_data.get("total_commitment") or 0.0))
    called_c = max(0.0, float(item_data.get("capital_called") or 0.0))
    raw_unf = item_data.get("unfunded_commitment")
    unfunded_c = max(0.0, float(raw_unf) if raw_unf is not None else max(0.0, total_c - called_c))

    fund_type = str(item_data.get("fund_type") or "Private Equity")
    valid_types = ("Venture", "Private Equity", "Real Estate", "Private Credit", "Direct / Angel")
    if fund_type not in valid_types:
        fund_type = "Private Equity"

    k1_status = str(item_data.get("k1_status") or "Expected")
    valid_k1 = ("Not Applicable", "Expected", "Received", "Sent to CPA")
    if k1_status not in valid_k1:
        k1_status = "Expected"

    saved_obj: Dict[str, Any] = {
        "id": item_id,
        "account_id": str(item_data.get("account_id") or "").strip(),
        "fund_name": sanitize_text(str(item_data.get("fund_name") or "Private Fund"), max_length=120, field_name="Fund Name", required=True),
        "fund_type": fund_type,
        "vintage_year": int(item_data.get("vintage_year") or 2022),
        "total_commitment": total_c,
        "capital_called": called_c,
        "unfunded_commitment": unfunded_c,
        "distributions_received": max(0.0, float(item_data.get("distributions_received") or 0.0)),
        "current_nav": max(0.0, float(item_data.get("current_nav") or 0.0)),
        "last_mark_date": sanitize_text(str(item_data.get("last_mark_date") or ""), max_length=12, field_name="Mark Date", required=False),
        "expected_call_horizon_years": max(1, min(10, int(item_data.get("expected_call_horizon_years") or 3))),
        "k1_status": k1_status,
        "notes": sanitize_text(str(item_data.get("notes") or ""), max_length=500, field_name="Notes", required=False),
    }

    idx = next((i for i, x in enumerate(items) if str(x.get("id")) == item_id), -1)
    if idx >= 0:
        items[idx] = saved_obj
    else:
        items.append(saved_obj)

    security.db_save_encrypted(target_db, "lp_commitments", "holdings", items, family_id=family_id)
    return _compute_metrics(saved_obj)


def delete_lp_commitment(family_id: int = 0, item_id: str = "") -> bool:
    """Removes an annotated LP commitment from the family's encrypted storage."""
    if not family_id or family_id <= 0 or not item_id:
        return False
    target_db = config.get_family_db_path(family_id)
    raw = security.db_load_encrypted(target_db, "lp_commitments", family_id=family_id)
    items = list(raw) if (raw is not None and isinstance(raw, list)) else _auto_seed_from_accounts_or_demo(family_id, target_db)

    filtered = [it for it in items if str(it.get("id")) != str(item_id)]
    if len(filtered) == len(items):
        return False

    security.db_save_encrypted(target_db, "lp_commitments", "holdings", filtered, family_id=family_id)
    return True


def get_lp_call_schedule(family_id: int = 0, accelerate: bool = False) -> Dict[int, float]:
    """
    Calculates projected annual capital call drawdowns from active unfunded commitments.
    When accelerate is True, unfunded calls are compressed into 18-24 months (years 2026-2027).
    """
    if not family_id or family_id <= 0:
        return {}
    items = get_lp_commitments(family_id=family_id)
    schedule: Dict[int, float] = {}
    current_year = 2026
    for it in items:
        unfunded = float(it.get("unfunded_commitment") or 0.0)
        if unfunded <= 0:
            continue
        horizon = 2 if accelerate else max(1, int(it.get("expected_call_horizon_years") or 3))
        annual_call = unfunded / horizon
        for y in range(horizon):
            yr = current_year + y
            schedule[yr] = round(schedule.get(yr, 0.0) + annual_call, 2)
    return schedule
