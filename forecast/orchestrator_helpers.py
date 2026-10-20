"""
forecast/orchestrator_helpers.py: Helper routines for multi-scenario simulation orchestration.
Decomposes timeline milestone synthesis, bisection search for earliest retirement,
multi-curve timeline collation, and Monte Carlo solvency decoration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from forecast.waterfall import run_scenario_simulation
from forecast.monte_carlo import run_monte_carlo_simulation


def resolve_profile_defaults(
    family_id: int,
    db_file: Path,
    scenarios_list: List[Dict[str, Any]],
) -> Tuple[float, float, int, float, int, int]:
    """Resolves baseline household spending, savings, retirement age, and inflation from profile & scenario state."""
    prof_spending = 0.0
    prof_savings = 0.0
    prof_ret_age = 65
    prof_inflation = 0.025

    if db_file.exists() and family_id:
        try:
            from db.household import get_household_profile
            prof = get_household_profile(family_id=family_id, db_path=db_file)
            if prof:
                if prof.get("annual_spending"):
                    prof_spending = float(prof["annual_spending"])
                if prof.get("annual_savings"):
                    prof_savings = float(prof["annual_savings"])
                if prof.get("retirement_age"):
                    prof_ret_age = int(prof["retirement_age"])
                if prof.get("inflation_rate"):
                    prof_inflation = float(prof["inflation_rate"])
        except Exception:
            pass

    baseline_raw = next((s for s in scenarios_list if s.get("id") == "scen_baseline"), None)
    if baseline_raw:
        if baseline_raw.get("annual_living_spend") is not None:
            prof_spending = float(baseline_raw["annual_living_spend"])
        if baseline_raw.get("annual_savings") is not None:
            prof_savings = float(baseline_raw["annual_savings"])
        if baseline_raw.get("primary_retirement_age") is not None:
            prof_ret_age = int(baseline_raw["primary_retirement_age"])
        if baseline_raw.get("inflation_rate") is not None:
            prof_inflation = float(baseline_raw["inflation_rate"])

    prof_primary_ss = 67
    prof_spouse_ss = 67
    if baseline_raw:
        if baseline_raw.get("primary_ss_claim_age") is not None:
            prof_primary_ss = int(baseline_raw["primary_ss_claim_age"])
        elif baseline_raw.get("ss_claim_age") is not None:
            prof_primary_ss = int(baseline_raw["ss_claim_age"])
        if baseline_raw.get("spouse_ss_claim_age") is not None:
            prof_spouse_ss = int(baseline_raw["spouse_ss_claim_age"])
        elif baseline_raw.get("ss_claim_age") is not None:
            prof_spouse_ss = int(baseline_raw["ss_claim_age"])

    return prof_spending, prof_savings, prof_ret_age, prof_inflation, prof_primary_ss, prof_spouse_ss


def resolve_asset_allocation_weights(
    snapshot: Dict[str, Any],
) -> Tuple[float, float, float, float, float, float, float]:
    """Calculates granular liquid and retirement compounding weights from Monarch detailed asset allocation."""
    alloc_totals = snapshot.get("detailed_asset_allocation", {}).get("totals", {})
    us_val = float(alloc_totals.get("us_equity", 0.0) or 0.0)
    intl_val = float(alloc_totals.get("intl_equity", 0.0) or 0.0)
    bonds_val = float(alloc_totals.get("bonds", 0.0) or 0.0)
    cash_val = float(alloc_totals.get("cash_liquid", 0.0) or 0.0)
    liquid_pool = us_val + intl_val + bonds_val + cash_val

    if liquid_pool > 0:
        w_us = us_val / liquid_pool
        w_intl = intl_val / liquid_pool
        w_bonds = bonds_val / liquid_pool
        w_cash = cash_val / liquid_pool
    else:
        w_us, w_intl, w_bonds, w_cash = 0.60, 0.20, 0.15, 0.05

    retire_pool = us_val + intl_val + bonds_val
    if retire_pool > 0:
        w_ret_us = us_val / retire_pool
        w_ret_intl = intl_val / retire_pool
        w_ret_bonds = bonds_val / retire_pool
    else:
        w_ret_us, w_ret_intl, w_ret_bonds = 0.70, 0.20, 0.10

    return w_us, w_intl, w_bonds, w_cash, w_ret_us, w_ret_intl, w_ret_bonds


def build_orchestrator_milestones(
    primary_birth_year: int,
    spouse_birth_year: int,
    primary_retirement_age: int,
    spouse_retirement_age: int,
    primary_name: str,
    spouse_name: str,
    current_primary_age: int,
    current_spouse_age: int,
    children_edu: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Synthesizes dynamic life, retirement, Medicare, and college entry timeline milestones."""
    primary_ret_yr = primary_birth_year + primary_retirement_age
    spouse_ret_yr = spouse_birth_year + spouse_retirement_age

    milestones: List[Dict[str, Any]] = [
        {"year": 2026, "label": f"Today ({primary_name} {current_primary_age} / {spouse_name} {current_spouse_age})", "icon": "", "category": "life"},
    ]
    if primary_ret_yr == spouse_ret_yr:
        milestones.append({
            "year": primary_ret_yr,
            "label": f"Combined Retirement (Age {primary_retirement_age})",
            "icon": "",
            "category": "retirement"
        })
    else:
        milestones.append({
            "year": primary_ret_yr,
            "label": f"{primary_name} Retirement (Age {primary_retirement_age})",
            "icon": "",
            "category": "retirement"
        })
        milestones.append({
            "year": spouse_ret_yr,
            "label": f"{spouse_name} Retirement (Age {spouse_retirement_age})",
            "icon": "",
            "category": "retirement"
        })

    for c in children_edu:
        c_name = c["first_name"]
        college_year = c["college_start"]
        milestones.append({
            "year": college_year,
            "label": f"{c_name} Enters College",
            "icon": "",
            "category": "education"
        })
    milestones.append({"year": primary_birth_year + 65, "label": "Medicare Eligibility (Age 65)", "icon": "", "category": "health"})
    milestones.append({"year": primary_birth_year + 67, "label": "Social Security FRA (Age 67)", "icon": "", "category": "ss"})
    milestones.sort(key=lambda m: m["year"])
    return milestones


