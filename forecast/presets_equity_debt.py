"""
forecast/presets_equity_debt.py: Equity grant liquidation and mortgage debt event builders.
Extracted from forecast/presets.py.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
from pathlib import Path

import monarch_service
from db.session import resolve_db_path
from forecast.storage import get_db_path


def build_equity_grant_events(family_id: int, active_db: Path) -> List[Dict[str, Any]]:
    """Generates equity grant and option liquidation events based on household grants."""
    events: List[Dict[str, Any]] = []
    if active_db.exists() and family_id:
        try:
            from db.equity import list_unexercised_grants
            decrypted_grants = list_unexercised_grants(family_id=family_id, db_path=active_db)

            if decrypted_grants:
                g1 = decrypted_grants[0]
                is_rsu1 = g1["grant_type"] == "RSU"
                events.append({
                    "id": "evt_company_equity_exercise_custom",
                    "name": f"Liquidate {g1['label']} RSUs" if is_rsu1 else f"Exercise {g1['label']} Options",
                    "category": "company_equity",
                    "event_type": "single_spike",
                    "icon": "evt-equity",
                    "year": 2027,
                    "end_year": 2027,
                    "action": "cashless_repurchase",
                    "options_quantity": float(g1["unexercised"]),
                    "grant_id": g1["grant_id"],
                    "reinvestment_strategy": "index_mirror",
                    "include_wa_tax": False,
                    "description": (
                        f"Company liquidates {int(g1['unexercised']):,} vested RSUs from {g1['label']} at FMV; net proceeds reinvested."
                        if is_rsu1 else
                        f"Company repurchases {int(g1['unexercised']):,} vested options from {g1['label']} at FMV; net proceeds reinvested."
                    ),
                })

                for extra_g in decrypted_grants[1:]:
                    is_rsu_extra = extra_g["grant_type"] == "RSU"
                    events.append({
                        "id": f"evt_equity_{extra_g['grant_id']}_{extra_g['grant_type'].lower()}",
                        "name": f"Liquidate {extra_g['label']} RSUs" if is_rsu_extra else f"Exercise {extra_g['label']} Options",
                        "category": "company_equity",
                        "event_type": "single_spike",
                        "icon": "evt-equity",
                        "year": 2028,
                        "end_year": 2028,
                        "action": "cashless_repurchase",
                        "options_quantity": float(extra_g["unexercised"]),
                        "grant_id": extra_g["grant_id"],
                        "reinvestment_strategy": "index_mirror",
                        "include_wa_tax": False,
                        "description": (
                            f"Company liquidates {int(extra_g['unexercised']):,} vested RSUs from {extra_g['label']} at FMV; net proceeds reinvested."
                            if is_rsu_extra else
                            f"Company repurchases {int(extra_g['unexercised']):,} vested options from {extra_g['label']} at FMV; net proceeds reinvested."
                        ),
                    })
        except Exception as e:
            print(f"[WARN] Error loading equity grants for event catalog: {e}")

    if not any(e["category"] == "company_equity" for e in events):
        events.append({
            "id": "evt_company_equity_exercise_custom",
            "name": "Exercise Stock Options (Optional)",
            "category": "company_equity",
            "event_type": "single_spike",
            "icon": "evt-equity",
            "year": 2027,
            "end_year": 2027,
            "action": "cashless_repurchase",
            "options_quantity": 0.0,
            "grant_id": None,
            "reinvestment_strategy": "index_mirror",
            "include_wa_tax": False,
            "description": "Optional stock option exercise modeling; net post-tax cash proceeds reinvested.",
        })

    return events


def build_debt_and_mortgage_events(
    family_id: int,
    snapshot: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Generates primary mortgage payoff and refinance events from balance sheet."""
    events: List[Dict[str, Any]] = []

    mortgage_bal_db = 0.0
    mortgage_service_db = 0.0
    try:
        snap = snapshot or monarch_service.get_financial_snapshot(family_id=family_id)
        mortgage_bal_db = abs(float(snap.get("categories", {}).get("mortgages", {}).get("total", 0.0) or 0.0))
        if mortgage_bal_db > 0:
            r_m = 0.045 / 12.0
            n_m = 360
            mortgage_service_db = mortgage_bal_db * (r_m * ((1.0 + r_m) ** n_m)) / (((1.0 + r_m) ** n_m) - 1.0) * 12.0
    except Exception:
        pass

    if mortgage_bal_db > 0:
        events.append({
            "id": "evt_mortgage_payoff",
            "name": f"Pay Off Primary Mortgage (${mortgage_bal_db/1e6:.2f}M)" if mortgage_bal_db >= 1e6 else f"Pay Off Primary Mortgage (${int(mortgage_bal_db/1e3)}k)",
            "category": "debt_payoff",
            "event_type": "single_spike",
            "icon": "evt-debt",
            "year": 2027,
            "end_year": 2027,
            "amount": round(mortgage_bal_db, 2),
            "funding_source": "taxable_brokerage",
            "annual_cashflow_saved": round(mortgage_service_db, 2),
            "description": f"Lump-sum payoff of primary mortgage loan balance (${mortgage_bal_db:,.0f}) from liquid assets, eliminating monthly debt service.",
        })

    events.append({
        "id": "evt_refinance_mortgage",
        "name": "Refinance Mortgage (30-Yr Fixed)",
        "category": "refinance",
        "event_type": "single_spike",
        "icon": "evt-refi",
        "refinance_type": "fixed",
        "year": 2027,
        "end_year": 2027,
        "new_interest_rate": 0.045,
        "new_term_years": 30,
        "closing_costs": 8000.0,
        "description": "Refinance primary mortgage to 4.50% 30-year fixed rate, reducing ongoing annual debt service.",
    })

    events.append({
        "id": "evt_refinance_mortgage_arm",
        "name": "Refinance Mortgage (7/1 ARM)",
        "category": "refinance",
        "event_type": "single_spike",
        "icon": "evt-refi",
        "refinance_type": "arm",
        "year": 2027,
        "end_year": 2027,
        "new_interest_rate": 0.03875,
        "new_term_years": 30,
        "arm_fixed_years": 7,
        "arm_reset_rate": 0.055,
        "closing_costs": 8000.0,
        "description": "Refinance with 7/1 ARM @ 3.88% introductory rate for 7 years (resets to 5.50%), maximizing near-term liquidity and cash flow.",
    })

    return events


