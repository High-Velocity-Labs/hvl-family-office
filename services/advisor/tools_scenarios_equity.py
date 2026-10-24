"""
Company Equity Exercise Strategies & Scenario Assumption Tools for the AI Financial Advisor.
Provides normalization helpers for multi-strategy equity events (cashless repurchase,
exercise & hold with liquid cash cover, exercise & hold with share sell-to-cover,
and secondary sale of held shares), shared-event catalog isolation, and `update_scenario_assumptions`.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

import forecast_engine
from routes.helpers import sanitize_text
from services.advisor.tools_core import _resolve_tool_family_id
from services.advisor.tools_scenarios_helpers import (
    _BENCHMARK_YEARS,
    _INHERITABLE_SCENARIO_KEYS,
    _STATE_CODES,
    _exclude_conflicting_events,
    _resolve_state_code,
    apply_scenario_equity_growth_overrides,
    build_key_years_schedule,
    default_company_equity_event_name,
    extract_scenario_metrics,
    normalize_custom_equity_growth_rate,
    normalize_equity_action,
    persist_or_simulate_scenario_state,
    reset_child_scenarios_to_baseline,
    resolve_or_clone_child_scenario,
)
from ssr.scenarios import build_ssr_scenarios

logger = logging.getLogger(__name__)


def _is_conflicting_equity_event(
    other_ev: Dict[str, Any],
    ev_id: Optional[str],
    ev_action: str,
    ev_grant: Optional[str],
    is_all_grants: bool,
) -> bool:
    """Determines whether another equity event conflicts with `ev`, preserving two-stage hold + later sale pairs."""
    oid = str(other_ev.get("id") or "")
    if not oid or oid == ev_id or other_ev.get("category") not in ("company_equity", "equity"):
        return False
    if oid == "evt_company_equity_exercise_custom" or oid.startswith("evt_equity_"):
        return True
    other_act = normalize_equity_action(other_ev.get("action"))
    hold_acts = ("exercise_and_hold_cash", "exercise_and_hold_sell_to_cover")
    if (ev_action == "sell_held_shares" and other_act in hold_acts) or (ev_action in hold_acts and other_act == "sell_held_shares"):
        return False
    return is_all_grants or other_ev.get("grant_id") in (None, "", "all", ev_grant)


def apply_company_equity_event_fields(
    ev: Dict[str, Any],
    target_scen: Dict[str, Any],
    events: List[Dict[str, Any]],
    equity_action: Optional[str],
    grant_id: Optional[str],
    options_quantity: Optional[float],
    include_wa_tax: Optional[bool],
    cost_basis_per_share: Optional[float] = None,
) -> None:
    """Populates company_equity strategy fields and removes conflicting inherited equity events."""
    ev["category"] = "company_equity"
    ev["icon"] = "evt-equity"
    ev["action"] = normalize_equity_action(equity_action or ev.get("action") or "cashless_repurchase")
    ev["grant_id"] = None if grant_id in (None, "", "all") else str(grant_id).strip()
    ev["options_quantity"] = float(options_quantity) if options_quantity else None
    ev["include_wa_tax"] = include_wa_tax
    if cost_basis_per_share is not None:
        ev["cost_basis_per_share"] = float(cost_basis_per_share)
    is_all = ev["grant_id"] in (None, "", "all")
    conflicting = {
        e.get("id")
        for e in events
        if _is_conflicting_equity_event(e, ev.get("id"), ev["action"], ev["grant_id"], is_all)
    }
    _exclude_conflicting_events(target_scen, conflicting)


def apply_relocation_and_gifting_fields(
    ev: Dict[str, Any],
    target_scen: Dict[str, Any],
    events: List[Dict[str, Any]],
    clean_cat: str,
    s_yr: int,
    e_yr: int,
    amt: float,
    origin_state: Optional[str],
    target_state: Optional[str],
    clean_name: str,
    clean_desc: str,
) -> None:
    """Populates state_relocation or gifting event fields and excludes conflicting inherited catalog events."""
    ev_id = ev.get("id")
    if clean_cat == "state_relocation":
        orig_st = _resolve_state_code(origin_state, "", str(ev.get("origin_state") or "WA"))
        targ_st = _resolve_state_code(target_state, f"{clean_name} {clean_desc}", str(ev.get("target_state") or "NV"))
        move_cost = float(amt) if amt > 0 else float(ev.get("moving_cost") or 35000.0)
        ev.update({
            "category": "state_relocation", "icon": "evt-relocation", "event_type": "point",
            "origin_state": orig_st, "target_state": targ_st, "moving_cost": move_cost,
            "amount": move_cost, "annual_amount": move_cost, "year": s_yr, "start_year": s_yr, "end_year": s_yr,
        })
        if orig_st == "WA":
            ev["state_tax_savings_rate"] = 0.0
        if not clean_name:
            ev["name"] = f"State Domicile Relocation ({orig_st} → {targ_st}, {s_yr})"
        conflicting_reloc = (
            {e.get("id") for e in events if e.get("id") != ev_id and e.get("category") == "state_relocation"}
            | {"evt_state_relocation"}
        ) - {ev_id}
        _exclude_conflicting_events(target_scen, conflicting_reloc)
        if ev in events:
            events.remove(ev)
            events.insert(0, ev)
    elif clean_cat in ("gifting", "gifting_throughline"):
        ev.update({
            "category": "gifting", "icon": "evt-gifting", "event_type": "duration",
            "year": s_yr, "start_year": s_yr, "end_year": e_yr, "funding_source": "cash_flow",
        })
        if not clean_name:
            ev["name"] = f"Annual Family Gifting Program (${int(amt / 1000)}k/yr)" if amt >= 1000 else "Annual Family Gifting Program"
        conflicting_gift = (
            {e.get("id") for e in events if e.get("id") != ev_id and e.get("category") in ("gifting", "gifting_throughline")}
            | {"evt_family_gifting"}
        ) - {ev_id}
        _exclude_conflicting_events(target_scen, conflicting_gift)


def update_scenario_assumptions(
    scenario_name: Optional[str] = None,
    scenario_id: Optional[str] = None,
    create_child_scenario_name: Optional[str] = None,
    equity_growth_preset: Optional[str] = None,
    custom_equity_growth_rate: Optional[float] = None,
    retirement_age: Optional[int] = None,
    spouse_retirement_age: Optional[int] = None,
    annual_living_spend: Optional[float] = None,
    annual_savings: Optional[float] = None,
    drawdown_order: Optional[str] = None,
    spending_guardrail_mode: Optional[str] = None,
    accelerate_lp_calls: Optional[bool] = None,
    delete_scenario: bool = False,
    delete_all_child_scenarios: bool = False,
    family_id: int = 0,
) -> Dict[str, Any]:
    """Updates (or clones/deletes) a scenario's assumptions and private company equity FMV growth rate."""
    from services.advisor.tools_scenarios import _resolve_scenario

    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {"error": "Unauthenticated session", "status": "unavailable"}

    clean_scen_name = sanitize_text(scenario_name, 100)
    clean_child_name = sanitize_text(create_child_scenario_name, 100)
    try:
        state = copy.deepcopy(forecast_engine.load_scenario_state(family_id=fam_id))
        scenarios = state.get("scenarios", [])
        if not scenarios:
            return {"error": "No scenarios found in household", "status": "unavailable"}

        is_demo = False
        try:
            from services.advisor.chat_service import is_advisor_demo_session

            is_demo = is_advisor_demo_session()
        except Exception:
            pass

        if delete_all_child_scenarios:
            deleted_names = reset_child_scenarios_to_baseline(state, scenarios)
            _, _, raw_base = persist_or_simulate_scenario_state(fam_id, state, "scen_baseline", is_demo)
            return {
                "status": "deleted_all_children" if not is_demo else "simulated_only",
                "deleted_count": len(deleted_names),
                "deleted_scenario_names": deleted_names,
                "key_years_schedule": build_key_years_schedule(raw_base, "scen_baseline"),
            }

        target_scen = _resolve_scenario(scenarios, scenario_id=scenario_id, scenario_name=clean_scen_name)
        if not target_scen and clean_scen_name and not clean_child_name and not delete_scenario:
            clean_child_name = clean_scen_name
        if not target_scen:
            active_id = "scen_baseline" if clean_child_name else (state.get("active_scenario_id") or "scen_baseline")
            target_scen = next(
                (s for s in scenarios if s.get("id") == active_id or (clean_child_name and s.get("is_baseline"))),
                scenarios[0],
            )

        if delete_scenario:
            if target_scen.get("is_baseline") or target_scen.get("id") in ("baseline", "scen_baseline"):
                return {"error": "Cannot delete the Baseline scenario", "status": "forbidden"}
            del_id, del_name = target_scen["id"], target_scen.get("name", "")
            state["scenarios"] = [s for s in scenarios if s.get("id") != del_id]
            if state.get("active_scenario_id") == del_id:
                state["active_scenario_id"] = "scen_baseline"
            if not is_demo:
                forecast_engine.save_scenario_state(state, family_id=fam_id)
            return {
                "status": "deleted" if not is_demo else "simulated_only",
                "deleted_scenario_id": del_id,
                "deleted_scenario_name": del_name,
            }

        ssr_before, _ = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen["id"])
        before_m = extract_scenario_metrics(ssr_before, target_scen["id"])
        if clean_child_name:
            target_scen = resolve_or_clone_child_scenario(state, scenarios, target_scen, clean_child_name)

        overrides = target_scen.setdefault("overrides", {})
        apply_scenario_equity_growth_overrides(target_scen, equity_growth_preset, custom_equity_growth_rate)
        if retirement_age is not None:
            ret_val = int(retirement_age)
            target_scen["retirement_age"] = ret_val
            target_scen["primary_retirement_age"] = ret_val
            overrides["primary_retirement_age"] = ret_val
        for key, val, cast in (
            ("spouse_retirement_age", spouse_retirement_age, int),
            ("annual_living_spend", annual_living_spend, float),
            ("annual_savings", annual_savings, float),
        ):
            if val is not None:
                target_scen[key] = cast(val)
                overrides[key] = cast(val)
        if drawdown_order is not None:
            target_scen["drawdown_order"] = sanitize_text(drawdown_order, 40).lower().strip()
        if spending_guardrail_mode is not None:
            gm = sanitize_text(spending_guardrail_mode, 40).lower().strip()
            target_scen["spending_guardrail_mode"] = gm
            overrides["spending_guardrail_mode"] = gm
        if accelerate_lp_calls is not None:
            target_scen["accelerate_lp_calls"] = bool(accelerate_lp_calls)

        status, ssr_after, raw_after = persist_or_simulate_scenario_state(fam_id, state, target_scen["id"], is_demo)
        return {
            "status": status,
            "scenario_id": target_scen["id"],
            "scenario_name": target_scen.get("name", ""),
            "assumptions": {
                "retirement_age": target_scen.get("retirement_age") or target_scen.get("primary_retirement_age"),
                "spouse_retirement_age": target_scen.get("spouse_retirement_age"),
                "annual_living_spend": target_scen.get("annual_living_spend"),
                "annual_savings": target_scen.get("annual_savings"),
                "equity_growth_preset": target_scen.get("equity_growth_preset"),
                "custom_equity_growth_rate": target_scen.get("custom_equity_growth_rate"),
            },
            "before_metrics": before_m,
            "after_metrics": extract_scenario_metrics(ssr_after, target_scen["id"]),
            "key_years_schedule": build_key_years_schedule(raw_after, target_scen["id"]),
        }
    except Exception as e:
        logger.warning("Error updating scenario assumptions for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


__all__ = [
    "_BENCHMARK_YEARS",
    "_INHERITABLE_SCENARIO_KEYS",
    "_STATE_CODES",
    "_exclude_conflicting_events",
    "_is_conflicting_equity_event",
    "_resolve_state_code",
    "apply_company_equity_event_fields",
    "apply_relocation_and_gifting_fields",
    "apply_scenario_equity_growth_overrides",
    "build_key_years_schedule",
    "default_company_equity_event_name",
    "extract_scenario_metrics",
    "normalize_custom_equity_growth_rate",
    "normalize_equity_action",
    "persist_or_simulate_scenario_state",
    "resolve_or_clone_child_scenario",
    "update_scenario_assumptions",
]
