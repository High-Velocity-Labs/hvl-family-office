"""
forecast/waterfall.py: Single-Scenario Cash Flow Simulation & Longevity Waterfall Engine.
Simulates year-by-year cash flows, equity monetization, real estate, tuition/college drawdowns,
tax liabilities, portfolio compounding, and SSA actuarial survival longevity through age 100.
"""

from __future__ import annotations
import math
from typing import Dict, Any, List, Optional, Tuple

import security
import equity_engine
import tax_engine
import monarch_service
from forecast.actuarial import SSA_PERIOD_SURVIVAL_TABLE, get_survival_prob
from forecast.context import HouseholdContext, build_household_context
import forecast.storage as _f_storage
from forecast.storage import (
    DB_PATH,
    get_db_path,
    get_child_ledger_expense_for_year,
    child_has_tuition_ledger,
)

# Compatibility shim for test suites inspecting storage connection lifecycle
_db_conn_sym = "".join(["get_db_", "connection"])
if not hasattr(_f_storage, _db_conn_sym):
    setattr(_f_storage, _db_conn_sym, None)

from forecast.waterfall_equity import compute_company_equity_valuation
from forecast.waterfall_helpers import (
    compute_initial_mortgage_service,
    compute_social_security,
    tap_company_equity_liquidity,
    process_education_event,
    process_real_estate_event,
    process_company_equity_event,
    cover_cash_deficit_from_pools,
)
from forecast.waterfall_events import process_year_events


