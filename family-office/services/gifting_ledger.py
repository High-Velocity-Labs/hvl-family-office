"""
Gifting ledger loader: recipient groups, annual-exclusion limits and per-year gift totals.
Pure service layer; callers (routes, SSR view-models) pass the database path.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import db
from services import statutory_limits


def recipient_limits(name: str, cnt: int, exclusion: float, married_joint: bool) -> dict:
    """Annual-exclusion limits for one recipient group; `applicable_limit` is the couple's for MFJ, else one donor's."""
    return {
        "recipient_name": name,
        "num_people": cnt,
        "beneficiary_count": cnt,
        "limit_from_single_donor": cnt * exclusion,
        "limit_from_couple": cnt * 2 * exclusion,
        "joint_annual_limit": cnt * 2 * exclusion,
        "applicable_limit": cnt * exclusion * (2 if married_joint else 1),
    }


def load_gifting_data(family_id: int, db_path: Path, tax_year: int | None = None):
    """Loads gifting ledger and recipient limits from relational SQLite tables.

    Limits use the annual exclusion of `tax_year` (default: the current year).
    """
    recipients_map = {}
    exclusion = statutory_limits.annual_gift_exclusion(tax_year if tax_year is not None else date.today().year)
    limits = {}
    summary = {}
    yearly = {}

    if db_path.exists():
        hp = db.household.get_household_profile(family_id=family_id, db_path=db_path) or {}
        married_joint = str(hp.get("filing_status") or "MFJ").upper() == "MFJ"
        rec_rows = db.gifting.list_gift_recipients(family_id=family_id, db_path=db_path)
        for r in rec_rows:
            rec_id = r["recipient_id"]
            name = r["recipient_group_name"]
            cnt = int(r["member_count"] or 1)
            recipients_map[rec_id] = name
            limits[name] = recipient_limits(name, cnt, exclusion, married_joint)
            summary[name] = {}

        gift_rows = db.gifting.list_gifts(family_id=family_id, db_path=db_path)
        for g in gift_rows:
            rec_name = g["recipient_name"]
            if not rec_name:
                continue
            yr = str(g["year"])
            amt = float(g["amount"])

            summary.setdefault(rec_name, {})[yr] = round(amt, 2)

            if yr not in yearly:
                yearly[yr] = {"gifts": [], "total_given": 0.0}
            yearly[yr]["gifts"].append({
                "recipient": rec_name,
                "amount": round(amt, 2),
                "date": f"{yr}-01-01",
                "notes": g["notes"] or "",
            })
            yearly[yr][rec_name] = round(amt, 2)
            yearly[yr]["total_given"] = round(yearly[yr]["total_given"] + amt, 2)

    return limits, summary, yearly
