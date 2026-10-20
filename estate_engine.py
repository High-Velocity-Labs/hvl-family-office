"""
HVL Family Office: Estate & Generational Wealth Engine
Core Capabilities:
1. Dynamic Federal Gift & Estate Tax calculation (current statutory unified exemption vs TCJA sunset scenario).
2. Dynamic State-by-State Estate Tax Engine (WA RCW 83.100, NY Tax Law § 952 cliff, MA, OR, and zero-tax states like CA, TX, FL, NV).
3. IRC § 2058 state death tax deduction modeling against federal taxable estate.
4. Trust Architecture & Wealth Preservation Sandbox (Status Quo vs SLAT, IDGT, GRAT, ILIT).
5. Next-Generation Inheritance Waterfall & Per-Child Distribution.
"""

from __future__ import annotations
from datetime import datetime, timezone
import math
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import security


from estate_helpers import (
    DB_PATH,
    _EstateDbPathProxy,
    FEDERAL_ESTATE_EXEMPTION_2026_MFJ,
    FEDERAL_ESTATE_EXEMPTION_2026_SINGLE,
    FEDERAL_ESTATE_EXEMPTION_SUNSET_MFJ,
    FEDERAL_ESTATE_EXEMPTION_SUNSET_SINGLE,
    FEDERAL_TOP_ESTATE_RATE,
    MA_ESTATE_EXCLUSION,
    NY_CLIFF_MULTIPLIER,
    NY_ESTATE_EXCLUSION,
    NY_ESTATE_TAX_TABLE,
    OR_ESTATE_EXCLUSION,
    WA_ESTATE_EXCLUSION_MFJ,
    WA_ESTATE_EXCLUSION_SINGLE,
    WA_ESTATE_TAX_TABLE,
    calculate_comprehensive_estate_tax,
    calculate_ny_estate_tax,
    calculate_state_estate_tax,
    calculate_wa_estate_tax,
)


