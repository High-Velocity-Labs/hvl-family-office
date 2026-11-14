"""
Cash Flow & Balance Sheet Summary tool for the AI Financial Advisor: net worth, liquid cash, investments,
liabilities, annual spending and savings, safe withdrawal rate, and household members.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import account_sync
import db
import security
from services.request_context import DB_PATH
from services.advisor.tool_errors import ADVISOR_TOOL_ERRORS
from services.advisor.tools_core import _resolve_tool_family_id

logger = logging.getLogger(__name__)


def get_cash_flow_summary(family_id: int = 0) -> Dict[str, Any]:
    """
    Retrieves the household balance sheet, net worth snapshot, liquid cash reserves,
    investable portfolios, liabilities, annual spending, safe withdrawal rate, and family members.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    summary: Dict[str, Any] = {
        "net_worth": 0.0,
        "liquid_cash": 0.0,
        "investments": 0.0,
        "real_estate": 0.0,
        "total_liabilities": 0.0,
        "annual_spending": 0.0,
        "annual_savings": 0.0,
        "retirement_age": 0,
        "safe_withdrawal_rate_pct": 0.0,
        "state_residence": "",
        "tax_filing_status": "MFJ",
        "family_members": [],
    }
    try:
        hp = db.household.get_household_profile(family_id=fam_id, db_path=DB_PATH)
        if hp:
            summary.update({
                "state_residence": str(hp.get("state") or ""),
                "tax_filing_status": str(hp.get("filing_status") or "MFJ"),
                "annual_spending": float(hp.get("annual_spending") or 0.0),
                "annual_savings": float(hp.get("annual_savings") or 0.0),
                "retirement_age": int(hp.get("retirement_age") or 0),
            })
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error loading profile assumptions for cash flow: %s", e)
        return {"error": f"Failed to load household profile: {e}", "status": "unavailable"}

    members = security.get_family_members(DB_PATH, family_id=fam_id) if DB_PATH.exists() else []
    summary["family_members"] = [
        {"name": m.get("name"), "relationship": m.get("relationship"), "birthdate": m.get("birthdate")}
        for m in (members or [])
    ]

    try:
        snap = account_sync.get_financial_snapshot(family_id=fam_id)
        if snap:
            cats = snap.get("categories", {})
            liquid_cash = cats.get("cash_liquid", {}).get("total", snap.get("liquid_cash", 0.0))
            investments = (
                cats.get("public_brokerage", {}).get("total", 0.0)
                + cats.get("retirement", {}).get("total", 0.0)
                + cats.get("private_investments", {}).get("total", 0.0)
            )
            real_estate = cats.get("real_estate", {}).get("total", snap.get("real_estate", 0.0))
            liabilities = cats.get("mortgages", {}).get("total", 0.0) + cats.get("credit_cards", {}).get("total", 0.0)
            nw = snap.get("true_net_worth", snap.get("monarch_reported_net_worth", 0.0))
            summary.update({
                "net_worth": nw,
                "liquid_cash": liquid_cash,
                "real_estate": real_estate,
                "investments": investments if investments > 0 else snap.get("total_investments", snap.get("investments", 0.0)),
                "total_liabilities": liabilities if liabilities > 0 else snap.get("total_liabilities", 0.0),
                "safe_withdrawal_rate_pct": round(summary["annual_spending"] / nw * 100, 2) if (nw > 0 and summary["annual_spending"] > 0) else 0.0,
            })
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error loading balance sheet for cash flow: %s", e)
        return {"error": str(e), "status": "unavailable"}

    return summary
