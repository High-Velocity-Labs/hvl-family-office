"""
forecast/orchestrator.py: Multi-Scenario Comparison and Cash Flow Simulation Orchestrator.
Simulates all scenarios simultaneously with independent per-spouse retirement timelines,
layered cash flows, hierarchy resolution, asset allocation weighting, and Monte Carlo integration.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import date

from services import equity_engine
from services.private_markets_service import get_lp_commitments
from db.session import resolve_db_path

from forecast.context import build_household_context
from forecast.mortgage_amortization import baseline_mortgage_rate
from forecast.retirement_split import pretax_share
from forecast.social_security import adults_without_social_security
from forecast.storage import (
    get_db_path,
    load_historical_forecast_actuals,
    load_scenario_state,
)
from forecast.capital_market_assumptions import DEFAULT_SCENARIO_GROWTH, resolve_portfolio_weights
from forecast.catalog import EQUITY_GROWTH_PRESETS
from forecast import plan_run_cache
from forecast.hierarchy import resolve_scenario_hierarchy
from forecast.waterfall import run_scenario_simulation
from forecast.orchestrator_builder import (
    build_scenario_scorecard_entry,
    package_simulation_response,
)
from forecast.orchestrator_series import (
    attach_monte_carlo_solvency,
    build_comparison_curves,
    find_earliest_sustainable_retirement,
    resolve_profile_defaults,
)
from forecast.orchestrator_params import (
    resolve_scenario_run_params,
    build_retirement_readiness,
    resolve_orchestrator_baseline_finances,
)




def simulate_multi_scenarios(
    family_id: int = 0,
    target_scenario_id: Optional[str] = None,
    equity_growth_preset: Optional[str] = None,
    equity_growth_presets: Optional[Dict[str, str]] = None,
    custom_equity_growth_rate: Optional[float] = None,
    retirement_age: Optional[int] = None,
    primary_retirement_age: Optional[int] = None,
    spouse_retirement_age: Optional[int] = None,
    annual_living_spend: Optional[float] = None,
    annual_savings: Optional[float] = None,
    inflation_rate: Optional[float] = None,
    ss_claim_age: Optional[int] = None,
    primary_ss_claim_age: Optional[int] = None,
    spouse_ss_claim_age: Optional[int] = None,
    growth_us_equity: Optional[float] = None,
    growth_intl_equity: Optional[float] = None,
    growth_bonds: Optional[float] = None,
    growth_cash: Optional[float] = None,
    growth_private_investments: Optional[float] = None,
    growth_real_estate: Optional[float] = None,
    view_mode: Optional[str] = None,
    spending_guardrail_mode: Optional[str] = None,
    scenario_state: Optional[Dict[str, Any]] = None,
    as_of_year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Pass `scenario_state` to simulate an unsaved, in-memory plan instead of the stored one.
    The projection starts in `as_of_year` (default: the current calendar year).

    Simulates all scenarios simultaneously with independent per-spouse retirement timelines,
    layered cash flows (Living, Gifting, Travel Go-Go curve, Events, Debt Service),
    and SSA Actuarial 100% stacked area longevity survival series.
    """
    state = scenario_state if scenario_state is not None else load_scenario_state(family_id=family_id)
    as_of_year = as_of_year if as_of_year is not None else date.today().year
    events_catalog = {e["id"]: e for e in state.get("events", [])}
    scenarios_list = state.get("scenarios", [])
    active_scen_id = state.get("active_scenario_id", "scen_a")
    equity_companies_list = equity_engine.load_equity_companies_summary(family_id=family_id)

    if equity_growth_preset is None:
        equity_growth_preset = state.get("equity_growth_preset", "moderate")

    if view_mode is None:
        view_mode = state.get("view_mode", "real")

    db_file = resolve_db_path(get_db_path(), family_id=family_id)
    profile_plan = resolve_profile_defaults(family_id=family_id, db_file=db_file, scenarios_list=scenarios_list)
    prof_spending = float(profile_plan.annual_living_spend)
    prof_savings = float(profile_plan.annual_savings)
    prof_ret_age = int(profile_plan.primary_retirement_age)
    prof_inflation = float(profile_plan.inflation_rate)
    prof_primary_ss = profile_plan.primary_ss_claim_age
    prof_spouse_ss = profile_plan.spouse_ss_claim_age

    explicit_flags = {
        "spending": annual_living_spend is not None,
        "savings": annual_savings is not None,
        "primary_ret": (primary_retirement_age is not None) or (retirement_age is not None),
        "spouse_ret": spouse_retirement_age is not None,
        "inflation": inflation_rate is not None,
        "primary_ss": (primary_ss_claim_age is not None) or (ss_claim_age is not None),
        "spouse_ss": spouse_ss_claim_age is not None,
        "guardrails": spending_guardrail_mode is not None,
    }
    if primary_retirement_age is None:
        primary_retirement_age = retirement_age if retirement_age is not None else prof_ret_age
    if spouse_retirement_age is None:
        spouse_retirement_age = primary_retirement_age + 2
    annual_living_spend = annual_living_spend if annual_living_spend is not None else prof_spending
    annual_savings = annual_savings if annual_savings is not None else prof_savings
    inflation_rate = inflation_rate if inflation_rate is not None else prof_inflation
    primary_ss_claim_age = primary_ss_claim_age if primary_ss_claim_age is not None else (ss_claim_age if ss_claim_age is not None else prof_primary_ss)
    spouse_ss_claim_age = spouse_ss_claim_age if spouse_ss_claim_age is not None else prof_spouse_ss

    base_params = {
        "primary_retirement_age": primary_retirement_age,
        "spouse_retirement_age": spouse_retirement_age,
        "annual_living_spend": annual_living_spend,
        "annual_savings": annual_savings,
        "inflation_rate": inflation_rate,
        "primary_ss_claim_age": primary_ss_claim_age,
        "spouse_ss_claim_age": spouse_ss_claim_age,
        "equity_growth_preset": equity_growth_preset,
        "spending_guardrail_mode": spending_guardrail_mode,
        "family_id": family_id,
        "start_year": as_of_year,
    }

    # Resolve Parent-Child Scenario Hierarchy and Cascading Assumptions/Events
    defaults = {
        "primary_retirement_age": prof_ret_age,
        "spouse_retirement_age": prof_ret_age + 2,
        "annual_living_spend": prof_spending,
        "annual_savings": prof_savings,
        "inflation_rate": prof_inflation,
        "primary_ss_claim_age": prof_primary_ss,
        "spouse_ss_claim_age": prof_spouse_ss,
        "ss_claim_age": prof_primary_ss,
        "equity_growth_preset": equity_growth_preset or "moderate",
        "spending_guardrail_mode": "off",
        **DEFAULT_SCENARIO_GROWTH,
    }
    scenarios_list = resolve_scenario_hierarchy(scenarios_list, default_assumptions=defaults)

    base_fin = resolve_orchestrator_baseline_finances(
        family_id=family_id,
        db_file=db_file,
        primary_retirement_age=primary_retirement_age,
        spouse_retirement_age=spouse_retirement_age,
        as_of_year=as_of_year,
    )
    snapshot = base_fin["snapshot"]
    liquid_start = base_fin["liquid_start"]
    retirement_start = base_fin["retirement_start"]
    real_estate_start = base_fin["real_estate_start"]
    mortgage_start = base_fin["mortgage_start"]
    other_start = base_fin["other_start"]
    mortgage_annual_service = base_fin["mortgage_annual_service"]
    w_us, w_intl, w_bonds, w_cash, w_ret_us, w_ret_intl, w_ret_bonds = base_fin["weights"]
    primary_birth_year = base_fin["primary_birth_year"]
    spouse_birth_year = base_fin["spouse_birth_year"]
    current_primary_age = base_fin["current_primary_age"]
    current_spouse_age = base_fin["current_spouse_age"]
    primary_name = base_fin["primary_name"]
    spouse_name = base_fin["spouse_name"]
    children_edu = base_fin["children_edu"]
    milestones = base_fin["milestones"]

    # Company Equity Growth Rate
    if custom_equity_growth_rate is not None:
        equity_annual_growth = custom_equity_growth_rate
    else:
        preset = EQUITY_GROWTH_PRESETS.get(equity_growth_preset, EQUITY_GROWTH_PRESETS["moderate"])
        equity_annual_growth = preset.get("growth_rate", 0.08)

    weights = (w_us, w_intl, w_bonds, w_cash, w_ret_us, w_ret_intl, w_ret_bonds)
    growth_overrides = {
        "us": growth_us_equity,
        "intl": growth_intl_equity,
        "bonds": growth_bonds,
        "cash": growth_cash,
        "private": growth_private_investments,
        "re": growth_real_estate,
    }

    portfolio_weights = resolve_portfolio_weights(snapshot)

    # Run simulations for each scenario
    household_context = build_household_context(family_id=family_id, children_edu=children_edu)
    mortgage_accounts = snapshot.get("categories", {}).get("mortgages", {}).get("accounts", [])
    # An account's own rate wins over the rate entered in Settings (already on the context).
    household_context.mortgage_rate = baseline_mortgage_rate(mortgage_accounts) or household_context.mortgage_rate
    retirement_accounts = snapshot.get("categories", {}).get("retirement", {}).get("accounts", [])
    household_context.pretax_share = pretax_share(retirement_accounts)
    # The household's private-market commitments, read once: each plan only chooses how fast they are called.
    lp_commitments = get_lp_commitments(family_id=family_id)
    # The context is the same for every plan: digest it once and key each plan's run with the digest.
    context_digest = plan_run_cache.run_key({"household_context": household_context})
    scenarios_results = {}
    scorecard = []

    for scen in scenarios_list:
        scen_id = scen["id"]
        scen_event_ids = scen.get("event_ids", [])
        scen_events = [events_catalog[eid] for eid in scen_event_ids if eid in events_catalog]

        p = resolve_scenario_run_params(
            scen=scen,
            target_scenario_id=target_scenario_id,
            explicit_flags=explicit_flags,
            base_params=base_params,
            equity_growth_presets=equity_growth_presets,
            equity_companies_list=equity_companies_list,
            weights=weights,
            growth_overrides=growth_overrides,
            lp_commitments=lp_commitments,
        )
        scen["portfolio_weights"] = dict(portfolio_weights)

        # A plan's run depends only on these arguments, so an earlier run with the same inputs (e.g. before an
        # overlay was switched off and on again) is reused: forecast/plan_run_cache.py.
        sim_kwargs = {
            "events": scen_events,
            "liquid_start": liquid_start,
            "retirement_start": retirement_start,
            "real_estate_start": real_estate_start,
            "mortgage_start": mortgage_start,
            "other_start": other_start,
            "equity_annual_growth": p["scen_equity_annual_growth"],
            **p["plan"].simulation_kwargs(),
            "education_inflation_rate": p["scen_education_inflation"],
            "primary_birth_year": primary_birth_year,
            "spouse_birth_year": spouse_birth_year,
            "view_mode": view_mode,
            "family_id": family_id,
            "mortgage_annual_service": mortgage_annual_service,
            "blended_liquid_growth": p["scen_blended_liquid"],
            "blended_retire_growth": p["scen_blended_retire"],
            "growth_private": p["growth_private"],
            "growth_real_estate": p["growth_re"],
            "company_growth_rates": p["scen_company_growth_rates"],
            "context": household_context,
            "drawdown_order": p["drawdown_order"],
            "lp_call_schedule": p["lp_call_schedule"],
            "accelerate_lp_calls": p["accelerate_lp_calls"],
            "start_year": as_of_year,
        }
        earliest_kwargs = {
            "scen_events": scen_events,
            "liquid_start": liquid_start,
            "retirement_start": retirement_start,
            "real_estate_start": real_estate_start,
            "mortgage_start": mortgage_start,
            "other_start": other_start,
            "scen_equity_annual_growth": p["scen_equity_annual_growth"],
            "current_primary_age": current_primary_age,
            "current_spouse_age": current_spouse_age,
            "scen_spending": p["scen_spending"],
            "scen_savings": p["scen_savings"],
            "inflation_rate": p["scen_inflation"],
            "education_inflation_rate": p["scen_education_inflation"],
            "primary_birth_year": primary_birth_year,
            "spouse_birth_year": spouse_birth_year,
            "view_mode": view_mode,
            "family_id": family_id,
            "scen_primary_ss_claim": p["scen_primary_ss_claim"],
            "scen_spouse_ss_claim": p["scen_spouse_ss_claim"],
            "mortgage_annual_service": mortgage_annual_service,
            "scen_blended_liquid": p["scen_blended_liquid"],
            "scen_blended_retire": p["scen_blended_retire"],
            "growth_private": p["growth_private"],
            "growth_re": p["growth_re"],
            "scen_company_growth_rates": p["scen_company_growth_rates"],
            "household_context": household_context,
            "scen_spouse_ret": p["scen_spouse_ret"],
            "drawdown_order": p["drawdown_order"],
            "lp_call_schedule": p["lp_call_schedule"],
            "accelerate_lp_calls": p["accelerate_lp_calls"],
            "start_year": as_of_year,
        }
        run_key = plan_run_cache.run_key({
            "simulate": {**sim_kwargs, "context": context_digest},
            "earliest": {**earliest_kwargs, "household_context": context_digest},
        })
        run = plan_run_cache.get(run_key)
        if run is None:
            run = {
                "sim_out": run_scenario_simulation(**sim_kwargs),
                "earliest": find_earliest_sustainable_retirement(**earliest_kwargs),
            }
            plan_run_cache.put(run_key, run)
        sim_out = run["sim_out"]
        scenarios_results[scen_id] = sim_out

        bal_65 = next((s["total_net_worth"] for s in sim_out["schedule"] if s.get("age_primary", s.get("age")) == 65), 0.0)
        bal_85 = next((s["total_net_worth"] for s in sim_out["schedule"] if s.get("age_primary", s.get("age")) == 85), 0.0)
        bal_95 = next((s["total_net_worth"] for s in sim_out["schedule"] if s.get("age_primary", s.get("age")) == 95), 0.0)

        earliest_joint_yr, earliest_p_age, earliest_s_age, can_retire_today = run["earliest"]

        ret_readiness, fi_threshold, fi_crossover_yr, fi_achieved = build_retirement_readiness(
            sim_out=sim_out,
            scen_spending=p["scen_spending"],
            primary_birth_year=primary_birth_year,
            spouse_birth_year=spouse_birth_year,
            scen_primary_ret=p["scen_primary_ret"],
            scen_spouse_ret=p["scen_spouse_ret"],
            primary_name=primary_name,
            spouse_name=spouse_name,
            current_primary_age=current_primary_age,
            current_spouse_age=current_spouse_age,
            earliest_joint_yr=earliest_joint_yr,
            earliest_p_age=earliest_p_age,
            earliest_s_age=earliest_s_age,
            can_retire_today=can_retire_today,
            as_of_year=as_of_year,
        )

        scorecard.append(
            build_scenario_scorecard_entry(
                scen=scen,
                scen_events=scen_events,
                scen_primary_ret=p["scen_primary_ret"],
                scen_spouse_ret=p["scen_spouse_ret"],
                primary_birth_year=primary_birth_year,
                spouse_birth_year=spouse_birth_year,
                scen_spending=p["scen_spending"],
                scen_savings=p["scen_savings"],
                scen_inflation=p["scen_inflation"],
                scen_primary_ss_claim=p["scen_primary_ss_claim"],
                scen_spouse_ss_claim=p["scen_spouse_ss_claim"],
                growth_us=p["growth_us"],
                growth_intl=p["growth_intl"],
                growth_bonds_rate=p["growth_bonds_rate"],
                growth_cash_rate=p["growth_cash_rate"],
                growth_private=p["growth_private"],
                growth_re=p["growth_re"],
                scen_blended_liquid=p["scen_blended_liquid"],
                scen_blended_retire=p["scen_blended_retire"],
                ret_readiness=ret_readiness,
                bal_65=bal_65,
                bal_85=bal_85,
                bal_95=bal_95,
                scen_growth_preset=p["scen_growth_preset"],
                scen_holding_presets=p["scen_holding_presets"],
                scen_equity_annual_growth=p["scen_equity_annual_growth"],
                preset_info=p["preset_info"],
                sim_out=sim_out,
                active_scen_id=active_scen_id,
            )
        )


    # Build Comparative Multi-Curve Timeline
    comparison_curves = build_comparison_curves(scenarios_results, scenarios_list)

    # Active Scenario details
    active_result = scenarios_results.get(active_scen_id) or scenarios_results.get("scen_baseline") or list(scenarios_results.values())[0]
    active_readiness = next((s["retirement_readiness"] for s in scorecard if s["id"] == active_scen_id), scorecard[0]["retirement_readiness"] if scorecard else None)

    # Historical Ribbon for continuous timeline (loaded dynamically per family, zero hardcoded PII)
    historical_ribbon, historical_cash_flow_series = load_historical_forecast_actuals(
        family_id=family_id,
        mortgage_annual_service=mortgage_annual_service,
    )

    res = package_simulation_response(
        view_mode=view_mode,
        equity_growth_preset=equity_growth_preset,
        equity_annual_growth=equity_annual_growth,
        primary_retirement_age=primary_retirement_age,
        spouse_retirement_age=spouse_retirement_age,
        primary_name=primary_name,
        spouse_name=spouse_name,
        current_primary_age=current_primary_age,
        current_spouse_age=current_spouse_age,
        annual_living_spend=annual_living_spend,
        annual_savings=annual_savings,
        inflation_rate=inflation_rate,
        primary_ss_claim_age=primary_ss_claim_age,
        spouse_ss_claim_age=spouse_ss_claim_age,
        active_scen_id=active_scen_id,
        active_readiness=active_readiness,
        scorecard=scorecard,
        comparison_curves=comparison_curves,
        milestones=milestones,
        events_catalog=events_catalog,
        scenarios_list=scenarios_list,
        children_edu=children_edu,
        active_result=active_result,
        scenarios_results=scenarios_results,
        historical_ribbon=historical_ribbon,
        historical_cash_flow_series=historical_cash_flow_series,
        equity_companies_list=equity_companies_list,
        w_us=w_us,
        w_intl=w_intl,
        w_bonds=w_bonds,
        w_cash=w_cash,
        mortgage_start=mortgage_start,
        real_estate_start=real_estate_start,
        family_id=family_id,
        prof_spending=prof_spending,
        as_of_year=as_of_year,
    )


    # Adults the forecast pays no Social Security (no earnings and no entered benefit) are named, never silently $0.
    names = {"primary": primary_name, "spouse": spouse_name}
    res["social_security_gaps"] = [
        {"person": who, "name": names[who]}
        for who in adults_without_social_security(household_context, primary_retirement_age, spouse_retirement_age)
    ]

    eval_scen_id = target_scenario_id or active_scen_id
    attach_monte_carlo_solvency(
        res=res,
        family_id=family_id,
        eval_scen_id=eval_scen_id,
        active_scen_id=active_scen_id,
        annual_living_spend=annual_living_spend,
    )

    return res

