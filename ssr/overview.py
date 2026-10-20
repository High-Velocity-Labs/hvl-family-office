"""
SSR view-model builder for Overview hero KPI cards.
"""

from __future__ import annotations
import logging

import db
import security
from routes.helpers import DB_PATH
from ssr.accounts import build_ssr_accounts
from ssr.formatting import fmt_currency, fmt_short_currency
from ssr.scenarios import build_ssr_scenarios
from ssr.settings import build_ssr_settings

logger = logging.getLogger(__name__)


def build_onboarding_state(family_id: int = 0) -> dict:
    """Computes the 4-milestone household setup checklist and guided onboarding state."""
    if family_id <= 0:
        return {
            "family_id": 0,
            "family_name": "Family Office",
            "onboarding_completed": True,
            "onboarding_dismissed": False,
            "show_checklist": False,
            "completed_count": 4,
            "total_count": 4,
            "progress_pct": 100,
            "steps": [],
        }

    try:
        fam = security.get_family(DB_PATH, family_id=family_id) or {}
        family_name = str(fam.get("name") or "Family Office")
        fam_settings = fam.get("settings") if isinstance(fam.get("settings"), dict) else {}
        onboarding_completed = bool(fam_settings.get("onboarding_completed"))
        onboarding_dismissed = bool(fam_settings.get("onboarding_dismissed"))

        hp = db.families.get_household_profile(family_id=family_id, db_path=DB_PATH)
        members = security.get_family_members(DB_PATH, family_id=family_id) or []
        accounts = db.accounts.list_accounts(family_id=family_id, db_path=DB_PATH) or []
        comp_records = db.compensation.list_compensation_records(family_id=family_id, db_path=DB_PATH) or []

        step_profile_done = bool(hp is not None or onboarding_completed)
        state_val = (hp or {}).get("state", "WA")
        filing_val = (hp or {}).get("filing_status", "MFJ")

        has_configured_member = any(bool(m.get("birthdate")) for m in members) or len(members) >= 2
        step_members_done = bool(has_configured_member or (len(members) >= 1 and hp is not None))

        step_accounts_done = len(accounts) >= 1
        step_income_done = bool(len(comp_records) >= 1 or onboarding_completed)

        steps = [
            {
                "num": 1,
                "key": "profile",
                "title": "Household & Tax Profile",
                "subtitle": f"{state_val} • {filing_val}",
                "done": step_profile_done,
            },
            {
                "num": 2,
                "key": "members",
                "title": "Family Members",
                "subtitle": f"{len(members)} member{'s' if len(members) != 1 else ''} configured",
                "done": step_members_done,
            },
            {
                "num": 3,
                "key": "accounts",
                "title": "Accounts & Balance Sheet",
                "subtitle": f"{len(accounts)} account{'s' if len(accounts) != 1 else ''} linked or manual",
                "done": step_accounts_done,
            },
            {
                "num": 4,
                "key": "income",
                "title": "Income & Spending Targets",
                "subtitle": f"{len(comp_records)} income stream{'s' if len(comp_records) != 1 else ''}",
                "done": step_income_done,
            },
        ]
        completed_count = sum(1 for s in steps if s["done"])
        total_count = len(steps)
        progress_pct = int(round((completed_count / total_count) * 100)) if total_count else 100
        show_checklist = bool(not onboarding_completed and not onboarding_dismissed and completed_count < total_count)

        return {
            "family_id": family_id,
            "family_name": family_name,
            "state": state_val,
            "filing_status": filing_val,
            "annual_spending": float((hp or {}).get("annual_spending") or 0.0),
            "retirement_age": int((hp or {}).get("retirement_age") or 65),
            "onboarding_completed": onboarding_completed,
            "onboarding_dismissed": onboarding_dismissed,
            "show_checklist": show_checklist,
            "completed_count": completed_count,
            "total_count": total_count,
            "progress_pct": progress_pct,
            "steps": steps,
        }
    except Exception as e:
        logger.warning(f"Error building onboarding state for family {family_id}: {e}")
        return {
            "family_id": family_id,
            "family_name": "Family Office",
            "onboarding_completed": False,
            "onboarding_dismissed": False,
            "show_checklist": False,
            "completed_count": 0,
            "total_count": 4,
            "progress_pct": 0,
            "steps": [],
        }


