"""
Company Equity Exercise Strategies & Scenario Assumption Tools for the AI Financial Advisor.
Provides normalization helpers for multi-strategy equity events (cashless repurchase,
exercise & hold with liquid cash cover, exercise & hold with share sell-to-cover,
and secondary sale of held shares), shared-event catalog isolation, and `update_scenario_assumptions`.
"""

from __future__ import annotations
import copy
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import forecast_engine
from routes.helpers import sanitize_text
from services.advisor.tools_core import _resolve_tool_family_id
from services.scenario_clone_service import pick_unused_scenario_color
from ssr.scenarios import build_ssr_scenarios

logger = logging.getLogger(__name__)


def normalize_equity_action(raw_action: Optional[str]) -> str:
    """Normalizes company equity event action identifiers into canonical strategy keys."""
    act = str(raw_action or "").strip().lower()
    if act in ("exercise_and_hold_cash", "hold_cash_cover", "exercise_hold_cash", "hold_cash"):
        return "exercise_and_hold_cash"
    if act in ("exercise_and_hold_sell_to_cover", "hold_sell_to_cover", "sell_to_cover", "exercise_hold_sell_to_cover"):
        return "exercise_and_hold_sell_to_cover"
    if act in ("sell_held_shares", "sell_owned_shares", "liquidate_held_shares", "secondary_sale", "sell_shares"):
        return "sell_held_shares"
    return "cashless_repurchase"


def normalize_custom_equity_growth_rate(rate: Optional[float]) -> Optional[float]:
    """Normalizes custom equity growth rate (converting percentages like 12.0 to 0.12)."""
    if rate is None:
        return None
    val = float(rate)
    return max(-0.50, min(1.0, round(val / 100.0 if abs(val) > 1.0 else val, 6)))


def apply_scenario_equity_growth_overrides(
    target_scen: Dict[str, Any],
    equity_growth_preset: Optional[str] = None,
    custom_equity_growth_rate: Optional[float] = None,
) -> None:
    """Applies company equity valuation growth preset and/or custom annual growth rate to a scenario."""
    overrides = target_scen.setdefault("overrides", {})
    norm_rate = normalize_custom_equity_growth_rate(custom_equity_growth_rate)
    clean_preset = sanitize_text(equity_growth_preset, 40).lower().strip() if equity_growth_preset else ""

    if clean_preset:
        target_scen["equity_growth_preset"], overrides["equity_growth_preset"] = clean_preset, clean_preset
        target_scen["equity_growth_presets"] = {}
        overrides.pop("equity_growth_presets", None)
        if norm_rate is None and clean_preset != "custom":
            target_scen["custom_equity_growth_rate"] = None
            target_scen.pop("equity_growth_rate", None)
            overrides.pop("custom_equity_growth_rate", None)

    if norm_rate is not None:
        target_scen["custom_equity_growth_rate"], target_scen["equity_growth_rate"] = norm_rate, norm_rate
        overrides["custom_equity_growth_rate"] = norm_rate
        target_scen["equity_growth_presets"] = {}
        overrides.pop("equity_growth_presets", None)
        if not clean_preset:
            preset_by_rate = {0.14: "aggressive", 0.105: "baseline_curve", 0.08: "moderate", 0.05: "conservative", 0.0: "flat"}
            inferred = next((name for r, name in preset_by_rate.items() if abs(norm_rate - r) < 1e-6), "custom")
            target_scen["equity_growth_preset"], overrides["equity_growth_preset"] = inferred, inferred


