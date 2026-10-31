"""
forecast/orchestrator_params.py: Scenario parameter resolution and retirement readiness builder.
Extracted from forecast/orchestrator.py to maintain modularity and single responsibility.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence, Tuple

from forecast.capital_market_assumptions import DEFAULT_EDUCATION_INFLATION_RATE, DEFAULT_SCENARIO_GROWTH
from forecast.catalog import EQUITY_GROWTH_PRESETS
from forecast.hierarchy import resolve_effective_plan
import security
from services.person_name import first_name
from forecast.context import PLACEHOLDER_PLANNING_AGE
from forecast.mortgage_amortization import (
    DEFAULT_BASELINE_MORTGAGE_RATE,
    BaselineLoan,
    baseline_mortgage_rate,
)
from forecast.waterfall_withdrawals import compute_initial_mortgage_service


def _birth_year(member: Dict[str, Any], as_of_year: int) -> int:
    """The member's birth year, or `as_of_year - PLACEHOLDER_PLANNING_AGE` when no birthdate is on file."""
    birthdate = str(member.get("birthdate") or "")
    return int(birthdate.split("-")[0]) if birthdate else as_of_year - PLACEHOLDER_PLANNING_AGE
import account_sync
from db.engine_inputs import get_mortgage_inputs
from forecast.storage import load_children_edu_reserves
from forecast.orchestrator_series import (
    resolve_asset_allocation_weights,
    build_orchestrator_milestones,
)



