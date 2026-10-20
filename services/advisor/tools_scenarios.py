"""
Scenarios and Life Events callable tools for the AI Financial Advisor:
Multi-Scenario Lookup by Name, Full Per-Scenario Event Visibility,
and Scenario Life Event Management (add, update, enable, disable, delete).
"""

from __future__ import annotations
import copy
import logging
import uuid
from typing import Any, Dict, List, Optional

import config
import forecast_engine
from routes.helpers import sanitize_text
from services.advisor.tools_core import _format_historical_backtest_summary, _resolve_tool_family_id
from ssr.scenarios import build_ssr_scenarios

logger = logging.getLogger(__name__)

_EVENT_CATEGORY_ICONS: Dict[str, str] = {
    "lifestyle": "evt-travel", "capital_outflow": "evt-capital-outflow", "capital_inflow": "evt-capital-inflow",
    "sabbatical": "evt-sabbatical", "roth_conversion": "evt-roth-ladder", "real_estate": "evt-real-estate",
    "home_renovation": "evt-real-estate", "college": "evt-tuition", "grad_school": "evt-tuition",
    "education": "evt-tuition", "eldercare": "evt-lifestyle", "gifting": "evt-gift",
    "philanthropy_daf": "evt-charity", "state_relocation": "evt-relocation", "debt_payoff": "evt-debt",
    "refinance": "evt-refi", "superfund_529": "evt-529", "pe_capital_call": "evt-capital-call",
}