def build_ssr_overview(snapshot: dict, private_investments: dict | None = None, family_id: int = 0) -> dict:
    """Prepares formatted strings for SSR hero KPI cards and customizable widgets on initial landing."""
    from ssr.widgets import build_overview_widgets

    onboarding = build_onboarding_state(family_id=family_id) if family_id > 0 else {}
    widgets_state = build_overview_widgets(family_id=family_id, snapshot=snapshot)
    if not snapshot:
        res: dict = {"widgets": widgets_state}
        if onboarding:
            res["onboarding"] = onboarding
        return res
    equity_data = snapshot.get("company_equity") or {}
    strike_cost = float(equity_data.get("total_strike_cost_needed") or 0.0)
    tax_drag = float(equity_data.get("total_tax_drag") or 0.0)
    has_strike = strike_cost > 0
    has_tax_drag = tax_drag > 0
    has_adjustment = has_strike or has_tax_drag

    if has_strike and has_tax_drag:
        net_worth_label = "NET WORTH (POST-TAX & STRIKE)"
    elif has_tax_drag:
        net_worth_label = "NET WORTH (POST-TAX)"
    elif has_strike:
        net_worth_label = "NET WORTH (POST-STRIKE)"
    else:
        net_worth_label = "TOTAL NET WORTH"

    if has_adjustment:
        parts = []
        if has_strike:
            parts.append(f"-{fmt_short_currency(strike_cost)} strike")
        if has_tax_drag:
            parts.append(f"-{fmt_short_currency(tax_drag)} tax")
        net_worth_sub = f"Adjusted: {', '.join(parts)}"
    else:
        net_worth_sub = "Consolidated balance sheet"

    company_name = equity_data.get("company_name") or "Company"
    if has_adjustment:
        equity_label = f"{company_name.upper()} POST-TAX EQUITY"
    else:
        equity_label = f"{company_name.upper()} EQUITY"

    categories = snapshot.get("categories") or {}
    cash = float((categories.get("cash_liquid") or {}).get("total") or 0.0)
    public_b = float((categories.get("public_brokerage") or {}).get("total") or 0.0)
    liquid_total = cash + public_b

    re_val = float((categories.get("real_estate") or {}).get("total") or 0.0)
    mort = abs(float((categories.get("mortgages") or {}).get("total") or 0.0))
    re_equity = re_val - mort

    ret_val = float((categories.get("retirement") or {}).get("total") or 0.0)

    priv_inv = private_investments or {}
    if "total_value" in priv_inv:
        priv_val = float(priv_inv.get("total_value") or 0.0)
    else:
        priv_val = float((categories.get("private_investments") or {}).get("total") or 0.0)

    if "items" in priv_inv:
        priv_count = len(priv_inv.get("items") or [])
    else:
        priv_count = len((categories.get("private_investments") or {}).get("accounts") or [])

    return {
        "true_net_worth": fmt_currency(snapshot.get("true_net_worth"), 0),
        "net_worth_label": net_worth_label,
        "net_worth_sub": net_worth_sub,
        "monarch_net_worth": fmt_currency(snapshot.get("monarch_reported_net_worth"), 0),
        "equity_label": equity_label,
        "equity_net_value": fmt_currency(equity_data.get("true_net_post_tax_value", 0), 0),
        "equity_gross": f"Gross: {fmt_short_currency(equity_data.get('total_gross_equity_value', 0))}",
        "liquid_portfolio": fmt_currency(liquid_total, 0),
        "liquid_sub": f"Brokerage: {fmt_short_currency(public_b)} | Cash: {fmt_short_currency(cash)}",
        "real_estate_equity": fmt_currency(re_equity, 0),
        "real_estate_sub": f"{fmt_short_currency(re_val)} home less {fmt_short_currency(mort)} debt",
        "private_investments": fmt_currency(priv_val, 0),
        "private_sub": f"{priv_count} Active Private Holdings • Monarch NAV",
        "retirement_assets": fmt_currency(ret_val, 0),
        "onboarding": onboarding,
        "widgets": widgets_state,
    }


__all__ = [
    "DB_PATH",
    "build_onboarding_state",
    "build_ssr_accounts",
    "build_ssr_overview",
    "build_ssr_scenarios",
    "build_ssr_settings",
    "db",
    "security",
]