def resolve_or_clone_child_scenario(
    state: Dict[str, Any], scenarios: List[Dict[str, Any]], target_scen: Dict[str, Any], clean_child_name: str
) -> Dict[str, Any]:
    """Finds an existing child scenario by name or clones a new child scenario from target_scen."""
    existing_child = next((s for s in scenarios if s.get("name", "").strip().lower() == clean_child_name.lower()), None)
    if existing_child:
        state["active_scenario_id"] = existing_child["id"]
        return existing_child

    new_scen_id = f"scen_{uuid.uuid4().hex[:8]}"
    new_scen: Dict[str, Any] = {
        "id": new_scen_id, "name": clean_child_name, "parent_id": target_scen["id"], "is_baseline": False,
        "color": pick_unused_scenario_color(scenarios),
        "retirement_age": target_scen.get("retirement_age", 60),
        "primary_retirement_age": target_scen.get("primary_retirement_age", target_scen.get("retirement_age", 60)),
        "spouse_retirement_age": target_scen.get("spouse_retirement_age", 60),
        "annual_living_spend": target_scen.get("annual_living_spend", 250000.0),
        "annual_savings": target_scen.get("annual_savings", 100000.0),
        "drawdown_order": target_scen.get("drawdown_order", "standard_waterfall"),
        "spending_guardrail_mode": target_scen.get("spending_guardrail_mode", "off"),
        "accelerate_lp_calls": bool(target_scen.get("accelerate_lp_calls", False)),
        "equity_growth_preset": target_scen.get("equity_growth_preset", state.get("equity_growth_preset", "moderate")),
        "custom_equity_growth_rate": target_scen.get("custom_equity_growth_rate"),
        "equity_growth_rate": target_scen.get("equity_growth_rate"),
        "event_ids": list(target_scen.get("event_ids", [])),
        "overrides": copy.deepcopy(target_scen.get("overrides") or {}),
    }
    scenarios.append(new_scen)
    state["active_scenario_id"] = new_scen_id
    return new_scen


def _is_conflicting_equity_event(
    other_ev: Dict[str, Any], ev_id: Optional[str], ev_action: str, ev_grant: Optional[str], is_all_grants: bool
) -> bool:
    """Determines whether another equity event conflicts with `ev`, preserving two-stage hold + later sale pairs."""
    oid = str(other_ev.get("id") or "")
    if not oid or oid == ev_id or other_ev.get("category") not in ("company_equity", "equity"):
        return False
    if oid == "evt_company_equity_exercise_custom" or oid.startswith("evt_equity_"):
        return True
    other_act = normalize_equity_action(other_ev.get("action"))
    hold_actions = ("exercise_and_hold_cash", "exercise_and_hold_sell_to_cover")
    if (ev_action == "sell_held_shares" and other_act in hold_actions) or (
        ev_action in hold_actions and other_act == "sell_held_shares"
    ):
        return False
    return is_all_grants or other_ev.get("grant_id") in (None, "", "all", ev_grant)


def apply_company_equity_event_fields(
    ev: Dict[str, Any], target_scen: Dict[str, Any], events: List[Dict[str, Any]],
    equity_action: Optional[str], grant_id: Optional[str], options_quantity: Optional[float],
    include_wa_tax: Optional[bool], cost_basis_per_share: Optional[float] = None,
) -> None:
    """Populates company_equity strategy fields and removes conflicting inherited equity events."""
    ev["category"], ev["icon"] = "company_equity", "evt-equity"
    ev["action"] = normalize_equity_action(equity_action or ev.get("action") or "cashless_repurchase")
    ev["grant_id"] = None if grant_id in (None, "", "all") else str(grant_id).strip()
    ev["options_quantity"] = float(options_quantity) if options_quantity else None
    ev["include_wa_tax"] = include_wa_tax
    if cost_basis_per_share is not None:
        ev["cost_basis_per_share"] = float(cost_basis_per_share)

    ev_id, ev_act, ev_grant = ev.get("id"), ev["action"], ev["grant_id"]
    is_all_grants = ev_grant in (None, "", "all")
    conflicting_ids = {
        e.get("id") for e in events if _is_conflicting_equity_event(e, ev_id, ev_act, ev_grant, is_all_grants)
    }
    if conflicting_ids:
        target_scen["event_ids"] = [eid for eid in target_scen.get("event_ids", []) if eid not in conflicting_ids]
        if isinstance(target_scen.get("added_event_ids"), list):
            target_scen["added_event_ids"] = [eid for eid in target_scen["added_event_ids"] if eid not in conflicting_ids]
        if target_scen.get("parent_id"):
            exc = target_scen.setdefault("excluded_event_ids", [])
            for cid in conflicting_ids:
                if cid not in exc:
                    exc.append(cid)


