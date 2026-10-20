"""
forecast/presets_family_edu.py: Education, eldercare, and family gifting event catalog builders.
Extracted from forecast/presets.py.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
from pathlib import Path

from forecast.storage import (
    load_children_k12_tuition,
    load_children_edu_reserves,
)


def build_education_events(
    family_id: int,
    children_k12: Optional[List[Dict[str, Any]]],
    children_edu: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Generates per-child K-12 tuition and college 529 drawdown events."""
    events: List[Dict[str, Any]] = []

    # K-12 private school
    if children_k12 is None:
        children_k12 = load_children_k12_tuition(family_id=family_id)
    if children_k12:
        for child in children_k12:
            c_name = child["name"]
            f_name = child["first_name"]
            k_start = child["k12_start"]
            k_end = child["k12_end"]
            k_amt = child["annual_amount"]
            c_id = child["user_id"]
            events.append({
                "id": f"evt_k12_{f_name.lower()}",
                "name": f"{c_name}'s K-12 Private School Tuition",
                "category": "education",
                "event_type": "duration",
                "icon": "evt-k12",
                "child_user_id": c_id,
                "child_name": c_name,
                "year": k_start,
                "end_year": k_end,
                "annual_amount": k_amt,
                "override_annual_amount": k_amt,
                "sync_with_ledger": True,
                "ledger_source_type": "k12",
                "funding_source": "cash_flow",
                "use_529_k12_election": True,
                "description": f"Private school tuition for {c_name} across academic years {k_start}–{k_end} (~${int(k_amt):,}/yr). Synced with live Education Ledger.",
            })
    else:
        events.append({
            "id": "evt_k12_education",
            "name": "K-12 Private School (Optional)",
            "category": "education",
            "event_type": "duration",
            "icon": "evt-k12",
            "year": 2026,
            "end_year": 2033,
            "annual_amount": 15000.0,
            "override_annual_amount": 15000.0,
            "sync_with_ledger": False,
            "funding_source": "cash_flow",
            "use_529_k12_election": True,
            "description": "Optional private school tuition baseline (~$15,000/yr national average).",
        })

    # College 529 drawdowns
    if children_edu is None:
        children_edu = load_children_edu_reserves(family_id=family_id)
    if children_edu:
        for child in children_edu:
            c_name = child["name"]
            f_name = child["first_name"]
            c_start = child["college_start"]
            c_end = c_start + 3
            c_bal = child["current_529_balance"]
            c_id = child["user_id"]
            events.append({
                "id": f"evt_college_{f_name.lower()}",
                "name": f"{c_name}'s College Tuition (4-Yr 529 Draw)",
                "category": "college",
                "event_type": "duration",
                "icon": "evt-college",
                "child_user_id": c_id,
                "child_name": c_name,
                "year": c_start,
                "end_year": c_end,
                "annual_amount": 85000.0,
                "override_annual_amount": 85000.0,
                "benchmark_tier": "Private Non-Profit",
                "sync_with_ledger": False,
                "ledger_source_type": "college",
                "use_529_reserves": True,
                "funding_source": "529_education_reserve",
                "description": f"4-year undergraduate college tuition (~$85,000/yr) for {c_name} starting in {c_start}. Draws from {f_name}'s 529/530A reserve funds (~${int(c_bal/1e3)}k), with any shortfall drawn from liquid accounts.",
            })
    else:
        events.append({
            "id": "evt_college_undergrad",
            "name": "Undergraduate College Tuition (Optional)",
            "category": "college",
            "event_type": "duration",
            "icon": "evt-college",
            "year": 2029,
            "end_year": 2032,
            "annual_amount": 28000.0,
            "use_529_reserves": True,
            "funding_source": "529_education_reserve",
            "description": "Optional 4-year undergraduate college tuition (~$28,000/yr national average).",
        })

    return events


def build_family_care_and_gifting_events(
    family_id: int,
    active_db: Path,
) -> List[Dict[str, Any]]:
    """Generates eldercare and annual exclusion family gifting events."""
    events: List[Dict[str, Any]] = []

    # Eldercare
    events.append({
        "id": "evt_eldercare_support",
        "name": "Elderly Parent Assisted Living Support",
        "category": "eldercare",
        "event_type": "duration",
        "icon": "evt-eldercare",
        "year": 2030,
        "end_year": 2035,
        "annual_care_cost": 80000.0,
        "sibling_split_pct": 50.0,
        "parent_offset_annual": 0.0,
        "annual_amount": 40000.0,
        "funding_source": "cash_flow",
        "description": "Assisted living support for aging parent, shared 50/50 with sibling.",
    })

    # Family gifting
    recip_count = 0
    if family_id and active_db.exists():
        from db.gifting import count_gift_recipients
        recip_count = count_gift_recipients(family_id=family_id, db_path=active_db)

    if recip_count > 0:
        gift_annual = recip_count * 38000.0
        events.append({
            "id": "evt_family_gifting",
            "name": f"Annual Family Gifting Program (${int(gift_annual/1000)}k/yr)",
            "category": "gifting",
            "event_type": "duration",
            "icon": "evt-gifting",
            "year": 2026,
            "end_year": 2045,
            "annual_amount": gift_annual,
            "funding_source": "cash_flow",
            "description": f"Joint spousal annual exclusion gifts ($38,000 x {recip_count} recipient groups) through-line.",
        })
    else:
        events.append({
            "id": "evt_family_gifting",
            "name": "Annual Family Gifting Program (Optional)",
            "category": "gifting",
            "event_type": "duration",
            "icon": "evt-gifting",
            "year": 2026,
            "end_year": 2045,
            "annual_amount": 38000.0,
            "funding_source": "cash_flow",
            "description": "Optional joint spousal annual exclusion gifts ($38,000/recipient group) through-line.",
        })

    return events
