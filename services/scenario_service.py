"""
Scenario Studio Simulation, Forecasting, Monte Carlo & Persistence Service.
Encapsulates scenario execution, Monte Carlo stochastic analysis, and profile synchronization.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import config
import forecast_cache
import forecast_engine
from routes.helpers import parse_query_params, sanitize_text
from services.scenario_clone_service import (
    export_forecast_csv,
    resolve_scenario_event_lineage,
    serialize_forecast_csv,
    validate_scenario_hierarchy,
)

logger = logging.getLogger(__name__)

FLOAT_OVERRIDE_FIELDS = (
    "annual_living_spend",
    "annual_savings",
    "inflation_rate",
    "custom_equity_growth_rate",
    "growth_us_equity",
    "growth_intl_equity",
    "growth_bonds",
    "growth_cash",
    "growth_private_investments",
    "growth_real_estate",
)

INT_OVERRIDE_FIELDS = (
    "primary_retirement_age",
    "spouse_retirement_age",
    "ss_claim_age",
    "primary_ss_claim_age",
    "spouse_ss_claim_age",
)


def get_or_compute_scenarios(
    family_id: int,
    universe: str,
    args: Any,
    engine: Any = None,
    cache: Any = None,
) -> dict[str, Any]:
    """Retrieves cached simulation or computes a fresh multi-scenario forecast."""
    eng = engine or forecast_engine
    cch = cache or forecast_cache

    cache_params = {k: v for k, v in args.items() if v not in (None, "", "null", "undefined")}
    cache_key = cch.make_cache_key(family_id, universe, cache_params)
    cached = cch.get_simulation(cache_key)
    if cached:
        return cached

    equity_preset = args.get("equity_growth_preset")
    view_mode = args.get("view_mode")

    params = parse_query_params(args, {
        "primary_retirement_age": int,
        "retirement_age": int,
        "spouse_retirement_age": int,
        "annual_living_spend": float,
        "annual_savings": float,
        "inflation_rate": float,
        "ss_claim_age": int,
        "primary_ss_claim_age": int,
        "spouse_ss_claim_age": int,
        "growth_us_equity": float,
        "growth_intl_equity": float,
        "growth_bonds": float,
        "growth_cash": float,
        "growth_private_investments": float,
        "growth_real_estate": float,
    })
    primary_retire_age = params["primary_retirement_age"] if params["primary_retirement_age"] is not None else params["retirement_age"]

    target_scen_id = args.get("scenario_id") or args.get("target_scenario_id")
    if target_scen_id in (None, "", "null", "undefined"):
        target_scen_id = None

    equity_presets_arg = None
    if args.get("equity_growth_presets"):
        try:
            raw_p = json.loads(args.get("equity_growth_presets"))
            if isinstance(raw_p, dict):
                equity_presets_arg = {str(k): str(v) for k, v in raw_p.items() if v}
        except Exception:
            pass

    res = eng.simulate_multi_scenarios(
        family_id=family_id,
        target_scenario_id=target_scen_id,
        equity_growth_preset=equity_preset,
        equity_growth_presets=equity_presets_arg,
        primary_retirement_age=primary_retire_age,
        spouse_retirement_age=params["spouse_retirement_age"],
        annual_living_spend=params["annual_living_spend"],
        annual_savings=params["annual_savings"],
        inflation_rate=params["inflation_rate"],
        ss_claim_age=params["ss_claim_age"],
        primary_ss_claim_age=params["primary_ss_claim_age"],
        spouse_ss_claim_age=params["spouse_ss_claim_age"],
        growth_us_equity=params["growth_us_equity"],
        growth_intl_equity=params["growth_intl_equity"],
        growth_bonds=params["growth_bonds"],
        growth_cash=params["growth_cash"],
        growth_private_investments=params["growth_private_investments"],
        growth_real_estate=params["growth_real_estate"],
        view_mode=view_mode,
        spending_guardrail_mode=args.get("spending_guardrail_mode"),
    )
    cch.set_simulation(
        cache_key,
        res,
        persist_l2=cch.is_canonical_simulation_params(cache_params),
    )
    return res


def get_or_compute_monte_carlo(
    family_id: int,
    universe: str,
    args: Any,
    engine: Any = None,
    cache: Any = None,
) -> dict[str, Any]:
    """Runs or retrieves cached stochastic Monte Carlo stress testing."""
    eng = engine or forecast_engine
    cch = cache or forecast_cache

    scenario_id = args.get("scenario_id")
    if scenario_id:
        try:
            scenario_id = sanitize_text(scenario_id, max_length=50, field_name="Scenario ID")
        except ValueError:
            scenario_id = None

    mc_parsed = parse_query_params(args, {
        "trials": (int, 1000),
        "spending": float,
        "retirement_age": int,
    })
    trials = max(100, min(5000, mc_parsed["trials"]))
    spending = mc_parsed["spending"]
    ret_age = mc_parsed["retirement_age"]

    mc_params = {
        "scenario_id": scenario_id,
        "trials": trials,
        "spending": spending,
        "retirement_age": ret_age,
    }
    mc_cache_key = cch.make_cache_key(family_id, universe, mc_params)
    cached_mc = cch.get_monte_carlo(mc_cache_key)
    if cached_mc:
        return cached_mc

    persist_l2 = cch.is_canonical_monte_carlo_params(mc_params)

    # Pipeline Reuse: Look up if matching simulation is cached in memory
    precomputed_sim = None
    sim_params = {}
    if scenario_id:
        sim_params["scenario_id"] = scenario_id
    if spending is not None:
        sim_params["annual_living_spend"] = str(spending)
    if ret_age is not None:
        sim_params["primary_retirement_age"] = str(ret_age)

    if sim_params:
        sim_cache_key = cch.make_cache_key(family_id, universe, sim_params)
        precomputed_sim = cch.get_simulation(sim_cache_key)

    if precomputed_sim is None and spending is None and ret_age is None:
        base_cache_key = cch.make_cache_key(family_id, universe, {})
        precomputed_sim = cch.get_simulation(base_cache_key)

    if precomputed_sim and spending is None and ret_age is None and trials == 1000:
        active_mc = precomputed_sim.get("active_monte_carlo")
        req_scen = scenario_id or precomputed_sim.get("active_scenario_id") or "scen_baseline"
        if active_mc and active_mc.get("scenario_id") == req_scen:
            cch.set_monte_carlo(mc_cache_key, active_mc, persist_l2=persist_l2)
            return active_mc

    res = eng.run_monte_carlo_simulation(
        family_id=family_id,
        scenario_id=scenario_id,
        trials=trials,
        custom_spending=spending,
        custom_retirement_age=ret_age,
        precomputed_sim=precomputed_sim,
    )
    cch.set_monte_carlo(mc_cache_key, res, persist_l2=persist_l2)
    return res


def save_scenario(
    family_id: int,
    data: dict[str, Any],
    engine: Any = None,
    cache: Any = None,
    db_module: Any = None,
    db_path: Any = None,
) -> tuple[bool, str | None]:
    """Saves or updates a scenario definition with full inheritance and DAG hierarchy validation."""
    eng = engine or forecast_engine
    cch = cache or forecast_cache

    try:
        scen_id = sanitize_text(data.get("id"), max_length=100, field_name="Scenario id", required=True)
        name = sanitize_text(data.get("name"), max_length=100, field_name="Scenario name", required=True)
        description = sanitize_text(data.get("description", ""), max_length=500, field_name="Scenario description", multiline=True)
        color = sanitize_text(data.get("color", "#1D4ED8"), max_length=20, field_name="Scenario color")
    except ValueError as e:
        return False, str(e)

    state = eng.load_scenario_state(family_id=family_id)
    scenarios = state.get("scenarios", [])

    existing = next((s for s in scenarios if s.get("id") == scen_id), None)
    if existing is None and len(scenarios) >= config.MAX_SCENARIOS:
        return False, f"Maximum of {config.MAX_SCENARIOS} scenarios per household reached."

    if "event_ids" in data and isinstance(data["event_ids"], list) and len(data["event_ids"]) > config.MAX_FORECAST_EVENTS:
        return False, f"Maximum of {config.MAX_FORECAST_EVENTS} forecast events reached."
    if "added_event_ids" in data and isinstance(data["added_event_ids"], list) and len(data["added_event_ids"]) > config.MAX_FORECAST_EVENTS:
        return False, f"Maximum of {config.MAX_FORECAST_EVENTS} forecast events reached."

    if "parent_id" in data:
        parent_id = data.get("parent_id")
        if scen_id == "scen_baseline":
            parent_id = None
    else:
        parent_id = existing.get("parent_id") if existing else None

    if parent_id:
        valid, err = validate_scenario_hierarchy(scen_id, parent_id, scenarios, existing)
        if not valid:
            return False, err

    if existing:
        existing["name"] = name
        existing["description"] = description
        existing["color"] = color
        existing["parent_id"] = parent_id

        if "event_ids" in data:
            curr_ids = list(data.get("event_ids", []))
            existing["event_ids"] = curr_ids
            added, excl = resolve_scenario_event_lineage(data, curr_ids, parent_id, scenarios)
            existing["added_event_ids"] = added
            existing["excluded_event_ids"] = excl
        else:
            if "added_event_ids" in data:
                existing["added_event_ids"] = list(data.get("added_event_ids", []))
            if "excluded_event_ids" in data:
                existing["excluded_event_ids"] = list(data.get("excluded_event_ids", []))

        if "equity_growth_preset" in data:
            val = data.get("equity_growth_preset")
            existing["equity_growth_preset"] = val if val not in (None, "", "inherit") else None
        if "spending_guardrail_mode" in data:
            val = data.get("spending_guardrail_mode")
            existing["spending_guardrail_mode"] = val if val in ("off", "moderate", "aggressive") else None
        if "equity_growth_presets" in data:
            val = data.get("equity_growth_presets")
            if isinstance(val, dict):
                existing["equity_growth_presets"] = {str(k): (str(v) if v not in (None, "", "inherit") else None) for k, v in val.items()}
            elif val in (None, "", "inherit"):
                existing["equity_growth_presets"] = None

        for f in FLOAT_OVERRIDE_FIELDS:
            if f in data:
                val = data[f]
                existing[f] = float(val) if val not in (None, "", "inherit") else None
        for f in INT_OVERRIDE_FIELDS:
            if f in data:
                val = data[f]
                existing[f] = int(val) if val not in (None, "", "inherit") else None
    else:
        equity_preset = data.get("equity_growth_preset")
        if equity_preset in (None, "", "inherit"):
            equity_preset = None if parent_id else "moderate"
        guardrail_mode = data.get("spending_guardrail_mode")
        if guardrail_mode not in ("off", "moderate", "aggressive"):
            guardrail_mode = None if parent_id else "off"
        ev_ids = list(data.get("event_ids", []))
        added, excl = resolve_scenario_event_lineage(data, ev_ids, parent_id, scenarios)
        new_scen = {
            "id": scen_id,
            "name": name,
            "description": description,
            "event_ids": ev_ids,
            "color": color,
            "parent_id": parent_id,
            "equity_growth_preset": equity_preset,
            "spending_guardrail_mode": guardrail_mode,
            "is_baseline": False,
            "added_event_ids": added,
            "excluded_event_ids": excl,
        }
        if "equity_growth_presets" in data and isinstance(data["equity_growth_presets"], dict):
            new_scen["equity_growth_presets"] = {str(k): (str(v) if v not in (None, "", "inherit") else None) for k, v in data["equity_growth_presets"].items()}
        for f in FLOAT_OVERRIDE_FIELDS:
            if f in data and data[f] not in (None, "", "inherit"):
                new_scen[f] = float(data[f])
        for f in INT_OVERRIDE_FIELDS:
            if f in data and data[f] not in (None, "", "inherit"):
                new_scen[f] = int(data[f])
        scenarios.append(new_scen)

    state["scenarios"] = scenarios
    eng.save_scenario_state(state, family_id=family_id)
    cch.invalidate_family_cache(family_id)

    # Synchronize household_profile table if saving baseline plan or active plan
    active_scen_id = state.get("active_scenario_id", "scen_baseline")
    if scen_id in ("scen_baseline", active_scen_id):
        target_s = next((s for s in scenarios if s.get("id") == scen_id), None)
        if target_s and db_module is not None and db_path is not None:
            hp_spend = target_s.get("annual_living_spend")
            hp_savings = target_s.get("annual_savings")
            hp_ret = target_s.get("primary_retirement_age")
            hp_inf = target_s.get("inflation_rate")
            if any(v is not None for v in (hp_spend, hp_savings, hp_ret, hp_inf)):
                try:
                    db_module.families.update_household_metrics(
                        family_id=family_id,
                        annual_spending=hp_spend,
                        annual_savings=hp_savings,
                        retirement_age=hp_ret,
                        inflation_rate=hp_inf,
                        db_path=db_path,
                    )
                except Exception as e:
                    logger.warning("Failed to update household metrics for scenario %s: %s", scen_id, e)

    return True, None


__all__ = [
    "export_forecast_csv",
    "get_or_compute_monte_carlo",
    "get_or_compute_scenarios",
    "save_scenario",
    "serialize_forecast_csv",
]