def extract_scenario_metrics(ssr: Dict[str, Any], sid: str) -> Dict[str, Any]:
    """Extracts net worth, solvency, and FI crossover metrics for a scenario from SSR output."""
    r = next((row for row in ssr.get("scorecard_rows", []) if row.get("id") == sid or row.get("scenario_id") == sid), None)
    return {
        "nw_age_65": (r.get("nw65_str") if r else None) or ssr.get("nw_65") or ssr.get("val_nw65", "--"),
        "nw_age_85": (r.get("nw85_str") if r else None) or ssr.get("nw_85") or ssr.get("val_nw85", "--"),
        "nw_age_95": (r.get("nw95_str") if r else None) or ssr.get("nw_95") or ssr.get("val_nw95", "--"),
        "solvency": (r.get("solv_text") if r else None) or ssr.get("solv_rate_display") or ssr.get("plan_solv_text", "--"),
        "fi_crossover_year": ssr.get("fi_crossover_year", "--"),
    }


def persist_or_simulate_scenario_state(
    fam_id: int, state: Dict[str, Any], target_scen_id: str, is_read_only: bool
) -> Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
    """Saves scenario state (or temporarily mocks state in read-only mode) and builds SSR output."""
    if not is_read_only:
        forecast_engine.save_scenario_state(state, family_id=fam_id)
        try:
            import forecast_cache
            forecast_cache.invalidate_family_cache(fam_id, domains=["scenarios"])
        except Exception:
            pass
        ssr_after, raw_after = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen_id)
        return "saved", ssr_after, raw_after

    orig_load = forecast_engine.load_scenario_state
    try:
        import forecast.orchestrator
        forecast_engine.load_scenario_state = lambda family_id=0: state
        forecast.orchestrator.load_scenario_state = lambda family_id=0: state
        ssr_after, raw_after = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen_id)
    finally:
        forecast_engine.load_scenario_state = orig_load
        forecast.orchestrator.load_scenario_state = orig_load
    return "simulated_only", ssr_after, raw_after