def build_vacation_and_lifestyle_events() -> List[Dict[str, Any]]:
    """Generates standard lifestyle aviation and vacation home property events."""
    return [
        {
            "id": "evt_netjets_membership",
            "name": "Fractional Jet / Travel Membership ($250k/yr)",
            "category": "lifestyle",
            "event_type": "duration",
            "icon": "evt-travel",
            "year": 2027,
            "end_year": 2031,
            "annual_amount": 250000.0,
            "is_outflow": True,
            "apply_gogo_taper": False,
            "funding_source": "taxable_brokerage",
            "description": "5-year fractional private aviation and luxury travel membership (~$250k/year outflow).",
        },
        {
            "id": "evt_vacation_home",
            "name": "Purchase Vacation Property ($1.5M)",
            "category": "real_estate",
            "re_action": "buy_vacation",
            "event_type": "single_spike",
            "icon": "evt-vacation-home",
            "year": 2028,
            "end_year": 2028,
            "purchase_price": 1500000.0,
            "down_payment_pct": 0.20,
            "mortgage_term": "30_fixed",
            "interest_rate": 0.055,
            "funding_source": "taxable_brokerage",
            "annual_ongoing_carrying_cost": 25000.0,
            "description": "Purchase $1.5M vacation property with 20% down ($300k) and $1.2M 30-year fixed mortgage at 5.5%.",
        },
        {
            "id": "evt_vacation_home_arm",
            "name": "Purchase Vacation Property (7/1 ARM)",
            "category": "real_estate",
            "re_action": "buy_vacation",
            "event_type": "single_spike",
            "icon": "evt-vacation-home",
            "year": 2028,
            "end_year": 2028,
            "purchase_price": 1500000.0,
            "down_payment_pct": 0.20,
            "mortgage_term": "7_1_arm",
            "interest_rate": 0.04875,
            "arm_fixed_years": 7,
            "arm_reset_rate": 0.0575,
            "funding_source": "taxable_brokerage",
            "annual_ongoing_carrying_cost": 25000.0,
            "description": "Purchase $1.5M vacation property with 7/1 ARM @ 4.88% intro rate (resets to 5.75% after 7 years).",
        },
    ]