def _resolve_scenario(
    scenarios: List[Dict[str, Any]], scenario_id: Optional[str] = None, scenario_name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Resolves target scenario by exact id, exact name (case-insensitive), or substring."""
    target = (scenario_name or scenario_id or "").strip()
    if not target:
        return None
    target_lower = target.lower()
    for s in scenarios:
        if s.get("id") == target or s.get("name", "").strip().lower() == target_lower:
            return s
    for s in scenarios:
        s_name = s.get("name", "").strip().lower()
        if target_lower in s_name or s_name in target_lower:
            return s
    return None


def enrich_scenarios_and_events_payload(
    family_id: int = 0, scenario_id: Optional[str] = None, scenario_name: Optional[str] = None
) -> Dict[str, Any]:
    """Enriches scenario forecast data with full multi-scenario lookup by name, per-scenario events, and catalog."""
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        raw_state = forecast_engine.load_scenario_state(family_id=fam_id)
        scenarios_list, events_list = raw_state.get("scenarios", []), raw_state.get("events", [])
        target_scen = _resolve_scenario(scenarios_list, scenario_id=scenario_id, scenario_name=scenario_name)
        resolved_id = target_scen["id"] if target_scen else scenario_id

        ssr_scen, raw_sim = build_ssr_scenarios(family_id=fam_id, scenario_id=resolved_id)
        if not ssr_scen and not raw_sim:
            return {}

        sched = (raw_sim or {}).get("active_schedule") or []
        milestone_years = [
            {"year": r.get("year"), "primary_age": r.get("primary_age"), "spouse_age": r.get("spouse_age"),
             "net_worth": r.get("net_worth"), "liquid_portfolio": r.get("liquid_portfolio"),
             "gross_income": r.get("gross_income"), "living_expenses": r.get("living_expenses"),
             "taxes_paid": r.get("total_tax"), "net_cash_flow": r.get("net_cash_flow")}
            for idx, r in enumerate(sched)
            if idx in (0, len(sched) - 1) or int(r.get("primary_age") or 0) in (50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100)
        ]

        hist_summary: Dict[str, Any] = {}
        active_mc = (raw_sim or {}).get("active_monte_carlo")
        if active_mc and (active_mc.get("historical_cohorts") or active_mc.get("historical_backtest")):
            hist_summary = _format_historical_backtest_summary(active_mc.get("historical_cohorts") or active_mc.get("historical_backtest"))
        if not hist_summary:
            try:
                mc_res = forecast_engine.run_monte_carlo_simulation(family_id=fam_id, trials=100)
                if mc_res and (mc_res.get("historical_cohorts") or mc_res.get("historical_backtest")):
                    hist_summary = _format_historical_backtest_summary(mc_res.get("historical_cohorts") or mc_res.get("historical_backtest"))
            except Exception:
                pass

        scorecard_map = {r.get("id"): r for r in (ssr_scen.get("scorecard_rows") or [])}
        selected_scen_id = ssr_scen.get("selected_scenario_id") or resolved_id
        scenarios_by_name: Dict[str, Dict[str, Any]] = {}
        for s in scenarios_list:
            s_id, s_name = s.get("id"), s.get("name", "Scenario")
            s_card = scorecard_map.get(s_id, {})
            sc_event_ids = set(s.get("event_ids", []))
            scenarios_by_name[s_name] = {
                "scenario_id": s_id, "name": s_name, "is_baseline": bool(s.get("is_baseline", False)),
                "parent_id": s.get("parent_id"), "is_selected": (s_id == selected_scen_id),
                "assumptions": {
                    "retirement_age": s.get("retirement_age"), "spouse_retirement_age": s.get("spouse_retirement_age"),
                    "annual_living_spend": s.get("annual_living_spend"), "annual_savings": s.get("annual_savings"),
                    "drawdown_order": s.get("drawdown_order", "standard_waterfall"),
                    "spending_guardrail_mode": s.get("spending_guardrail_mode", "off"),
                    "accelerate_lp_calls": bool(s.get("accelerate_lp_calls", False)),
                },
                "metrics": {"nw_65": s_card.get("nw65_str", "--"), "nw_85": s_card.get("nw85_str", "--"),
                            "nw_95": s_card.get("nw95_str", "--"), "solvency": s_card.get("solv_text", "--")},
                "enabled_events": [dict(ev) for ev in events_list if ev.get("id") in sc_event_ids],
            }

        all_household_events = []
        for ev in events_list:
            ev_dict = dict(ev)
            ev_dict["enabled_in_scenario_names"] = [s.get("name", "") for s in scenarios_list if ev.get("id") in s.get("event_ids", [])]
            all_household_events.append(ev_dict)

        return {
            "active_plan_name": ssr_scen.get("plan_name", "Baseline Plan"), "selected_scenario_id": selected_scen_id,
            "view_mode": ssr_scen.get("view_mode", "real"), "net_worth_age_65": ssr_scen.get("nw_65"),
            "net_worth_age_85": ssr_scen.get("nw_85"), "net_worth_age_95": ssr_scen.get("nw_95"),
            "solvency_status": ssr_scen.get("solv_rate_display"), "solvency_detail": ssr_scen.get("solv_sub"),
            "primary_retirement_target": ssr_scen.get("val_primary_ret"), "spouse_retirement_target": ssr_scen.get("val_spouse_ret"),
            "fi_achieved": ssr_scen.get("fi_achieved", False), "fi_crossover_year": ssr_scen.get("fi_crossover_year"),
            "fi_threshold": ssr_scen.get("fi_threshold"),
            "assumptions": {
                "annual_living_spend": ssr_scen.get("living_spend_str"), "annual_savings": ssr_scen.get("annual_savings_str"),
                "inflation_rate": ssr_scen.get("inflation_pct_str"), "primary_ss_claim_age": ssr_scen.get("primary_ss_claim_age"),
                "spouse_ss_claim_age": ssr_scen.get("spouse_ss_claim_age"), "blended_liquid_growth": ssr_scen.get("blended_liquid_pct"),
                "spending_guardrail_mode": ssr_scen.get("spending_guardrail_mode", "off"),
                "guardrails_badge_label": ssr_scen.get("guardrails_badge_label", "Off"),
            },
            "historical_backtest_summary": hist_summary, "historical_backtest": hist_summary,
            "scenarios_scorecard": [
                {"scenario_id": r.get("id"), "name": r.get("name"), "is_selected": r.get("is_selected", False),
                 "retirement_ages": r.get("ret_ages_str"), "annual_spend": r.get("spend_str"), "events_summary": r.get("events_summary"),
                 "nw_65": r.get("nw65_str"), "nw_85": r.get("nw85_str"), "nw_95": r.get("nw95_str"), "solvency": r.get("solv_text")}
                for r in (ssr_scen.get("scorecard_rows") or [])
            ],
            "active_life_events": [
                {"name": ev.get("name"), "year": ev.get("year_str"), "amount": ev.get("amount_str"),
                 "category": ev.get("type_label"), "enabled_in_active_plan": ev.get("is_checked", True)}
                for ev in (ssr_scen.get("event_rows") or [])
            ],
            "milestone_schedule": milestone_years, "scenarios_by_name": scenarios_by_name,
            "all_household_events_catalog": all_household_events,
        }
    except Exception as e:
        logger.warning("Error loading scenarios and forecast plan for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def manage_scenario_life_event(
    action: str = "upsert",
    event_name: str = "",
    category: str = "lifestyle",
    start_year: int = 2027,
    end_year: Optional[int] = None,
    amount: float = 0.0,
    is_outflow: bool = True,
    description: str = "",
    scenario_name: Optional[str] = None,
    scenario_id: Optional[str] = None,
    create_child_scenario_name: Optional[str] = None,
    event_id: Optional[str] = None,
    roth_strategy_preset: Optional[str] = None,
    family_id: int = 0,
) -> Dict[str, Any]:
    """
    Creates, modifies, enables/disables, or deletes a life event on a household forecast scenario
    (or clones a new child scenario for the event), persists the change (when not in demo/viewer mode),
    and returns the exact Before vs. After multi-year financial impact (Net Worth at 65/85/95,
    FI crossover year, Monte Carlo solvency, and cash-flow impact during the event years,
    including interaction with other scheduled events like vacations, sabbaticals, or tuition).

    Supported `action` values:
      - 'upsert': Adds a new life event or modifies an existing event matched by event_id or event_name.
      - 'enable': Enables an existing life event on the target scenario.
      - 'disable': Removes an existing life event from the target scenario's active schedule.
      - 'delete': Permanently removes a life event from the household catalog and all scenarios.
      - 'simulate_only': Simulates before/after multi-year impact without saving changes to disk.

    Supported `category` values:
      'lifestyle' (personal assistant, nanny, staff, travel), 'capital_outflow', 'capital_inflow',
      'sabbatical', 'roth_conversion' (supports roth_strategy_preset: 'auto_bracket_24', 'auto_bracket_22', 'rule_72t_sepp'),
      'real_estate', 'home_renovation', 'college', 'grad_school', 'education', 'eldercare', 'gifting',
      'philanthropy_daf', 'state_relocation', 'debt_payoff', 'refinance', 'superfund_529', 'pe_capital_call'.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {"error": "Unauthenticated session", "status": "unavailable"}

    clean_name, clean_desc = sanitize_text(event_name, 100), sanitize_text(description, 500)
    clean_cat = sanitize_text(category, 50).lower().strip() or "lifestyle"
    clean_scen_name, clean_child_name = sanitize_text(scenario_name, 100), sanitize_text(create_child_scenario_name, 100)
    act = (action or "upsert").lower().strip()

    try:
        raw_state = forecast_engine.load_scenario_state(family_id=fam_id)
        state = copy.deepcopy(raw_state)
        scenarios = state.get("scenarios", [])
        if not scenarios:
            return {"error": "No scenarios found in household", "status": "unavailable"}

        target_scen = _resolve_scenario(scenarios, scenario_id=scenario_id, scenario_name=clean_scen_name)
        if not target_scen:
            active_id = state.get("active_scenario_id") or "scen_baseline"
            target_scen = next((s for s in scenarios if s.get("id") == active_id), scenarios[0])

        ssr_before, raw_before = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen["id"])
        is_demo = False
        try:
            from services.advisor.chat_service import is_advisor_demo_session
            is_demo = is_advisor_demo_session()
        except Exception:
            is_demo = False
        is_read_only = is_demo or (act == "simulate_only")

        if clean_child_name:
            existing_child = next((s for s in scenarios if s.get("name", "").strip().lower() == clean_child_name.lower()), None)
            if existing_child:
                target_scen = existing_child
            else:
                new_scen_id = f"scen_{uuid.uuid4().hex[:8]}"
                new_scen = {
                    "id": new_scen_id, "name": clean_child_name, "parent_id": target_scen["id"], "is_baseline": False,
                    "retirement_age": target_scen.get("retirement_age", 60), "spouse_retirement_age": target_scen.get("spouse_retirement_age", 60),
                    "annual_living_spend": target_scen.get("annual_living_spend", 250000.0), "annual_savings": target_scen.get("annual_savings", 100000.0),
                    "drawdown_order": target_scen.get("drawdown_order", "standard_waterfall"),
                    "spending_guardrail_mode": target_scen.get("spending_guardrail_mode", "off"),
                    "accelerate_lp_calls": bool(target_scen.get("accelerate_lp_calls", False)),
                    "event_ids": list(target_scen.get("event_ids", [])),
                }
                scenarios.append(new_scen)
                state["active_scenario_id"] = new_scen_id
                target_scen = new_scen

        events = state.setdefault("events", [])
        matched_event: Optional[Dict[str, Any]] = None
        if event_id:
            matched_event = next((e for e in events if e.get("id") == event_id), None)
        if not matched_event and clean_name:
            c_lower = clean_name.lower()
            matched_event = next((e for e in events if e.get("name", "").strip().lower() == c_lower), None)
            if not matched_event:
                matched_event = next((e for e in events if c_lower in e.get("name", "").strip().lower() or e.get("name", "").strip().lower() in c_lower), None)

        s_yr, e_yr = int(start_year or 2027), int(end_year if end_year is not None else (start_year or 2027))
        if e_yr < s_yr:
            e_yr = s_yr
        amt = float(amount or 0.0)
        target_event_ids = target_scen.setdefault("event_ids", [])

        if act in ("upsert", "simulate_only"):
            if matched_event:
                ev = matched_event
                if clean_name:
                    ev["name"] = clean_name
                ev["category"], ev["year"], ev["end_year"] = clean_cat, s_yr, e_yr
                ev["amount"], ev["annual_amount"], ev["is_outflow"] = amt, amt, bool(is_outflow)
                if clean_desc:
                    ev["description"] = clean_desc
                ev["icon"] = _EVENT_CATEGORY_ICONS.get(clean_cat, "evt-capital-outflow")
                if roth_strategy_preset:
                    ev["roth_strategy_preset"] = roth_strategy_preset
                if ev["id"] not in target_event_ids:
                    target_event_ids.append(ev["id"])
            else:
                max_events = getattr(config, "MAX_FORECAST_EVENTS", 40)
                if len(events) >= max_events:
                    return {"error": f"Maximum scenario events limit ({max_events}) reached", "status": "limit_exceeded"}
                new_ev_id = f"evt_{uuid.uuid4().hex[:8]}"
                ev = {
                    "id": new_ev_id, "name": clean_name or "Life Event", "category": clean_cat,
                    "year": s_yr, "end_year": e_yr, "amount": amt, "annual_amount": amt,
                    "is_outflow": bool(is_outflow), "description": clean_desc,
                    "icon": _EVENT_CATEGORY_ICONS.get(clean_cat, "evt-capital-outflow"),
                }
                if roth_strategy_preset:
                    ev["roth_strategy_preset"] = roth_strategy_preset
                events.append(ev)
                target_event_ids.append(new_ev_id)
        elif act == "enable":
            if not matched_event:
                return {"error": f"Event '{clean_name or event_id}' not found", "status": "not_found"}
            ev = matched_event
            if ev["id"] not in target_event_ids:
                target_event_ids.append(ev["id"])
        elif act == "disable":
            if not matched_event:
                return {"error": f"Event '{clean_name or event_id}' not found", "status": "not_found"}
            ev = matched_event
            if ev["id"] in target_event_ids:
                target_event_ids.remove(ev["id"])
        elif act == "delete":
            if not matched_event:
                return {"error": f"Event '{clean_name or event_id}' not found", "status": "not_found"}
            ev = matched_event
            for sc in scenarios:
                if ev["id"] in sc.get("event_ids", []):
                    sc["event_ids"].remove(ev["id"])
            state["events"] = [e for e in events if e.get("id") != ev["id"]]
        else:
            return {"error": f"Unsupported action '{act}'", "status": "invalid_action"}

        if not is_read_only:
            forecast_engine.save_scenario_state(state, family_id=fam_id)
            try:
                import forecast_cache
                forecast_cache.invalidate_family_cache(fam_id, domains=["scenarios"])
            except Exception:
                pass
            status = "saved"
            ssr_after, raw_after = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen["id"])
        else:
            status = "simulated_only"
            orig_load = forecast_engine.load_scenario_state
            try:
                import forecast.orchestrator
                forecast_engine.load_scenario_state = lambda family_id=0: state
                forecast.orchestrator.load_scenario_state = lambda family_id=0: state
                ssr_after, raw_after = build_ssr_scenarios(family_id=fam_id, scenario_id=target_scen["id"])
            finally:
                forecast_engine.load_scenario_state = orig_load
                forecast.orchestrator.load_scenario_state = orig_load

        def _get_metrics(ssr: Dict[str, Any], sid: str) -> Dict[str, Any]:
            r = next((row for row in ssr.get("scorecard_rows", []) if row.get("id") == sid or row.get("scenario_id") == sid), None)
            return {
                "nw_age_65": (r.get("nw65_str") if r else None) or ssr.get("nw_65") or ssr.get("val_nw65", "--"),
                "nw_age_85": (r.get("nw85_str") if r else None) or ssr.get("nw_85") or ssr.get("val_nw85", "--"),
                "nw_age_95": (r.get("nw95_str") if r else None) or ssr.get("nw_95") or ssr.get("val_nw95", "--"),
                "solvency": (r.get("solv_text") if r else None) or ssr.get("solv_rate_display") or ssr.get("plan_solv_text", "--"),
                "fi_crossover_year": ssr.get("fi_crossover_year", "--"),
            }

        before_m, after_m = _get_metrics(ssr_before, target_scen["id"]), _get_metrics(ssr_after, target_scen["id"])
        sched_by_yr = {r.get("year"): r for r in ((raw_after or {}).get("active_schedule") or [])}
        cf_by_yr = {r.get("year"): r for r in ((raw_after or {}).get("active_cash_flow_series") or [])}

        window_cf = [
            {"year": y, "gross_income": cf_by_yr.get(y, {}).get("gross_compensation", sched_by_yr.get(y, {}).get("gross_income", 0.0)),
             "living_expenses": cf_by_yr.get(y, {}).get("living_core", sched_by_yr.get(y, {}).get("living_spending", 0.0)),
             "events_inflow": cf_by_yr.get(y, {}).get("event_inflows", 0.0),
             "events_outflow": cf_by_yr.get(y, {}).get("events_outflow", 0.0),
             "net_cash_flow": sched_by_yr.get(y, {}).get("net_cash_flow", cf_by_yr.get(y, {}).get("net_cash_flow", 0.0)),
             "liquid_portfolio": sched_by_yr.get(y, {}).get("liquid_assets", sched_by_yr.get(y, {}).get("liquid_portfolio", 0.0)),
             "events_occurred": sched_by_yr.get(y, {}).get("events_occurred", [])}
            for y in range(s_yr, min(e_yr, s_yr + 5) + 1)
        ]

        return {
            "status": status, "scenario_id": target_scen["id"], "scenario_name": target_scen.get("name", ""),
            "event": ev, "before_metrics": before_m, "after_metrics": after_m, "event_window_cash_flow": window_cf,
        }
    except Exception as e:
        logger.warning("Error managing life event for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}