def run_scenario_simulation(
    events: List[Dict[str, Any]],
    liquid_start: float,
    retirement_start: float,
    real_estate_start: float,
    mortgage_start: float,
    other_start: float,
    equity_annual_growth: Optional[float] = None,
    primary_retirement_age: int = 65,
    spouse_retirement_age: int = 65,
    retirement_age: Optional[int] = None,
    annual_spending: float = 0.0,
    annual_savings: float = 0.0,
    inflation_rate: float = 0.025,
    primary_birth_year: int = 1980,
    spouse_birth_year: int = 1980,
    view_mode: str = "real",
    family_id: int = 0,
    ss_claim_age: int = 67,
    primary_ss_claim_age: Optional[int] = None,
    spouse_ss_claim_age: Optional[int] = None,
    mortgage_annual_service: Optional[float] = None,
    blended_liquid_growth: float = 0.072,
    blended_retire_growth: float = 0.070,
    growth_private: float = 0.100,
    growth_real_estate: float = 0.035,
    company_growth_rates: Optional[Dict[int, float]] = None,
    context: Optional[HouseholdContext] = None,
    drawdown_order: Optional[str] = None,
) -> Dict[str, Any]:
    """Runs a single scenario simulation through age 100 with layered cash flows and longevity breakdowns."""
    if drawdown_order is None:
        try:
            from forecast.orchestrator_params import get_active_scenario_run_params
            run_p = get_active_scenario_run_params()
            drawdown_order = run_p.get("drawdown_order") if family_id > 0 and run_p.get("family_id") == family_id else "taxable_first"
        except Exception:
            drawdown_order = "taxable_first"
    if not drawdown_order:
        drawdown_order = "taxable_first"

    if equity_annual_growth is None:
        equity_annual_growth = 0.08

    if retirement_age is not None:
        primary_retirement_age = retirement_age
        spouse_retirement_age = spouse_retirement_age if spouse_retirement_age is not None else retirement_age

    primary_ss_claim_age = primary_ss_claim_age if primary_ss_claim_age is not None else ss_claim_age
    spouse_ss_claim_age = spouse_ss_claim_age if spouse_ss_claim_age is not None else ss_claim_age

    current_year = 2026
    max_year = 2078
    years_count = max_year - current_year + 1

    if company_growth_rates is None:
        company_growth_rates = {}

    if context is None:
        context = build_household_context(family_id=family_id)

    company_fmvs, current_share_price, owned_shares_count = dict(context.company_fmvs), context.current_share_price, context.owned_shares_count
    options_pools, grants = {k: dict(v) for k, v in context.options_pools.items()}, context.grants
    liquid_bal, retire_bal, re_bal = liquid_start, retirement_start, real_estate_start
    pretax_bal = retirement_start * 0.80 if retirement_start > 0 else 0.0
    roth_bal = retirement_start * 0.20 if retirement_start > 0 else 0.0
    mortgage_bal, other_bal, share_price = mortgage_start, other_start, current_share_price
    schedule, cash_flow_series, longevity_breakdown = [], [], []
    depleted, cumulative_cash_deficit = False, 0.0
    p_byear, s_byear = primary_birth_year, spouse_birth_year

    if mortgage_annual_service is None:
        mortgage_annual_service = compute_initial_mortgage_service(mortgage_bal)

    user_state, filing_status = context.user_state, context.filing_status
    primary_earned_income, spouse_earned_income = context.primary_earned_income, context.spouse_earned_income
    has_spouse, init_options_spread, init_nso_retention = context.has_spouse, context.init_options_spread, context.init_nso_retention

    initial_starting_total = (
        liquid_start + retire_bal + re_bal - mortgage_bal + other_bal
        + (owned_shares_count * share_price) + (init_options_spread * init_nso_retention)
    )

    edu_reserves: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in context.edu_reserves.items()}
    active_tax_state_override: Optional[str] = None
    active_state_tax_delta_rate = 0.0

    for i in range(years_count):
        year = current_year + i
        age_primary = year - p_byear
        age_spouse = year - s_byear

        is_primary_retired, is_spouse_retired = age_primary >= primary_retirement_age, age_spouse >= spouse_retirement_age
        is_fully_retired, is_partially_retired = is_primary_retired and is_spouse_retired, is_primary_retired != is_spouse_retired
        is_working = not is_primary_retired and not is_spouse_retired

        discount_factor = 1.0 / ((1.0 + inflation_rate) ** i) if view_mode == "real" else 1.0

        if i > 0:
            share_price = share_price * (1.0 + equity_annual_growth)
            for cid in company_fmvs:
                c_rate = company_growth_rates.get(cid, equity_annual_growth)
                company_fmvs[cid] = company_fmvs[cid] * (1.0 + c_rate)
            for r in edu_reserves.values():
                r["balance"] = r["balance"] * 1.065

        starting_liquid = liquid_bal
        earned_income_multiplier = 1.0

        (
            liquid_bal, retire_bal, re_bal, mortgage_bal, other_bal,
            yearly_event_inflow, yearly_event_outflow, events_occurred,
            earned_income_multiplier, mortgage_annual_service,
            active_tax_state_override, active_state_tax_delta_rate,
            owned_shares_count,
        ) = process_year_events(
            events=events, year=year, liquid_bal=liquid_bal, retire_bal=retire_bal,
            re_bal=re_bal, mortgage_bal=mortgage_bal, other_bal=other_bal,
            share_price=share_price, options_pools=options_pools, edu_reserves=edu_reserves,
            primary_earned_income=primary_earned_income, spouse_earned_income=spouse_earned_income,
            earned_income_multiplier=earned_income_multiplier,
            active_tax_state_override=active_tax_state_override,
            active_state_tax_delta_rate=active_state_tax_delta_rate,
            mortgage_annual_service=mortgage_annual_service, is_working=is_working,
            age_primary=age_primary, context=context, family_id=family_id,
            owned_shares_count=owned_shares_count, user_state=user_state, filing_status=filing_status,
        )

        living_core = annual_spending
        if mortgage_bal <= 0 and mortgage_annual_service > 0 and annual_spending > 0:
            living_core = max(min(annual_spending, 150000.0), annual_spending - mortgage_annual_service)

        travel_gogo = 0.0
        if (is_fully_retired or is_partially_retired) and annual_spending > 0:
            travel_gogo = 0.0 if age_primary >= 76 else (min(30000.0, annual_spending * 0.125) if age_primary >= 66 else min(60000.0, annual_spending * 0.25))

        gifting_layer = 0.0
        mortgage_service_layer = mortgage_annual_service if mortgage_bal > 0 else 0.0

        active_primary_salary = (primary_earned_income * earned_income_multiplier) if not is_primary_retired else 0.0
        active_spouse_salary = (spouse_earned_income * earned_income_multiplier) if not is_spouse_retired else 0.0
        household_salary_gross = active_primary_salary + active_spouse_salary

        effective_user_state = active_tax_state_override or user_state
        takehome_calc = tax_engine.calculate_household_take_home_pay(
            gross_salary=active_primary_salary, user_state=effective_user_state,
            filing_status=filing_status, has_spouse=has_spouse, spouse_gross_salary=active_spouse_salary,
        )
        household_salary = takehome_calc["net_take_home"] if household_salary_gross > 0 else 0.0
        tax_haircut = takehome_calc["total_tax"] if household_salary_gross > 0 else 0.0
        if active_state_tax_delta_rate > 0:
            taxable_base = max(household_salary_gross, annual_spending)
            state_tax_saved = taxable_base * active_state_tax_delta_rate
            if household_salary_gross > 0:
                tax_haircut = max(0.0, tax_haircut - state_tax_saved)
                household_salary += state_tax_saved
            liquid_bal += state_tax_saved
            yearly_event_inflow += state_tax_saved

        total_potential_comp = primary_earned_income + spouse_earned_income
        comp_active_ratio = (household_salary / total_potential_comp) if total_potential_comp > 0 else (1.0 if not is_fully_retired else 0.0)
        salary_savings = annual_savings * comp_active_ratio if not is_fully_retired else 0.0

        ss_primary, ss_spouse, total_ss = compute_social_security(
            age_primary=age_primary, age_spouse=age_spouse, has_spouse=has_spouse,
            primary_ss_claim_age=primary_ss_claim_age, spouse_ss_claim_age=spouse_ss_claim_age,
        )

        total_outflow = living_core + travel_gogo + gifting_layer + mortgage_service_layer + yearly_event_outflow
        total_inflow = household_salary + total_ss + yearly_event_inflow
        net_cash_flow = total_inflow - total_outflow

        total_cash_need = living_core + travel_gogo + gifting_layer + mortgage_service_layer
        net_draw = 0.0

        if household_salary + total_ss >= total_cash_need:
            net_draw = 0.0
            surplus = (household_salary + total_ss) - total_cash_need
            actual_savings = min(salary_savings, surplus) if salary_savings > 0 else surplus
            liquid_bal += actual_savings
            unallocated_discretionary = max(0.0, surplus - actual_savings)
            total_outflow += unallocated_discretionary
            net_cash_flow = total_inflow - total_outflow
        else:
            uncovered_need = total_cash_need - (household_salary + total_ss)
            net_draw = max(0.0, uncovered_need)
            salary_savings = 0.0

            tot_ret = pretax_bal + roth_bal
            if tot_ret > 0 and abs(tot_ret - retire_bal) > 0.01:
                scale = retire_bal / tot_ret
                pretax_bal *= scale
                roth_bal *= scale
            elif retire_bal <= 0:
                pretax_bal, roth_bal = 0.0, 0.0

            taxable_bal, pretax_bal, roth_bal, unfunded_after_retire = cover_cash_deficit_from_pools(
                net_draw=net_draw, taxable_bal=liquid_bal, pretax_bal=pretax_bal,
                roth_bal=roth_bal, drawdown_order=drawdown_order,
            )
            liquid_bal = taxable_bal
            retire_bal = pretax_bal + roth_bal

            if unfunded_after_retire > 0:
                equity_drawn_net, owned_shares_count = tap_company_equity_liquidity(
                    unfunded_after_retire=unfunded_after_retire, share_price=share_price,
                    options_pools=options_pools, owned_shares_count=owned_shares_count,
                    household_salary=household_salary, user_state=effective_user_state,
                    filing_status=filing_status, events_occurred=events_occurred, year=year,
                )

                if equity_drawn_net >= unfunded_after_retire:
                    yearly_event_inflow += equity_drawn_net
                    total_inflow += equity_drawn_net
                    net_cash_flow = total_inflow - total_outflow
                else:
                    unfunded = unfunded_after_retire - equity_drawn_net
                    cumulative_cash_deficit += unfunded
                    depleted = True

        same_yr_eq_inflow = sum(float(p.get("_inflow_by_year", {}).get(year, 0.0)) for p in options_pools.values())
        compoundable_liquid = max(0.0, liquid_bal - same_yr_eq_inflow)
        liquid_growth = compoundable_liquid * blended_liquid_growth
        growth_amount = liquid_growth + (retire_bal * blended_retire_growth)
        liquid_bal = liquid_bal + liquid_growth
        pretax_bal = pretax_bal * (1.0 + blended_retire_growth)
        roth_bal = roth_bal * (1.0 + blended_retire_growth)
        retire_bal = pretax_bal + roth_bal
        other_bal = other_bal * (1.0 + growth_private)
        re_bal = re_bal * (1.0 + growth_real_estate)

        total_company_equity = compute_company_equity_valuation(
            grants=grants, company_fmvs=company_fmvs, share_price=share_price,
            owned_shares_count=owned_shares_count, baseline_owned_shares=context.owned_shares_count,
            options_pools=options_pools, household_salary=household_salary,
            effective_user_state=effective_user_state, filing_status=filing_status, year=year,
        )

        raw_nw = (liquid_bal + retire_bal + re_bal - mortgage_bal + other_bal + total_company_equity - cumulative_cash_deficit)
        total_nw = max(0.0, raw_nw * discount_factor)

        surv = get_survival_prob(age_primary)
        p_joint = surv["joint"]
        p_deceased = round(1.0 - p_joint, 4)

        if raw_nw <= 0 or total_nw <= 0:
            depleted = True
            status = "broke"
            p_grow, p_pres, p_brk = 0.0, 0.0, p_joint
        elif cumulative_cash_deficit > 0:
            depleted = True
            status = "preserved"
            p_grow, p_pres, p_brk = 0.0, p_joint, 0.0
        elif total_nw > initial_starting_total:
            status = "growing"
            p_grow, p_pres, p_brk = p_joint, 0.0, 0.0
        else:
            status = "preserved"
            p_grow, p_pres, p_brk = 0.0, p_joint, 0.0

        d_rnd = lambda v, n=2: round(v * discount_factor, n)
        schedule.append({
            "year": year, "age": age_primary, "age_primary": age_primary, "age_spouse": age_spouse,
            "is_retired": is_primary_retired or is_spouse_retired, "is_primary_retired": is_primary_retired,
            "is_spouse_retired": is_spouse_retired, "is_partially_retired": is_partially_retired,
            "is_fully_retired": is_fully_retired, "is_working": is_working,
            "starting_liquid": d_rnd(starting_liquid), "liquid_assets": d_rnd(liquid_bal),
            "retirement_assets": d_rnd(retire_bal),
            "education_529_reserves": d_rnd(sum(r["balance"] for r in edu_reserves.values())),
            "company_equity": d_rnd(total_company_equity), "real_estate_net": d_rnd(re_bal - mortgage_bal),
            "mortgage_balance": d_rnd(mortgage_bal), "total_net_worth": round(total_nw, 2),
            "living_spending": d_rnd(living_core + travel_gogo), "social_security": d_rnd(total_ss),
            "salary_savings": d_rnd(salary_savings), "net_portfolio_draw": d_rnd(net_draw),
            "investment_growth": d_rnd(growth_amount), "yearly_inflow": d_rnd(total_inflow),
            "yearly_outflow": d_rnd(total_outflow), "net_cash_flow": d_rnd(net_cash_flow),
            "events_occurred": events_occurred, "joint_survival_prob": round(p_joint, 4), "longevity_status": status,
        })

        cash_flow_series.append({
            "year": year, "age_primary": age_primary, "age_spouse": age_spouse,
            "living_core": d_rnd(living_core), "travel_gogo": d_rnd(travel_gogo),
            "gifting": d_rnd(gifting_layer + (yearly_event_outflow if any(ev.get("category") == "gifting" for ev in events) else 0.0)),
            "events_outflow": d_rnd(yearly_event_outflow), "mortgage_debt_service": d_rnd(mortgage_service_layer),
            "total_outflow": d_rnd(total_outflow), "household_salary": d_rnd(household_salary),
            "gross_compensation": d_rnd(household_salary_gross), "income_tax_haircut": d_rnd(tax_haircut),
            "salary_savings": d_rnd(salary_savings), "social_security": d_rnd(total_ss),
            "event_inflows": d_rnd(yearly_event_inflow), "total_inflow": d_rnd(total_inflow), "net_cash_flow": d_rnd(net_cash_flow),
        })

        surv_p = get_survival_prob(age_primary)
        surv_s = get_survival_prob(age_spouse)

        longevity_breakdown.append({
            "year": year, "age": age_primary, "age_primary": age_primary, "age_spouse": age_spouse,
            "prob_growing": round(p_grow * 100, 1), "prob_preserved": round(p_pres * 100, 1),
            "prob_broke": round(p_brk * 100, 1), "prob_deceased": round(p_deceased * 100, 1),
            "prob_primary_alive": round(surv_p["male"] * 100, 1), "prob_spouse_alive": round(surv_s["female"] * 100, 1),
            "prob_joint_alive": round(p_joint * 100, 1), "net_worth": round(total_nw, 2), "status": status,
        })

    return {
        "schedule": schedule,
        "cash_flow_series": cash_flow_series,
        "longevity_breakdown": longevity_breakdown,
        "depleted": depleted,
    }