def update_scenario_assumptions(
    scenario_name: Optional[str] = None, scenario_id: Optional[str] = None,
    create_child_scenario_name: Optional[str] = None, equity_growth_preset: Optional[str] = None,
    custom_equity_growth_rate: Optional[float] = None, retirement_age: Optional[int] = None,
    spouse_retirement_age: Optional[int] = None, annual_living_spend: Optional[float] = None,
    annual_savings: Optional[float] = None, drawdown_order: Optional[str] = None,
    spending_guardrail_mode: Optional[str] = None, accelerate_lp_calls: Optional[bool] = None,
    delete_scenario: bool = False, delete_all_child_scenarios: bool = False, family_id: int = 0,
) -> Dict[str, Any]:
    """Updates (or clones/deletes) a scenario's assumptions and private company equity FMV growth rate."""
    from services.advisor.tools_scenarios import _resolve_scenario

    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {"error": "Unauthenticated session", "status": "unavailable"}

    clean_scen_name, clean_child_name = sanitize_text(scenario_name, 100), sanitize_text(create_child_scenario_name, 100)
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
            is_demo = False

        if delete_all_child_scenarios:
            non_base = [s for s in scenarios if not s.get("is_baseline") and s.get("id") not in ("baseline", "scen_baseline")]
            deleted_names = [s.get("name", s.get("id", "")) for s in non_base]
            kept = [s for s in scenarios if s.get("is_baseline") or s.get("id") in ("baseline", "scen_baseline")]
            state["scenarios"] = kept or scenarios[:1]
            state["active_scenario_id"] = "scen_baseline"
            kept_eids = {eid for s in state["scenarios"] for eid in (s.get("event_ids") or [])}
            state["events"] = [
                e for e in state.get("events", [])
                if e.get("id") in kept_eids or e.get("id") == "evt_company_equity_exercise_custom"
                or str(e.get("id") or "").startswith(("evt_k12_", "evt_college_", "evt_equity_"))
            ]
            if not is_demo:
                forecast_engine.save_scenario_state(state, family_id=fam_id)
                try:
                    import forecast_cache
                    forecast_cache.invalidate_family_cache(fam_id, domains=["scenarios"])
                except Exception:
                    pass
            return {
                "status": "deleted_all_children" if not is_demo else "simulated_only",
                "deleted_count": len(deleted_names), "deleted_scenario_names": deleted_names,
            }

        target_scen = _resolve_scenario(scenarios, scenario_id=scenario_id, scenario_name=clean_scen_name)
        if not target_scen:
            active_id = "scen_baseline" if clean_child_name else (state.get("active_scenario_id") or "scen_baseline")
            target_scen = next((s for s in scenarios if s.get("id") == active_id or (clean_child_name and s.get("is_baseline"))), scenarios[0])

        if delete_scenario:
            if target_scen.get("is_baseline") or target_scen.get("id") in ("baseline", "scen_baseline"):
                return {"error": "Cannot delete the Baseline scenario", "status": "forbidden"}
            del_id, del_name = target_scen["id"], target_scen.get("name", "")
            state["scenarios"] = [s for s in scenarios if s.get("id") != del_id]
            if state.get("active_scenario_id") == del_id:
                state["active_scenario_id"] = "scen_baseline"
            if not is_demo:
                forecast_engine.save_scenario_state(state, family_id=fam_id)
            return {"status": "deleted" if not is_demo else "simulated_only", "deleted_scenario_id": del_id, "deleted_scenario_name": del_name}

        ssr_before, _ = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen["id"])
        before_m = extract_scenario_metrics(ssr_before, target_scen["id"])
        if clean_child_name:
            target_scen = resolve_or_clone_child_scenario(state, scenarios, target_scen, clean_child_name)

        overrides = target_scen.setdefault("overrides", {})
        apply_scenario_equity_growth_overrides(target_scen, equity_growth_preset, custom_equity_growth_rate)
        if retirement_age is not None:
            target_scen["retirement_age"], target_scen["primary_retirement_age"] = int(retirement_age), int(retirement_age)
            overrides["primary_retirement_age"] = int(retirement_age)
        if spouse_retirement_age is not None:
            target_scen["spouse_retirement_age"], overrides["spouse_retirement_age"] = int(spouse_retirement_age), int(spouse_retirement_age)
        if annual_living_spend is not None:
            target_scen["annual_living_spend"], overrides["annual_living_spend"] = float(annual_living_spend), float(annual_living_spend)
        if annual_savings is not None:
            target_scen["annual_savings"], overrides["annual_savings"] = float(annual_savings), float(annual_savings)
        if drawdown_order is not None:
            target_scen["drawdown_order"] = sanitize_text(drawdown_order, 40).lower().strip()
        if spending_guardrail_mode is not None:
            gm = sanitize_text(spending_guardrail_mode, 40).lower().strip()
            target_scen["spending_guardrail_mode"], overrides["spending_guardrail_mode"] = gm, gm
        if accelerate_lp_calls is not None:
            target_scen["accelerate_lp_calls"] = bool(accelerate_lp_calls)

        status, ssr_after, _ = persist_or_simulate_scenario_state(fam_id, state, target_scen["id"], is_demo)
        after_m = extract_scenario_metrics(ssr_after, target_scen["id"])
        return {
            "status": status, "scenario_id": target_scen["id"], "scenario_name": target_scen.get("name", ""),
            "assumptions": {
                "retirement_age": target_scen.get("retirement_age") or target_scen.get("primary_retirement_age"),
                "spouse_retirement_age": target_scen.get("spouse_retirement_age"),
                "annual_living_spend": target_scen.get("annual_living_spend"), "annual_savings": target_scen.get("annual_savings"),
                "equity_growth_preset": target_scen.get("equity_growth_preset"),
                "custom_equity_growth_rate": target_scen.get("custom_equity_growth_rate"),
            },
            "before_metrics": before_m, "after_metrics": after_m,
        }
    except Exception as e:
        logger.warning("Error updating scenario assumptions for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}