def find_earliest_sustainable_retirement(
    scen_events: List[Dict[str, Any]],
    liquid_start: float,
    retirement_start: float,
    real_estate_start: float,
    mortgage_start: float,
    other_start: float,
    scen_equity_annual_growth: float,
    current_primary_age: int,
    current_spouse_age: int,
    scen_spending: float,
    scen_savings: float,
    inflation_rate: float,
    primary_birth_year: int,
    spouse_birth_year: int,
    view_mode: str,
    family_id: int,
    scen_primary_ss_claim: int,
    scen_spouse_ss_claim: int,
    mortgage_annual_service: float,
    scen_blended_liquid: float,
    scen_blended_retire: float,
    growth_private: float,
    growth_re: float,
    scen_company_growth_rates: Dict[int, float],
    household_context: Any,
    scen_spouse_ret: int,
) -> Tuple[Optional[int], Optional[int], Optional[int], bool]:
    """
    Executes bisection (binary search) across career years to determine the earliest
    sustainable retirement year where portfolio never depletes through age 100.
    Returns (earliest_joint_yr, earliest_p_age, earliest_s_age, can_retire_today).
    """
    test_sim = run_scenario_simulation(
        events=scen_events,
        liquid_start=liquid_start,
        retirement_start=retirement_start,
        real_estate_start=real_estate_start,
        mortgage_start=mortgage_start,
        other_start=other_start,
        equity_annual_growth=scen_equity_annual_growth,
        primary_retirement_age=current_primary_age,
        spouse_retirement_age=current_spouse_age,
        annual_spending=scen_spending,
        annual_savings=scen_savings,
        inflation_rate=inflation_rate,
        primary_birth_year=primary_birth_year,
        spouse_birth_year=spouse_birth_year,
        view_mode=view_mode,
        family_id=family_id,
        ss_claim_age=scen_primary_ss_claim,
        primary_ss_claim_age=scen_primary_ss_claim,
        spouse_ss_claim_age=scen_spouse_ss_claim,
        mortgage_annual_service=mortgage_annual_service,
        blended_liquid_growth=scen_blended_liquid,
        blended_retire_growth=scen_blended_retire,
        growth_private=growth_private,
        growth_real_estate=growth_re,
        company_growth_rates=scen_company_growth_rates,
        context=household_context,
    )
    if not test_sim["depleted"]:
        return 2026, current_primary_age, current_spouse_age, True

    spouse_already_retired = (scen_spouse_ret <= current_spouse_age)
    low_yr = 2027
    high_yr = 2054
    best_yr = None
    best_tp = None
    best_ts = None
    while low_yr <= high_yr:
        mid_yr = (low_yr + high_yr) // 2
        tp = mid_yr - primary_birth_year
        ts = scen_spouse_ret if spouse_already_retired else (mid_yr - spouse_birth_year)
        tsim = run_scenario_simulation(
            events=scen_events,
            liquid_start=liquid_start,
            retirement_start=retirement_start,
            real_estate_start=real_estate_start,
            mortgage_start=mortgage_start,
            other_start=other_start,
            equity_annual_growth=scen_equity_annual_growth,
            primary_retirement_age=tp,
            spouse_retirement_age=ts,
            annual_spending=scen_spending,
            annual_savings=scen_savings,
            inflation_rate=inflation_rate,
            primary_birth_year=primary_birth_year,
            spouse_birth_year=spouse_birth_year,
            view_mode=view_mode,
            family_id=family_id,
            ss_claim_age=scen_primary_ss_claim,
            primary_ss_claim_age=scen_primary_ss_claim,
            spouse_ss_claim_age=scen_spouse_ss_claim,
            mortgage_annual_service=mortgage_annual_service,
            blended_liquid_growth=scen_blended_liquid,
            blended_retire_growth=scen_blended_retire,
            growth_private=growth_private,
            growth_real_estate=growth_re,
            company_growth_rates=scen_company_growth_rates,
            context=household_context,
        )
        if not tsim["depleted"]:
            best_yr = mid_yr
            best_tp = tp
            best_ts = ts
            high_yr = mid_yr - 1
        else:
            low_yr = mid_yr + 1

    can_retire_today = (best_yr is not None and best_yr <= 2026 and not test_sim["depleted"])
    return best_yr, best_tp, best_ts, can_retire_today