def simulate_trust_architectures(
    gross_estate: float,
    state: str = "WA",
    is_mfj: bool = True,
    apply_tcja_sunset: bool = False,
    company_equity_value: float = 0.0,
) -> Dict[str, Any]:
    """
    Compares Status Quo vs Advanced Wealth Preservation Trust Vehicles:
    1. Status Quo (Revocable Living Trust / Will)
    2. SLAT (Spousal Lifetime Access Trust)
    3. IDGT (Intentionally Defective Grantor Trust)
    4. GRAT (Grantor Retained Annuity Trust)
    5. ILIT (Irrevocable Life Insurance Trust)
    """
    base = calculate_comprehensive_estate_tax(
        gross_estate=gross_estate,
        state=state,
        is_mfj=is_mfj,
        apply_tcja_sunset=apply_tcja_sunset,
    )
    base_tax = base["total_estate_tax"]

    # 1. SLAT: Lock in statutory federal exemption ($15.0M single / $30.0M MFJ) into irrevocable trust
    # Trust assets grow 100% outside the estate.
    slat_funding = min(gross_estate * 0.70, FEDERAL_ESTATE_EXEMPTION_2026_MFJ if is_mfj else FEDERAL_ESTATE_EXEMPTION_2026_SINGLE)
    rem_slat_estate = max(0.0, gross_estate - slat_funding)
    slat_tax_res = calculate_comprehensive_estate_tax(
        gross_estate=rem_slat_estate,
        state=state,
        is_mfj=is_mfj,
        apply_tcja_sunset=apply_tcja_sunset,
    )
    slat_saved = round(max(0.0, base_tax - slat_tax_res["total_estate_tax"]), 2)

    # 2. IDGT: Freeze startup equity / private assets; growth compounds estate-tax-free
    # If family has company equity, gift/sale to IDGT removes 80% of future appreciation
    idgt_equity_removed = min(company_equity_value, gross_estate * 0.40)
    if idgt_equity_removed == 0:
        idgt_equity_removed = gross_estate * 0.25  # standard liquid growth stock transfer
    rem_idgt_estate = max(0.0, gross_estate - idgt_equity_removed)
    idgt_tax_res = calculate_comprehensive_estate_tax(
        gross_estate=rem_idgt_estate,
        state=state,
        is_mfj=is_mfj,
        apply_tcja_sunset=apply_tcja_sunset,
    )
    idgt_saved = round(max(0.0, base_tax - idgt_tax_res["total_estate_tax"]), 2)

    # 3. GRAT: Rolling zeroed-out GRAT transferring appreciation above IRS § 7520 rate (e.g. 5.2%)
    grat_growth_transferred = round(gross_estate * 0.15, 2)
    rem_grat_estate = max(0.0, gross_estate - grat_growth_transferred)
    grat_tax_res = calculate_comprehensive_estate_tax(
        gross_estate=rem_grat_estate,
        state=state,
        is_mfj=is_mfj,
        apply_tcja_sunset=apply_tcja_sunset,
    )
    grat_saved = round(max(0.0, base_tax - grat_tax_res["total_estate_tax"]), 2)

    # 4. ILIT: Second-to-die life insurance policy providing 100% tax liquidity
    ilit_coverage = base_tax
    ilit_net_heirs = gross_estate  # insurance covers 100% of tax liability

    vehicles = [
        {
            "id": "status_quo",
            "name": "Status Quo (Revocable Living Trust / Will)",
            "badge": "Unoptimized Baseline",
            "icon": "📜",
            "description": "Standard probate avoidance trust. All assets remain in the gross taxable estate, exposed to federal 40% and state estate taxes.",
            "estate_tax_due": base_tax,
            "tax_savings": 0.0,
            "net_to_heirs": base["net_estate_to_heirs"],
            "effective_rate": base["effective_tax_rate"],
            "key_mechanic": "Zero lifetime wealth shielding. 100% exposed to TCJA sunset.",
        },
        {
            "id": "slat",
            "name": "SLAT (Spousal Lifetime Access Trust)",
            "badge": "High-Impact Exemption Lock",
            "icon": "🛡️",
            "description": f"Irrevocable completed gift of ${slat_funding/1e6:.1f}M locking in the high statutory exemption ($15.0M single / $30.0M MFJ). Assets grow outside estate while spouse retains discretionary HEMS access.",
            "estate_tax_due": slat_tax_res["total_estate_tax"],
            "tax_savings": slat_saved,
            "net_to_heirs": round(gross_estate - slat_tax_res["total_estate_tax"], 2),
            "effective_rate": round(slat_tax_res["total_estate_tax"] / gross_estate * 100, 2) if gross_estate > 0 else 0.0,
            "key_mechanic": f"Shields ${slat_funding/1e6:.1f}M from 40% federal tax and {state} estate taxes permanently.",
        },
        {
            "id": "idgt",
            "name": "IDGT (Intentionally Defective Grantor Trust)",
            "badge": "Equity Upside Freeze",
            "icon": "📈",
            "description": f"Sale of ${idgt_equity_removed/1e6:.1f}M in high-growth company equity in exchange for a low-interest note. Future upside compounds for children completely estate-tax-free.",
            "estate_tax_due": idgt_tax_res["total_estate_tax"],
            "tax_savings": idgt_saved,
            "net_to_heirs": round(gross_estate - idgt_tax_res["total_estate_tax"], 2),
            "effective_rate": round(idgt_tax_res["total_estate_tax"] / gross_estate * 100, 2) if gross_estate > 0 else 0.0,
            "key_mechanic": "Grantor pays trust income taxes, providing annual tax-free compounding gifts to heirs.",
        },
        {
            "id": "grat",
            "name": "GRAT (Grantor Retained Annuity Trust - IRC § 2702)",
            "badge": "Zero-Gift-Tax Upside Transfer",
            "icon": "⏳",
            "description": f"Transfers ${grat_growth_transferred/1e6:.1f}M of equity appreciation above the IRS § 7520 hurdle rate to heirs with $0 gift tax liability.",
            "estate_tax_due": grat_tax_res["total_estate_tax"],
            "tax_savings": grat_saved,
            "net_to_heirs": round(gross_estate - grat_tax_res["total_estate_tax"], 2),
            "effective_rate": round(grat_tax_res["total_estate_tax"] / gross_estate * 100, 2) if gross_estate > 0 else 0.0,
            "key_mechanic": "Heads you win, tails you tie. If assets fail to beat § 7520, principal returns to grantor.",
        },
        {
            "id": "ilit",
            "name": "ILIT (Irrevocable Life Insurance Trust)",
            "badge": "Immediate Tax Liquidity",
            "icon": "🏦",
            "description": f"Holds a permanent second-to-die life insurance policy with ${ilit_coverage/1e6:.1f}M tax-free death benefit to pay estate taxes without forced asset sales.",
            "estate_tax_due": 0.0,
            "tax_savings": base_tax,
            "net_to_heirs": ilit_net_heirs,
            "effective_rate": 0.0,
            "key_mechanic": "Liquid death benefit eliminates forced fire-sales of illiquid family real estate or private equity.",
        },
    ]

    return {
        "status_quo": base,
        "vehicles": vehicles,
        "max_potential_tax_savings": max(slat_saved, idgt_saved, base_tax),
    }


