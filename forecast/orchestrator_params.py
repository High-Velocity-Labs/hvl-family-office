"""
forecast/orchestrator_params.py: Scenario parameter resolution and retirement readiness builder.
Extracted from forecast/orchestrator.py to maintain modularity and single responsibility.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple

from forecast.catalog import EQUITY_GROWTH_PRESETS
import security
import monarch_service
from forecast.storage import load_children_edu_reserves
from forecast.orchestrator_helpers import (
    resolve_asset_allocation_weights,
    build_orchestrator_milestones,
)

_CURRENT_SCENARIO_RUN_PARAMS: Dict[str, Any] = {}
_CURRENT_ORCHESTRATOR_FAMILY_ID: int = 0


def set_active_scenario_run_params(params: Dict[str, Any]) -> None:
    """Sets active scenario run parameters for consumption by waterfall simulation."""
    global _CURRENT_SCENARIO_RUN_PARAMS
    _CURRENT_SCENARIO_RUN_PARAMS = dict(params)


def get_active_scenario_run_params() -> Dict[str, Any]:
    """Returns active scenario run parameters."""
    return dict(_CURRENT_SCENARIO_RUN_PARAMS)




def resolve_scenario_run_params(
    scen: Dict[str, Any],
    target_scenario_id: Optional[str],
    explicit_flags: Dict[str, bool],
    base_params: Dict[str, Any],
    equity_growth_presets: Optional[Dict[str, str]],
    equity_companies_list: List[Dict[str, Any]],
    weights: Tuple[float, float, float, float, float, float, float],
    growth_overrides: Dict[str, Optional[float]],
) -> Dict[str, Any]:
    """
    Resolves effective retirement ages, growth presets, holding rates, and asset returns
    for an individual scenario run.
    """
    scen_id = scen["id"]
    is_target = (target_scenario_id is None) or (scen_id == target_scenario_id)

    primary_ret = base_params["primary_retirement_age"]
    spouse_ret = base_params["spouse_retirement_age"]
    spending = base_params["annual_living_spend"]
    savings = base_params["annual_savings"]
    inflation = base_params["inflation_rate"]
    primary_ss = base_params["primary_ss_claim_age"]
    spouse_ss = base_params["spouse_ss_claim_age"]
    fallback_ss = scen.get("ss_claim_age") or primary_ss

    scen_primary_ret = (primary_ret if explicit_flags["primary_ret"] else (scen.get("primary_retirement_age") or primary_ret)) if is_target else (scen.get("primary_retirement_age") or primary_ret)
    scen_spouse_ret = (spouse_ret if explicit_flags["spouse_ret"] else (scen.get("spouse_retirement_age") or spouse_ret)) if is_target else (scen.get("spouse_retirement_age") or spouse_ret)
    scen_spending = (spending if explicit_flags["spending"] else (scen.get("annual_living_spend") or spending)) if is_target else (scen.get("annual_living_spend") or spending)
    scen_savings = (savings if explicit_flags["savings"] else (scen.get("annual_savings") or savings)) if is_target else (scen.get("annual_savings") or savings)
    scen_inflation = (inflation if explicit_flags["inflation"] else (scen.get("inflation_rate") if scen.get("inflation_rate") is not None else inflation)) if is_target else (scen.get("inflation_rate") if scen.get("inflation_rate") is not None else inflation)

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

    scen_primary_ss_claim = int((primary_ss if explicit_flags["primary_ss"] else (scen.get("primary_ss_claim_age") or fallback_ss)) if is_target else (scen.get("primary_ss_claim_age") or fallback_ss))
    scen_spouse_ss_claim = int((spouse_ss if explicit_flags["spouse_ss"] else (scen.get("spouse_ss_claim_age") or (scen.get("ss_claim_age") or spouse_ss))) if is_target else (scen.get("spouse_ss_claim_age") or (scen.get("ss_claim_age") or spouse_ss)))
    raw_guardrails = (base_params.get("spending_guardrail_mode") if explicit_flags.get("guardrails") else (scen.get("spending_guardrail_mode") or "off")) if is_target else (scen.get("spending_guardrail_mode") or "off")
    scen_guardrail_mode = str(raw_guardrails).lower().strip() if raw_guardrails in ("off", "moderate", "aggressive") else "off"

    scen["primary_retirement_age"] = scen_primary_ret
    scen["spouse_retirement_age"] = scen_spouse_ret
    scen["annual_living_spend"] = scen_spending
    scen["annual_savings"] = scen_savings
    scen["inflation_rate"] = scen_inflation
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

    fam_id = int(scen.get("family_id") or base_params.get("family_id") or _CURRENT_ORCHESTRATOR_FAMILY_ID or 0)
    lp_schedule: Dict[int, float] = {}
    if fam_id > 0:
        try:
            from services.private_markets_service import get_lp_call_schedule
            lp_schedule = get_lp_call_schedule(family_id=fam_id, accelerate=scen_accelerate_lp)
        except Exception:
            lp_schedule = {}

    set_active_scenario_run_params({
        "drawdown_order": scen_drawdown_order,
        "accelerate_lp_calls": scen_accelerate_lp,
        "lp_call_schedule": lp_schedule,
        "family_id": fam_id,
    })

    growth_us = float(scen.get("growth_us_equity") if scen.get("growth_us_equity") is not None else 0.075)
    growth_intl = float(scen.get("growth_intl_equity") if scen.get("growth_intl_equity") is not None else 0.065)
    growth_bonds = float(scen.get("growth_bonds") if scen.get("growth_bonds") is not None else 0.042)
    growth_cash = float(scen.get("growth_cash") if scen.get("growth_cash") is not None else 0.028)
    growth_private = float(scen.get("growth_private_investments") if scen.get("growth_private_investments") is not None else 0.100)
    growth_re = float(scen.get("growth_real_estate") if scen.get("growth_real_estate") is not None else 0.035)

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
        "scen_primary_ret": scen_primary_ret,
        "scen_spouse_ret": scen_spouse_ret,
        "scen_spending": scen_spending,
        "scen_savings": scen_savings,
        "scen_inflation": scen_inflation,
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
) -> Tuple[Dict[str, Any], float, Optional[int], bool]:
    """
    Computes financial independence crossover and builds the retirement readiness dictionary.
    """
    primary_ret_yr = primary_birth_year + scen_primary_ret
    spouse_ret_yr = spouse_birth_year + scen_spouse_ret
    primary_yrs_away = max(0, primary_ret_yr - 2026)
    spouse_yrs_away = max(0, spouse_ret_yr - 2026)

    fi_threshold = round(scen_spending * 25.0, 2)
    fi_crossover_yr = None
    for r in sim_out.get("schedule", []):
        if (r.get("liquid_assets", 0.0) + r.get("retirement_assets", 0.0)) >= fi_threshold:
            fi_crossover_yr = r["year"]
            break
    fi_achieved = (fi_crossover_yr is not None and fi_crossover_yr <= 2026)

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


def resolve_orchestrator_baseline_finances(
    family_id: int,
    db_file: str,
    primary_retirement_age: int,
    spouse_retirement_age: int,
) -> Dict[str, Any]:
    """
    Resolves Monarch snapshot, starting balances, debt service, allocation weights,
    family members, ages, and educational milestones.
    """
    global _CURRENT_ORCHESTRATOR_FAMILY_ID
    _CURRENT_ORCHESTRATOR_FAMILY_ID = family_id
    snapshot = monarch_service.get_financial_snapshot(family_id=family_id)
    liquid_start = float(snapshot.get("liquid_non_equity_assets", 0.0) or 0.0)
    retirement_start = float(snapshot.get("categories", {}).get("retirement", {}).get("total", 0.0) or 0.0)
    real_estate_start = float(snapshot.get("categories", {}).get("real_estate", {}).get("total", 0.0) or 0.0)
    mortgage_start = abs(float(snapshot.get("categories", {}).get("mortgages", {}).get("total", 0.0) or 0.0))
    other_start = float(snapshot.get("categories", {}).get("private_investments", {}).get("total", 0.0) or 0.0)

    mortgage_annual_service = float(snapshot.get("mortgage_annual_service") or 0.0)
    if mortgage_annual_service <= 0 and mortgage_start > 0:
        r_m = 0.065 / 12.0
        n_m = 360
        mortgage_annual_service = mortgage_start * (r_m * ((1.0 + r_m) ** n_m)) / (((1.0 + r_m) ** n_m) - 1.0) * 12.0

    weights = resolve_asset_allocation_weights(snapshot)

    members = security.get_family_members(db_file, family_id=family_id)
    primary_member = next((m for m in members if m.get("relationship") == "primary"), {})
    spouse_member = next((m for m in members if m.get("relationship") == "spouse"), {})
    primary_birth_year = int(primary_member.get("birthdate", "1980-01-01").split("-")[0]) if primary_member.get("birthdate") else 1980
    spouse_birth_year = int(spouse_member.get("birthdate", "1980-01-01").split("-")[0]) if spouse_member.get("birthdate") else 1980
    current_primary_age = 2026 - primary_birth_year
    current_spouse_age = 2026 - spouse_birth_year

    primary_name = primary_member.get("name", "Primary").split()[0] if primary_member.get("name") else "Primary"
    spouse_name = spouse_member.get("name", "Spouse").split()[0] if spouse_member.get("name") else "Spouse"

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