def build_comparison_curves(
    scenarios_results: Dict[str, Any],
    scenarios_list: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Builds comparative multi-scenario net worth trajectory curves aligned by year."""
    comparison_curves = []
    baseline_sched = scenarios_results.get("scen_baseline", {}).get("schedule", [])
    years_list = [s["year"] for s in baseline_sched]

    for idx, yr in enumerate(years_list):
        row: Dict[str, Any] = {
            "year": yr,
            "age": baseline_sched[idx].get("age_primary", baseline_sched[idx].get("age", 45)),
            "age_primary": baseline_sched[idx].get("age_primary", baseline_sched[idx].get("age", 45)),
            "age_spouse": baseline_sched[idx].get("age_spouse", 45),
        }
        for scen in scenarios_list:
            scen_id = scen["id"]
            scen_sched = scenarios_results.get(scen_id, {}).get("schedule", [])
            if idx < len(scen_sched):
                row[scen_id] = scen_sched[idx]["total_net_worth"]
        comparison_curves.append(row)
    return comparison_curves


def attach_monte_carlo_solvency(
    res: Dict[str, Any],
    family_id: int,
    eval_scen_id: str,
    active_scen_id: str,
    annual_living_spend: Optional[float],
) -> None:
    """Runs high-trial Monte Carlo simulation and injects solvency stats and longevity curves into res."""
    try:
        active_mc = run_monte_carlo_simulation(
            family_id=family_id,
            scenario_id=eval_scen_id,
            trials=1000,
            custom_spending=annual_living_spend,
            precomputed_sim=res,
        )
        if active_mc and active_mc.get("success"):
            res["active_monte_carlo"] = active_mc
            if active_mc.get("longevity_breakdown"):
                if eval_scen_id == active_scen_id:
                    res["active_longevity_breakdown"] = active_mc["longevity_breakdown"]
                if "scenario_longevity_breakdowns" in res:
                    res["scenario_longevity_breakdowns"][eval_scen_id] = active_mc["longevity_breakdown"]
            solv_100 = active_mc.get("success_rate_age_100")
            for sc in res.get("scorecard", []):
                if sc.get("id") == eval_scen_id:
                    sc["monte_carlo_solvency"] = solv_100
                    sc["solvency_rate_85"] = active_mc.get("success_rate_age_85")
                    sc["solvency_rate_90"] = active_mc.get("success_rate_age_90")
                    sc["is_depleted"] = sc.get("is_depleted", False) or (solv_100 is not None and solv_100 < 50.0)
    except Exception:
        pass
