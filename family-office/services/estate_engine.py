"""
HVL Family Office: Estate & Generational Wealth Engine
Core Capabilities:
1. Dynamic Federal Gift & Estate Tax calculation (current permanent OBBBA exemption vs a legislative-rollback stress test).
2. State estate tax per jurisdiction (schedules in `services/state_estate_tax.py`).
3. IRC § 2058 state death tax deduction modeling against federal taxable estate.
4. Trust Architecture & Wealth Preservation Sandbox (Status Quo vs SLAT, IDGT, GRAT, ILIT).
5. Next-Generation Inheritance Waterfall & Per-Child Distribution.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, Optional

import security
from services.state_estate_tax import calculate_state_estate_tax

logger = logging.getLogger(__name__)


class _EstateDbPathProxy(os.PathLike):
    """Dynamically resolves to the database for the active request universe."""
    def _path(self) -> Path:
        from services.request_context import get_current_db_path
        return get_current_db_path()

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def exists(self) -> bool:
        return self._path().exists()


DB_PATH = _EstateDbPathProxy()


# =============================================================================
# STATUTORY TAX BRACKETS & EXEMPTIONS
# =============================================================================

# 2026 Federal Unified Gift & Estate Tax Parameters (OBBBA 2026 statutory exemption)
FEDERAL_ESTATE_EXEMPTION_2026_SINGLE = 15_000_000.0
FEDERAL_ESTATE_EXEMPTION_2026_MFJ = 30_000_000.0  # with DSUE portability (IRC § 2010(c)(5))

# Legislative Rollback / Stress-Test Scenario (~$7.0M single / ~$14.0M MFJ inflation-adjusted)
# Note: OBBBA made the $15M/$30M exemption permanent; this toggle (apply_tcja_sunset) now models a
# "Legislative Rollback / Stress-Test Scenario (~$7M/$14M)" rather than an automatic TCJA sunset.
FEDERAL_ESTATE_EXEMPTION_SUNSET_SINGLE = 7_000_000.0
FEDERAL_ESTATE_EXEMPTION_SUNSET_MFJ = 14_000_000.0

# Illustrative appreciation above the note, as a share of the value sold to an IDGT, over the planning horizon.
IDGT_ASSUMED_APPRECIATION_ABOVE_NOTE = 0.50

# The statutory exemptions above are today's-dollar figures with no year indexing in this engine, so every
# gross estate is compared against them in today's dollars (a future-year estate is deflated to today's
# dollars first). Results carry this label so no consumer has to guess the unit.
ESTATE_DOLLAR_BASIS = "todays_dollars"

FEDERAL_TOP_ESTATE_RATE = 0.40  # 40% statutory federal estate tax


def calculate_comprehensive_estate_tax(
    gross_estate: float,
    state: str = "",
    is_mfj: bool = True,
    apply_tcja_sunset: bool = False,
    has_ab_trust: bool = True,
) -> Dict[str, Any]:
    """
    Computes combined Federal and State estate taxes, applying IRC § 2058 deduction.
    """
    if gross_estate <= 0:
        return {
            "gross_estate": 0.0,
            "state_estate_tax": 0.0,
            "federal_estate_tax": 0.0,
            "total_estate_tax": 0.0,
            "effective_tax_rate": 0.0,
            "net_estate_to_heirs": 0.0,
        }

    # 1. State Estate Tax
    state_res = calculate_state_estate_tax(
        gross_estate=gross_estate,
        state=state,
        is_mfj=is_mfj,
        has_ab_trust=has_ab_trust,
    )
    state_tax = state_res["tax_liability"]

    # 2. Federal Unified Exemption
    if apply_tcja_sunset:
        fed_exemption = FEDERAL_ESTATE_EXEMPTION_SUNSET_MFJ if is_mfj else FEDERAL_ESTATE_EXEMPTION_SUNSET_SINGLE
    else:
        fed_exemption = FEDERAL_ESTATE_EXEMPTION_2026_MFJ if is_mfj else FEDERAL_ESTATE_EXEMPTION_2026_SINGLE

    # 3. IRC § 2058 Deduction: State death taxes paid reduce federal gross estate
    adjusted_gross_for_fed = max(0.0, gross_estate - state_tax)
    fed_taxable = max(0.0, adjusted_gross_for_fed - fed_exemption)
    fed_tax = round(fed_taxable * FEDERAL_TOP_ESTATE_RATE, 2)

    total_tax = round(state_tax + fed_tax, 2)
    effective_rate = round((total_tax / gross_estate * 100), 2) if gross_estate > 0 else 0.0
    net_heirs = round(max(0.0, gross_estate - total_tax), 2)

    return {
        "gross_estate": round(gross_estate, 2),
        "state": state.upper(),
        "is_mfj": is_mfj,
        "apply_tcja_sunset": apply_tcja_sunset,
        "federal_exemption": fed_exemption,
        "federal_taxable_estate": fed_taxable,
        "irc_2058_state_tax_deduction": state_tax,
        "federal_estate_tax": fed_tax,
        "state_tax_details": state_res,
        "state_estate_tax": state_tax,
        "total_estate_tax": total_tax,
        "effective_tax_rate": effective_rate,
        "net_estate_to_heirs": net_heirs,
    }


def simulate_trust_architectures(
    gross_estate: float,
    state: str = "",
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

    # 1. SLAT: funded with the donor spouse's own exemption only (one spouse's share, never the joint
    # exemption), so funding is capped at the single-filer exemption even for a married couple.
    # Trust assets grow 100% outside the estate.
    slat_exemption = FEDERAL_ESTATE_EXEMPTION_SUNSET_SINGLE if apply_tcja_sunset else FEDERAL_ESTATE_EXEMPTION_2026_SINGLE
    slat_funding = min(gross_estate * 0.70, slat_exemption)
    rem_slat_estate = max(0.0, gross_estate - slat_funding)
    slat_tax_res = calculate_comprehensive_estate_tax(
        gross_estate=rem_slat_estate,
        state=state,
        is_mfj=is_mfj,
        apply_tcja_sunset=apply_tcja_sunset,
    )
    slat_saved = round(max(0.0, base_tax - slat_tax_res["total_estate_tax"]), 2)

    # 2. IDGT: sale of equity / private assets to the trust for a note. The note (worth what was sold)
    # stays in the grantor's estate; only appreciation above the note leaves it.
    idgt_equity_sold = min(company_equity_value, gross_estate * 0.40)
    if idgt_equity_sold == 0:
        idgt_equity_sold = gross_estate * 0.25  # standard liquid growth stock transfer
    idgt_equity_removed = round(idgt_equity_sold * IDGT_ASSUMED_APPRECIATION_ABOVE_NOTE, 2)
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

    # 4. ILIT: second-to-die policy owned outside the estate. It does not reduce the estate tax due; it
    # supplies the cash to pay it, so heirs receive the estate less tax plus the death benefit (premiums ignored).
    ilit_coverage = base_tax
    ilit_net_heirs = round(base["net_estate_to_heirs"] + ilit_coverage, 2)

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
            "key_mechanic": "Zero lifetime wealth shielding. 100% exposed to federal and state estate tax.",
        },
        {
            "id": "slat",
            "name": "SLAT (Spousal Lifetime Access Trust)",
            "badge": "High-Impact Exemption Use",
            "icon": "🛡️",
            "description": f"Irrevocable completed gift of ${slat_funding/1e6:.1f}M using one spouse's (the donor's) statutory exemption (the exemption is permanent under current law; a SLAT can use only the donor spouse's share, never the joint exemption). Assets grow outside estate while spouse retains discretionary HEMS access.",
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
            "description": f"Sale of ${idgt_equity_sold/1e6:.1f}M in high-growth company equity to the trust in exchange for a low-interest note. The note stays in the estate; only appreciation above the note passes to children outside the estate (illustrative assumption: the equity grows {IDGT_ASSUMED_APPRECIATION_ABOVE_NOTE:.0%} beyond the note, ${idgt_equity_removed/1e6:.1f}M).",
            "estate_tax_due": idgt_tax_res["total_estate_tax"],
            "tax_savings": idgt_saved,
            "net_to_heirs": round(gross_estate - idgt_tax_res["total_estate_tax"], 2),
            "effective_rate": round(idgt_tax_res["total_estate_tax"] / gross_estate * 100, 2) if gross_estate > 0 else 0.0,
            "key_mechanic": "Note value stays in the estate; growth above the note compounds outside it, and the grantor paying the trust's income tax is an extra tax-free transfer.",
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
            "description": f"Holds a permanent second-to-die life insurance policy with a ${ilit_coverage/1e6:.1f}M income-tax-free death benefit, outside the estate, that provides the cash to pay the estate tax without forced asset sales. It does not reduce the tax itself.",
            "estate_tax_due": base_tax,
            "tax_savings": 0.0,
            "liquidity_provided": ilit_coverage,
            "net_to_heirs": ilit_net_heirs,
            "effective_rate": base["effective_tax_rate"],
            "key_mechanic": f"Estate tax is unchanged; the ${ilit_coverage/1e6:.1f}M death benefit supplies the liquidity to pay it, so illiquid real estate or private equity need not be sold (premiums not modeled).",
        },
    ]

    return {
        "status_quo": base,
        "vehicles": vehicles,
        "max_potential_tax_savings": max(slat_saved, idgt_saved, grat_saved),
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
        from forecast import cache as forecast_cache
        cached_estate = forecast_cache.get_cached_estate(family_id, estate_cache_params)
        if cached_estate is not None:
            return cached_estate

    state = ""
    filing_status = "MFJ"
    is_mfj = True
    charitable_pct = 0.05
    apply_tcja_sunset = False
    children_list = []
    total_net_worth = 0.0
    company_equity_val = 0.0

    if DB_PATH.exists() and family_id:
        from db.auth_repo import (
            get_family_children_for_estate,
            get_household_profile_for_estate,
        )
        hp = get_household_profile_for_estate(family_id=family_id, db_path=DB_PATH)
        if hp:
            state = hp["state"]
            filing_status = hp["filing_status"]
            is_mfj = (filing_status == "MFJ")
            from db.estate import ESTATE_PLANNING_KEY
            from db.household_assumptions import get_section

            ep = get_section(family_id=family_id, section_key=ESTATE_PLANNING_KEY, db_path=DB_PATH)
            if isinstance(ep, dict):
                apply_tcja_sunset = bool(ep.get("apply_tcja_sunset", False))
                charitable_pct = float(ep.get("charitable_pct", 0.05))

        children_list = get_family_children_for_estate(family_id=family_id, db_path=DB_PATH)

    active_sched = None
    snap_found = False
    if family_id:
        import account_sync
        snap = account_sync.get_financial_snapshot(family_id=family_id)
        if snap:
            nw = snap.get("true_net_worth")
            if nw is None:
                nw = snap.get("monarch_reported_net_worth")
            if nw is None:
                nw = snap.get("net_worth")
            if nw is not None:
                total_net_worth = float(nw)
                snap_found = True

    def _load_family_simulation(fid: int):
        from forecast import cache as forecast_cache
        from services.request_context import get_current_universe
        u = get_current_universe()
        ck = forecast_cache.make_cache_key(fid, u, {})
        cached = forecast_cache.get_simulation(ck)
        if cached:
            return cached
        from forecast import engine as forecast_engine
        res = forecast_engine.simulate_multi_scenarios(family_id=fid)
        forecast_cache.set_simulation(ck, res)
        return res

    # If net worth is not found in snapshot and total_net_worth <= 0, pull from forecast engine baseline
    if not snap_found and total_net_worth <= 0 and family_id:
        sim = _load_family_simulation(family_id)
        active_sched = sim.get("active_schedule", [])
        if active_sched:
            first = active_sched[0]
            to_todays = float(first["to_todays_dollars"])
            total_net_worth = float(first.get("total_net_worth", 0.0)) * to_todays
            company_equity_val = float(first.get("company_equity", 0.0)) * to_todays

    if not total_net_worth or total_net_worth <= 0:
        total_net_worth = 0.0

    # Multi-Decade Estate Trajectory (Projections at Ages 80, 85, 90, 95)
    # Using forecast engine schedule or standard conservative compound growth
    projections = []
    milestone_ages = [80, 85, 90, 95]

    if active_sched is None and family_id:
        sim = _load_family_simulation(family_id)
        active_sched = sim.get("active_schedule", [])
    sched = active_sched or []

    base_age = int(sched[0].get("age_primary", sched[0].get("age", 50))) if sched else 50
    for age in milestone_ages:
        pt = next((s for s in sched if s.get("age_primary", s.get("age")) == age), None)
        yrs_out = max(1, age - base_age)
        # Schedule rows are in the saved view's dollars (nominal or today's, per the UI toggle);
        # `to_todays_dollars` converts a row to today's dollars so the result never depends on the view.
        if pt:
            val = float(pt.get("total_net_worth")) * float(pt["to_todays_dollars"])
        else:
            val = total_net_worth * (1.03 ** yrs_out)
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
            "dollar_basis": ESTATE_DOLLAR_BASIS,
            "projected_gross_estate": round(val, 2),
            "state_tax": tax_calc["state_estate_tax"],
            "federal_tax": tax_calc["federal_estate_tax"],
            "total_estate_tax": tax_due,
            "effective_rate": tax_calc["effective_tax_rate"],
            "charitable_legacy": charity_amt,
            "net_wealth_transferred": heirs_amt,
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
        "dollar_basis": ESTATE_DOLLAR_BASIS,
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
        from forecast import cache as forecast_cache
        forecast_cache.set_cached_estate(family_id, result, estate_cache_params, persist_l2=True)
    return result


generate_estate_report = get_family_estate_profile