def get_family_estate_profile(family_id: int = 0) -> Dict[str, Any]:
    """
    Gathers authentic family estate profile:
    - Current balance sheet and projected gross estate at ages 80, 85, 90, 95
    - Children from users table
    - State and tax filing status
    - Trust simulation comparisons
    """
    estate_cache_params = {"db": str(DB_PATH)}
    if family_id and family_id > 0:
        try:
            import forecast_cache
            cached_estate = forecast_cache.get_cached_estate(family_id, estate_cache_params)
            if cached_estate is not None:
                return cached_estate
        except Exception:
            pass

    state = "WA"
    filing_status = "MFJ"
    is_mfj = True
    charitable_pct = 0.05
    apply_tcja_sunset = False
    children_list = []
    total_net_worth = 0.0
    company_equity_val = 0.0

    if DB_PATH.exists() and family_id:
        try:
            from db.auth_repo import (
                get_family_children_for_estate,
                get_household_profile_for_estate,
            )
            hp = get_household_profile_for_estate(family_id=family_id, db_path=DB_PATH)
            if hp:
                state = hp["state"]
                filing_status = hp["filing_status"]
                is_mfj = (filing_status == "MFJ")
                if hp.get("assumptions_json"):
                    try:
                        import json
                        assump = json.loads(hp["assumptions_json"])
                        if "estate_planning" in assump:
                            ep = assump["estate_planning"]
                            apply_tcja_sunset = bool(ep.get("apply_tcja_sunset", False))
                            charitable_pct = float(ep.get("charitable_pct", 0.05))
                    except Exception:
                        pass

            children_list = get_family_children_for_estate(family_id=family_id, db_path=DB_PATH)
        except Exception:
            pass

    active_sched = None
    if family_id:
        try:
            import monarch_service
            snap = monarch_service.get_financial_snapshot(family_id=family_id)
            if snap:
                nw = snap.get("true_net_worth")
                if nw is None:
                    nw = snap.get("monarch_reported_net_worth")
                if nw is None:
                    nw = snap.get("net_worth")
                if nw is not None and float(nw) > 0:
                    total_net_worth = float(nw)
        except Exception:
            pass

    def _load_family_simulation(fid: int):
        try:
            import forecast_cache
            from routes.helpers import get_current_universe
            u = get_current_universe()
            ck = forecast_cache.make_cache_key(fid, u, {})
            cached = forecast_cache.get_simulation(ck)
            if cached:
                return cached
            import forecast_engine
            res = forecast_engine.simulate_multi_scenarios(family_id=fid)
            forecast_cache.set_simulation(ck, res)
            return res
        except Exception:
            import forecast_engine
            return forecast_engine.simulate_multi_scenarios(family_id=fid)

    # If net worth is 0 or generic, pull from forecast engine baseline
    if total_net_worth <= 0 and family_id:
        try:
            sim = _load_family_simulation(family_id)
            active_sched = sim.get("active_schedule", [])
            if active_sched:
                total_net_worth = float(active_sched[0].get("total_net_worth", 0.0))
                company_equity_val = float(active_sched[0].get("company_equity", 0.0))
        except Exception:
            pass

    if not total_net_worth or total_net_worth <= 0:
        total_net_worth = 0.0

    # Multi-Decade Estate Trajectory (Projections at Ages 80, 85, 90, 95)
    # Using forecast engine schedule or standard conservative compound growth
    projections = []
    milestone_ages = [80, 85, 90, 95]

    try:
        if active_sched is None and family_id:
            sim = _load_family_simulation(family_id)
            active_sched = sim.get("active_schedule", [])
        sched = active_sched or []


        base_age = int(sched[0].get("age_primary", sched[0].get("age", 50))) if sched else 50
        for age in milestone_ages:
            pt = next((s for s in sched if s.get("age_primary", s.get("age")) == age), None)
            yrs_out = max(1, age - base_age)
            val = float(pt.get("total_net_worth")) if pt else total_net_worth * (1.03 ** yrs_out)
            yr = int(pt.get("year")) if pt else (datetime.now(timezone.utc).year + yrs_out)

            tax_calc = calculate_comprehensive_estate_tax(
                gross_estate=val,
                state=state,
                is_mfj=is_mfj,
                apply_tcja_sunset=apply_tcja_sunset,
            )
            tax_due = tax_calc["total_estate_tax"]
            rem_after_tax = max(0.0, val - tax_due)
            charity_amt = round(rem_after_tax * charitable_pct, 2)
            heirs_amt = round(rem_after_tax - charity_amt, 2)
            num_kids = len(children_list)
            per_child = round(heirs_amt / num_kids, 2) if num_kids > 0 else 0.0

            projections.append({
                "milestone_age": age,
                "projected_year": yr,
                "projected_gross_estate": round(val, 2),
                "state_tax": tax_calc["state_estate_tax"],
                "federal_tax": tax_calc["federal_estate_tax"],
                "total_estate_tax": tax_due,
                "effective_rate": tax_calc["effective_tax_rate"],
                "charitable_legacy": charity_amt,
                "net_wealth_transferred": heirs_amt,
                "per_child_inheritance": per_child,
            })
    except Exception:
        for age in milestone_ages:
            yrs_out = max(1, age - 50)
            val = total_net_worth * (1.03 ** yrs_out)
            yr = datetime.now(timezone.utc).year + yrs_out
            tax_calc = calculate_comprehensive_estate_tax(gross_estate=val, state=state, is_mfj=is_mfj)
            num_kids = len(children_list)
            per_child = round(tax_calc["net_estate_to_heirs"] / num_kids, 2) if num_kids > 0 else 0.0
            projections.append({
                "milestone_age": age,
                "projected_year": yr,
                "projected_gross_estate": round(val, 2),
                "total_estate_tax": tax_calc["total_estate_tax"],
                "net_wealth_transferred": tax_calc["net_estate_to_heirs"],
                "per_child_inheritance": per_child,
            })

    # Trust Architectures
    trust_sandbox = simulate_trust_architectures(
        gross_estate=total_net_worth,
        state=state,
        is_mfj=is_mfj,
        apply_tcja_sunset=apply_tcja_sunset,
        company_equity_value=company_equity_val,
    )

    # State Tax Arbitrage Comparison (compare current state vs CA, NY, MA, OR, FL/TX)
    state_comparisons = [
        calculate_state_estate_tax(gross_estate=total_net_worth, state="WA", is_mfj=is_mfj),
        calculate_state_estate_tax(gross_estate=total_net_worth, state="CA", is_mfj=is_mfj),
        calculate_state_estate_tax(gross_estate=total_net_worth, state="NY", is_mfj=is_mfj),
        calculate_state_estate_tax(gross_estate=total_net_worth, state="MA", is_mfj=is_mfj),
        calculate_state_estate_tax(gross_estate=total_net_worth, state="OR", is_mfj=is_mfj),
        calculate_state_estate_tax(gross_estate=total_net_worth, state="TX", is_mfj=is_mfj),
    ]

    result = {
        "success": True,
        "family_id": family_id,
        "state": state,
        "filing_status": filing_status,
        "is_mfj": is_mfj,
        "apply_tcja_sunset": apply_tcja_sunset,
        "charitable_pct": charitable_pct,
        "children": children_list,
        "children_count": len(children_list),
        "current_net_worth": round(total_net_worth, 2),
        "current_estate_tax": calculate_comprehensive_estate_tax(
            gross_estate=total_net_worth,
            state=state,
            is_mfj=is_mfj,
            apply_tcja_sunset=apply_tcja_sunset,
        ),
        "projections": projections,
        "trust_sandbox": trust_sandbox,
        "state_comparisons": state_comparisons,
    }
    if family_id and family_id > 0:
        try:
            import forecast_cache
            forecast_cache.set_cached_estate(family_id, result, estate_cache_params, persist_l2=True)
        except Exception:
            pass
    return result


generate_estate_report = get_family_estate_profile