def resolve_scenario_run_params(
    scen: Dict[str, Any],
    target_scenario_id: Optional[str],
    explicit_flags: Dict[str, bool],
    base_params: Dict[str, Any],
    equity_growth_presets: Optional[Dict[str, str]],
    equity_companies_list: List[Dict[str, Any]],
    weights: Tuple[float, float, float, float, float, float, float],
    growth_overrides: Dict[str, Optional[float]],
    lp_commitments: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """
    Resolves effective retirement ages, growth presets, holding rates, and asset returns
    for an individual scenario run. `lp_commitments` are the household's private-market commitments,
    loaded once per forecast; each plan only chooses how fast they are called.
    """
    scen_id = scen["id"]
    is_target = (target_scenario_id is None) or (scen_id == target_scenario_id)

    plan = resolve_effective_plan(scen, base_params, explicit_flags, is_target)
    scen_primary_ret = plan.primary_retirement_age
    scen_spouse_ret = plan.spouse_retirement_age
    scen_spending = plan.annual_living_spend
    scen_savings = plan.annual_savings
    scen_inflation = plan.inflation_rate

    scen_education_inflation = float(scen["education_inflation_rate"] if scen.get("education_inflation_rate") is not None else DEFAULT_EDUCATION_INFLATION_RATE)

    scen_growth_preset = scen.get("equity_growth_preset") or base_params.get("equity_growth_preset") or "moderate"
    preset_info = EQUITY_GROWTH_PRESETS.get(scen_growth_preset, EQUITY_GROWTH_PRESETS.get("moderate", {}))
    if scen.get("custom_equity_growth_rate") is not None:
        scen_equity_growth = float(scen["custom_equity_growth_rate"])
    elif "equity_growth_rate" in scen and scen["equity_growth_rate"] is not None:
        scen_equity_growth = float(scen["equity_growth_rate"])
    else:
        scen_equity_growth = preset_info.get("growth_rate", 0.08)

    scen_holding_presets = dict(scen.get("equity_growth_presets") or {})
    if is_target and equity_growth_presets:
        scen_holding_presets.update({str(k): str(v) for k, v in equity_growth_presets.items() if v})
    scen_company_growth_rates: Dict[int, float] = {}
    for c in equity_companies_list:
        cid_int = int(c.get("company_id", 0))
        cid_str = str(cid_int)
        c_preset = scen_holding_presets.get(cid_str) or scen_growth_preset
        scen_holding_presets[cid_str] = c_preset
        p_inf = EQUITY_GROWTH_PRESETS.get(c_preset, preset_info)
        scen_company_growth_rates[cid_int] = p_inf.get("growth_rate", scen_equity_growth)

    scen_primary_ss_claim = plan.primary_ss_claim_age
    scen_spouse_ss_claim = plan.spouse_ss_claim_age
    scen_guardrail_mode = plan.spending_guardrail_mode

    scen["primary_retirement_age"] = scen_primary_ret
    scen["spouse_retirement_age"] = scen_spouse_ret
    scen["annual_living_spend"] = scen_spending
    scen["annual_savings"] = scen_savings
    scen["inflation_rate"] = scen_inflation
    scen["education_inflation_rate"] = scen_education_inflation
    scen["primary_ss_claim_age"] = scen_primary_ss_claim
    scen["spouse_ss_claim_age"] = scen_spouse_ss_claim
    scen["ss_claim_age"] = scen_primary_ss_claim
    scen["equity_growth_preset"] = scen_growth_preset
    scen["spending_guardrail_mode"] = scen_guardrail_mode
    scen["equity_growth_presets"] = scen_holding_presets
    scen["equity_growth_rate"] = scen_equity_growth

    raw_drawdown = scen.get("drawdown_order") or base_params.get("drawdown_order") or "taxable_first"
    scen_drawdown_order = str(raw_drawdown).lower().strip() if str(raw_drawdown).lower().strip() in ("taxable_first", "pretax_first", "pro_rata") else "taxable_first"
    scen_accelerate_lp = bool(scen.get("accelerate_lp_calls") if scen.get("accelerate_lp_calls") is not None else base_params.get("accelerate_lp_calls", False))
    scen["drawdown_order"] = scen_drawdown_order
    scen["accelerate_lp_calls"] = scen_accelerate_lp

    from services.private_markets_service import lp_call_schedule

    lp_schedule = lp_call_schedule(
        list(lp_commitments), accelerate=scen_accelerate_lp, start_year=base_params["start_year"]
    )

    def _growth(field: str) -> float:
        return float(scen[field] if scen.get(field) is not None else DEFAULT_SCENARIO_GROWTH[field])

    growth_us = _growth("growth_us_equity")
    growth_intl = _growth("growth_intl_equity")
    growth_bonds = _growth("growth_bonds")
    growth_cash = _growth("growth_cash")
    growth_private = _growth("growth_private_investments")
    growth_re = _growth("growth_real_estate")

    if is_target:
        if growth_overrides.get("us") is not None: growth_us = float(growth_overrides["us"])
        if growth_overrides.get("intl") is not None: growth_intl = float(growth_overrides["intl"])
        if growth_overrides.get("bonds") is not None: growth_bonds = float(growth_overrides["bonds"])
        if growth_overrides.get("cash") is not None: growth_cash = float(growth_overrides["cash"])
        if growth_overrides.get("private") is not None: growth_private = float(growth_overrides["private"])
        if growth_overrides.get("re") is not None: growth_re = float(growth_overrides["re"])

    w_us, w_intl, w_bonds, w_cash, w_ret_us, w_ret_intl, w_ret_bonds = weights
    scen_blended_liquid = (w_us * growth_us) + (w_intl * growth_intl) + (w_bonds * growth_bonds) + (w_cash * growth_cash)
    scen_blended_retire = (w_ret_us * growth_us) + (w_ret_intl * growth_intl) + (w_ret_bonds * growth_bonds)

    scen["growth_us_equity"] = growth_us
    scen["growth_intl_equity"] = growth_intl
    scen["growth_bonds"] = growth_bonds
    scen["growth_cash"] = growth_cash
    scen["growth_private_investments"] = growth_private
    scen["growth_real_estate"] = growth_re
    scen["blended_liquid_growth"] = round(scen_blended_liquid, 4)
    scen["blended_retire_growth"] = round(scen_blended_retire, 4)

    return {
        "plan": plan,
        "scen_primary_ret": scen_primary_ret,
        "scen_spouse_ret": scen_spouse_ret,
        "scen_spending": scen_spending,
        "scen_savings": scen_savings,
        "scen_inflation": scen_inflation,
        "scen_education_inflation": scen_education_inflation,
        "scen_primary_ss_claim": scen_primary_ss_claim,
        "scen_spouse_ss_claim": scen_spouse_ss_claim,
        "scen_growth_preset": scen_growth_preset,
        "scen_equity_annual_growth": scen_equity_growth,
        "scen_holding_presets": scen_holding_presets,
        "scen_company_growth_rates": scen_company_growth_rates,
        "growth_us": growth_us,
        "growth_intl": growth_intl,
        "growth_bonds_rate": growth_bonds,
        "growth_cash_rate": growth_cash,
        "growth_private": growth_private,
        "growth_re": growth_re,
        "scen_blended_liquid": scen_blended_liquid,
        "scen_blended_retire": scen_blended_retire,
        "drawdown_order": scen_drawdown_order,
        "accelerate_lp_calls": scen_accelerate_lp,
        "lp_call_schedule": lp_schedule,
        "preset_info": preset_info,
        "scen_drawdown_order": scen_drawdown_order,
        "scen_accelerate_lp": scen_accelerate_lp,
        "lp_schedule": lp_schedule,
    }


def build_retirement_readiness(
    sim_out: Dict[str, Any],
    scen_spending: float,
    primary_birth_year: int,
    spouse_birth_year: int,
    scen_primary_ret: int,
    scen_spouse_ret: int,
    primary_name: str,
    spouse_name: str,
    current_primary_age: int,
    current_spouse_age: int,
    earliest_joint_yr: Optional[int],
    earliest_p_age: Optional[int],
    earliest_s_age: Optional[int],
    can_retire_today: bool,
    as_of_year: int,
) -> Tuple[Dict[str, Any], float, Optional[int], bool]:
    """
    Computes financial independence crossover and builds the retirement readiness dictionary.
    """
    primary_ret_yr = primary_birth_year + scen_primary_ret
    spouse_ret_yr = spouse_birth_year + scen_spouse_ret
    primary_yrs_away = max(0, primary_ret_yr - as_of_year)
    spouse_yrs_away = max(0, spouse_ret_yr - as_of_year)

    fi_threshold = round(scen_spending * 25.0, 2)
    fi_crossover_yr = None
    for r in sim_out.get("schedule", []):
        # The threshold is in today's dollars, so compare against today's-dollar balances.
        if (r.get("liquid_assets", 0.0) + r.get("retirement_assets", 0.0)) * r["to_todays_dollars"] >= fi_threshold:
            fi_crossover_yr = r["year"]
            break
    fi_achieved = (fi_crossover_yr is not None and fi_crossover_yr <= as_of_year)

    readiness = {
        "primary_name": primary_name,
        "spouse_name": spouse_name,
        "primary_current_age": current_primary_age,
        "spouse_current_age": current_spouse_age,
        "primary_planned_age": scen_primary_ret,
        "primary_planned_year": primary_ret_yr,
        "primary_years_away": primary_yrs_away,
        "spouse_planned_age": scen_spouse_ret,
        "spouse_planned_year": spouse_ret_yr,
        "spouse_years_away": spouse_yrs_away,
        "is_sustainable": not sim_out["depleted"],
        "terminal_net_worth": round(sim_out["schedule"][-1]["total_net_worth"], 2) if sim_out.get("schedule") else 0.0,
        "fi_crossover_year": fi_crossover_yr,
        "fi_achieved": fi_achieved,
        "fi_threshold": fi_threshold,
        "earliest_joint_year": earliest_joint_yr,
        "earliest_primary_age": earliest_p_age,
        "earliest_spouse_age": earliest_s_age,
        "can_retire_today": can_retire_today,
        "liquid_capital": round(sim_out["schedule"][0]["liquid_assets"] + sim_out["schedule"][0]["retirement_assets"], 2) if sim_out.get("schedule") else 0.0,
        "annual_spending": scen_spending,
    }
    return readiness, fi_threshold, fi_crossover_yr, fi_achieved


def resolve_mortgage_service(snapshot: Dict[str, Any], mortgage_start: float, entered: Dict[str, float]) -> float:
    """
    Annual debt service on the starting mortgage. An entered remaining term (Settings) amortizes the balance at the
    account's rate, else the entered rate, else the default rate; with no term the balance sheet's reported payment
    stands, and with neither the default term applies.
    """
    if mortgage_start <= 0:
        return 0.0
    accounts = snapshot.get("categories", {}).get("mortgages", {}).get("accounts", [])
    rate = baseline_mortgage_rate(accounts) or entered.get("annual_rate") or DEFAULT_BASELINE_MORTGAGE_RATE
    if "remaining_term_years" in entered:
        return BaselineLoan(mortgage_start, rate, entered["remaining_term_years"]).level_annual_service()
    reported = float(snapshot.get("mortgage_annual_service") or 0.0)
    return reported if reported > 0 else compute_initial_mortgage_service(mortgage_start, rate)


def resolve_orchestrator_baseline_finances(
    family_id: int,
    db_file: str,
    primary_retirement_age: int,
    spouse_retirement_age: int,
    as_of_year: int,
) -> Dict[str, Any]:
    """
    Resolves Monarch snapshot, starting balances, debt service, allocation weights,
    family members, ages, and educational milestones.
    """
    snapshot = account_sync.get_financial_snapshot(family_id=family_id)
    liquid_start = float(snapshot.get("liquid_non_equity_assets", 0.0) or 0.0)
    retirement_start = float(snapshot.get("categories", {}).get("retirement", {}).get("total", 0.0) or 0.0)
    real_estate_start = float(snapshot.get("categories", {}).get("real_estate", {}).get("total", 0.0) or 0.0)
    mortgage_start = abs(float(snapshot.get("categories", {}).get("mortgages", {}).get("total", 0.0) or 0.0))
    other_start = float(snapshot.get("categories", {}).get("private_investments", {}).get("total", 0.0) or 0.0)

    mortgage_annual_service = resolve_mortgage_service(
        snapshot, mortgage_start, get_mortgage_inputs(family_id=family_id, db_path=db_file),
    )

    weights = resolve_asset_allocation_weights(snapshot)

    members = security.get_family_members(db_file, family_id=family_id)
    primary_member = next((m for m in members if m.get("relationship") == "primary"), {})
    spouse_member = next((m for m in members if m.get("relationship") == "spouse"), {})
    primary_birth_year = _birth_year(primary_member, as_of_year)
    spouse_birth_year = _birth_year(spouse_member, as_of_year)
    current_primary_age = as_of_year - primary_birth_year
    current_spouse_age = as_of_year - spouse_birth_year

    primary_name = first_name(primary_member.get("name") or "", "Primary")
    spouse_name = first_name(spouse_member.get("name") or "", "Spouse")

    children_edu = load_children_edu_reserves(family_id=family_id)
    milestones = build_orchestrator_milestones(
        primary_birth_year=primary_birth_year,
        spouse_birth_year=spouse_birth_year,
        primary_retirement_age=primary_retirement_age,
        spouse_retirement_age=spouse_retirement_age,
        primary_name=primary_name,
        spouse_name=spouse_name,
        current_primary_age=current_primary_age,
        current_spouse_age=current_spouse_age,
        children_edu=children_edu,
        as_of_year=as_of_year,
    )

    return {
        "snapshot": snapshot,
        "liquid_start": liquid_start,
        "retirement_start": retirement_start,
        "real_estate_start": real_estate_start,
        "mortgage_start": mortgage_start,
        "other_start": other_start,
        "mortgage_annual_service": mortgage_annual_service,
        "weights": weights,
        "primary_birth_year": primary_birth_year,
        "spouse_birth_year": spouse_birth_year,
        "current_primary_age": current_primary_age,
        "current_spouse_age": current_spouse_age,
        "primary_name": primary_name,
        "spouse_name": spouse_name,
        "children_edu": children_edu,
        "milestones": milestones,
    }


