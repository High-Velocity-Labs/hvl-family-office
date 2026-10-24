"""
SSR view-model builder for 4-milestone household setup checklist and guided onboarding state.
"""

from __future__ import annotations

import logging

import db
import security
from routes.helpers import DB_PATH

logger = logging.getLogger(__name__)


def build_onboarding_state(family_id: int = 0) -> dict:
    """Computes the 4-milestone household setup checklist and guided onboarding state."""
    if family_id <= 0:
        return {
            "family_id": 0,
            "family_name": "Family Office",
            "onboarding_completed": True,
            "onboarding_dismissed": False,
            "onboarding_wizard_dismissed": True,
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
        onboarding_wizard_dismissed = bool(
            fam_settings.get("onboarding_wizard_dismissed")
            or onboarding_dismissed
            or onboarding_completed
        )

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
        step_income_done = bool(
            len(comp_records) >= 1
            or float((hp or {}).get("annual_spending") or 0) > 0
            or onboarding_completed
        )

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
            "onboarding_wizard_dismissed": onboarding_wizard_dismissed,
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
            "onboarding_wizard_dismissed": False,
            "show_checklist": False,
            "completed_count": 0,
            "total_count": 4,
            "progress_pct": 0,
            "steps": [],
        }


__all__ = ["build_onboarding_state"]
