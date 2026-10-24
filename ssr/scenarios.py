"""
SSR Builder for the Forecasting / Multi-Scenario Longevity section.
Computes server-side rendered template context and raw JSON payload for #section-scenarios.
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict, Optional, Tuple

from ssr.formatting import fmt_short_currency
from ssr.scenarios_scorecard import (
    _OVERRIDE_LABEL_MAP,
    build_assumptions_and_overrides,
    build_scorecard_rows,
    format_override_value as _format_override_value,
)
from ssr.scenarios_shelf import (
    build_events_and_timeline_shelf,
    build_schedule_and_inspector,
)

logger = logging.getLogger(__name__)


def _parse_float(val: Any) -> Optional[float]:
    if val in (None, "", "null", "undefined"):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_int(val: Any) -> Optional[int]:
    if val in (None, "", "null", "undefined"):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _load_or_run_simulation(
    family_id: int,
    scenario_id: Optional[str],
    custom_params: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    import forecast_cache
    import forecast_engine
    from routes.helpers import get_current_universe

    universe = get_current_universe()
    raw_params = dict(custom_params or {})
    cache_params: Dict[str, Any] = {
        str(k): v
        for k, v in raw_params.items()
        if v not in (None, "", "null", "undefined")
    }

    req_scen_id = scenario_id or cache_params.get("scenario_id") or cache_params.get("target_scenario_id")
    if req_scen_id in (None, "", "null", "undefined"):
        req_scen_id = None
    else:
        req_scen_id = str(req_scen_id)
        cache_params["scenario_id"] = req_scen_id

    ck = forecast_cache.make_cache_key(family_id, universe, cache_params)
    sim = forecast_cache.get_simulation(ck)

    if not sim and set(cache_params.keys()) <= {"scenario_id"}:
        base_ck = forecast_cache.make_cache_key(family_id, universe, {})
        base_sim = forecast_cache.get_simulation(base_ck)
        if base_sim and (not req_scen_id or req_scen_id == base_sim.get("active_scenario_id")):
            sim = base_sim

    if not sim:
        equity_preset = cache_params.get("equity_growth_preset")
        view_mode_param = cache_params.get("view_mode")
        primary_ret_age = _parse_int(
            cache_params.get("primary_retirement_age")
            if cache_params.get("primary_retirement_age") is not None
            else cache_params.get("retirement_age")
        )
        equity_presets_arg = None
        if cache_params.get("equity_growth_presets"):
            raw_eq_p = cache_params.get("equity_growth_presets")
            try:
                parsed_p = json.loads(raw_eq_p) if isinstance(raw_eq_p, str) else raw_eq_p
                if isinstance(parsed_p, dict):
                    equity_presets_arg = {str(k): str(v) for k, v in parsed_p.items() if v}
            except Exception:
                pass

        sim = forecast_engine.simulate_multi_scenarios(
            family_id=family_id,
            target_scenario_id=req_scen_id,
            equity_growth_preset=str(equity_preset) if equity_preset else None,
            equity_growth_presets=equity_presets_arg,
            primary_retirement_age=primary_ret_age,
            spouse_retirement_age=_parse_int(cache_params.get("spouse_retirement_age")),
            annual_living_spend=_parse_float(cache_params.get("annual_living_spend")),
            annual_savings=_parse_float(cache_params.get("annual_savings")),
            inflation_rate=_parse_float(cache_params.get("inflation_rate")),
            ss_claim_age=_parse_int(cache_params.get("ss_claim_age")),
            primary_ss_claim_age=_parse_int(cache_params.get("primary_ss_claim_age")),
            spouse_ss_claim_age=_parse_int(cache_params.get("spouse_ss_claim_age")),
            growth_us_equity=_parse_float(cache_params.get("growth_us_equity")),
            growth_intl_equity=_parse_float(cache_params.get("growth_intl_equity")),
            growth_bonds=_parse_float(cache_params.get("growth_bonds")),
            growth_cash=_parse_float(cache_params.get("growth_cash")),
            growth_private_investments=_parse_float(cache_params.get("growth_private_investments")),
            growth_real_estate=_parse_float(cache_params.get("growth_real_estate")),
            view_mode=str(view_mode_param) if view_mode_param else None,
            spending_guardrail_mode=str(cache_params.get("spending_guardrail_mode")) if cache_params.get("spending_guardrail_mode") else None,
        )
        if sim:
            forecast_cache.set_simulation(
                ck,
                sim,
                persist_l2=forecast_cache.is_canonical_simulation_params(cache_params),
            )

    return sim, req_scen_id, cache_params


def build_ssr_scenarios(
    family_id: int,
    scenario_id: Optional[str] = None,
    custom_params: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Generates SSR metrics for Forecasting / Scenarios plan card and raw dictionary payload."""
    if family_id <= 0:
        return {}, {}
    try:
        sim, req_scen_id, cache_params = _load_or_run_simulation(family_id, scenario_id, custom_params)
        if not sim:
            return {}, {}

        sim = dict(sim)
        default_scen_id = sim.get("active_scenario_id") or "scen_baseline"
        scens = [dict(s) for s in (sim.get("scenarios") or []) if isinstance(s, dict)]
        for s in scens:
            s["is_archived"] = bool(s.get("is_archived", False))
        sim["scenarios"] = scens
        archived_count = sum(1 for s in scens if s.get("is_archived"))
        valid_scen_ids = {s.get("id") for s in scens if s.get("id")}

        selected_scen_id = req_scen_id if (req_scen_id and req_scen_id in valid_scen_ids) else default_scen_id
        active_scen_id = selected_scen_id
        is_default_selected = selected_scen_id == default_scen_id

        view_mode = str(cache_params.get("view_mode") or sim.get("view_mode") or "real").lower()
        if view_mode not in ("real", "nominal"):
            view_mode = "real"
        sim["view_mode"] = view_mode
        sim["selected_scenario_id"] = selected_scen_id
        sim["default_scenario_id"] = default_scen_id

        scorecard_items = sim.get("scorecard") or []
        card = next((item for item in scorecard_items if item.get("id") == active_scen_id), None) or (scorecard_items[0] if scorecard_items else {})
        cur_scen = next((s for s in scens if s.get("id") == (card.get("id") or active_scen_id)), None) or (scens[0] if scens else {})
        ret_readiness = card.get("retirement_readiness") or cur_scen.get("retirement_readiness") or sim.get("active_retirement_readiness") or {}

        if selected_scen_id != default_scen_id:
            scen_scheds, scen_cfs, scen_longs = sim.get("scenario_schedules") or {}, sim.get("scenario_cash_flows") or {}, sim.get("scenario_longevity_breakdowns") or {}
            if selected_scen_id in scen_scheds:
                sim["active_schedule"] = scen_scheds[selected_scen_id]
            if selected_scen_id in scen_cfs:
                sim["active_cash_flow_series"] = scen_cfs[selected_scen_id]
            if selected_scen_id in scen_longs:
                sim["active_longevity_breakdown"] = scen_longs[selected_scen_id]
            if ret_readiness:
                sim["active_retirement_readiness"] = ret_readiness

        p_name = ret_readiness.get("primary_name") or sim.get("primary_name") or "Primary"
        s_name = ret_readiness.get("spouse_name") or sim.get("spouse_name") or "Spouse"
        try:
            p_cur_age = int(ret_readiness.get("primary_current_age") or sim.get("primary_current_age") or 49)
        except (ValueError, TypeError):
            p_cur_age = 49
        try:
            s_cur_age = int(ret_readiness.get("spouse_current_age") or sim.get("spouse_current_age") or 47)
        except (ValueError, TypeError):
            s_cur_age = 47

        try:
            p_age = int(ret_readiness.get("primary_planned_age") or cur_scen.get("primary_retirement_age") or card.get("primary_retirement_age") or 50)
        except (ValueError, TypeError):
            p_age = 50
        try:
            raw_p_yr = ret_readiness.get("primary_planned_year") or card.get("primary_retirement_year") or cur_scen.get("primary_retirement_year")
            p_yr = int(raw_p_yr) if raw_p_yr is not None else (2026 + max(0, p_age - p_cur_age))
        except (ValueError, TypeError):
            p_yr = 2026 + max(0, p_age - p_cur_age)

        try:
            s_age = int(ret_readiness.get("spouse_planned_age") or cur_scen.get("spouse_retirement_age") or card.get("spouse_retirement_age") or 52)
        except (ValueError, TypeError):
            s_age = 52
        try:
            raw_s_yr = ret_readiness.get("spouse_planned_year") or card.get("spouse_retirement_year") or cur_scen.get("spouse_retirement_year")
            s_yr = int(raw_s_yr) if raw_s_yr is not None else (2026 + max(0, s_age - s_cur_age))
        except (ValueError, TypeError):
            s_yr = 2026 + max(0, s_age - s_cur_age)

        p_years_away, s_years_away = max(0, p_yr - 2026), max(0, s_yr - 2026)

        nw65_num = card.get("net_worth_65") if card.get("net_worth_65") is not None else cur_scen.get("net_worth_65")
        nw85_num = card.get("net_worth_85") if card.get("net_worth_85") is not None else cur_scen.get("net_worth_85")
        nw95_num = card.get("net_worth_95") if card.get("net_worth_95") is not None else cur_scen.get("net_worth_95")
        nw65, nw85, nw95 = fmt_short_currency(nw65_num), fmt_short_currency(nw85_num), fmt_short_currency(nw95_num)

        is_depleted = bool(card.get("is_depleted"))
        is_sust = (ret_readiness.get("is_sustainable") is True) and not is_depleted
        living_spend_num = (
            card.get("annual_living_spend")
            if card.get("annual_living_spend") is not None
            else (cur_scen.get("annual_living_spend") if cur_scen.get("annual_living_spend") is not None else (sim.get("annual_living_spend") or 0))
        )
        annual_savings_num = cur_scen.get("annual_savings") if cur_scen.get("annual_savings") is not None else (card.get("annual_savings") or sim.get("annual_savings") or 0)
        spend = fmt_short_currency(living_spend_num)
        evt_count = len(card.get("events_included") or card.get("events_details") or cur_scen.get("event_ids") or [])
        spend_text = f"{evt_count} Events • {spend}/yr"

        baseline_card = next((s for s in scorecard_items if s.get("is_baseline")), scorecard_items[-1] if scorecard_items else {})
        baseline_nw65 = (
            baseline_card.get("net_worth_65")
            if baseline_card.get("net_worth_65") is not None
            else (next((s for s in scens if s.get("is_baseline")), scens[-1] if scens else {}).get("net_worth_65") or 0)
        )
        diff65 = (nw65_num or 0) - (baseline_nw65 or 0)
        diff65_str = f"{'+' if diff65 >= 0 else ''}{fmt_short_currency(diff65)} vs Baseline"

        liquid_cap = float(ret_readiness.get("liquid_capital") or 0.0)
        terminal_nw = float(ret_readiness.get("terminal_net_worth") or nw95_num or 0.0)

        mc_solv = card.get("monte_carlo_solvency")
        if mc_solv is None:
            active_mc_obj = sim.get("active_monte_carlo") or {}
            if not active_mc_obj.get("scenario_id") or active_mc_obj.get("scenario_id") == active_scen_id:
                mc_solv = active_mc_obj.get("success_rate_age_100")
        has_mc = mc_solv is not None
        solv_rate = mc_solv if has_mc else (100 if is_sust else 0)
        solv_rate_fmt = int(solv_rate) if isinstance(solv_rate, float) and solv_rate.is_integer() else solv_rate
        solv_color = "var(--status-green)" if solv_rate >= 90 else ("var(--accent-orange)" if solv_rate >= 75 else "var(--status-red)")
        solv_badge = "badge-green" if solv_rate >= 90 else ("badge-orange" if solv_rate >= 75 else "badge-red")
        solv_badge_text = "High Solvency" if solv_rate >= 90 else ("Moderate Sequence Risk" if solv_rate >= 75 else "High Sequence Risk")
        solv_sub = f"{solv_rate_fmt}% of 1,000 Monte Carlo trials solvent at 100" if has_mc else ("Deterministic baseline solvent" if is_sust else "Outflows exhaust capital")
        solv_rate_display = f"{solv_rate_fmt}%" if has_mc else ("100%" if is_sust else "Depleted")
        plan_solv_badge = solv_badge if has_mc else ("badge-red" if is_depleted else "badge-green")
        plan_solv_text = f"{solv_rate_fmt}% Solvency (MC)" if has_mc else ("Depleted" if is_depleted else "Solvent @ 100")

        can_retire_today = is_sust and (ret_readiness.get("can_retire_today") is True)
        fi_achieved = is_sust and (ret_readiness.get("fi_achieved") is True)
        fi_threshold = fmt_short_currency(ret_readiness.get("fi_threshold", 0))
        fi_crossover_year = ret_readiness.get("fi_crossover_year") or p_yr

        earliest_joint_yr = ret_readiness.get("earliest_joint_year")
        earliest_p_age = ret_readiness.get("earliest_primary_age")
        earliest_s_age = ret_readiness.get("earliest_spouse_age")
        has_feasible_retirement = bool(earliest_joint_yr)
        earliest_years_away = (int(earliest_joint_yr) - 2026) if earliest_joint_yr else 0
        spending_amt_num = ret_readiness.get("annual_spending") or sim.get("annual_living_spend") or living_spend_num or 0
        spending_amt_str = fmt_short_currency(spending_amt_num)

        def _ret_badge_tuple(cur_a: Any, plan_a: Any, plan_y: Any, earliest_a: Any) -> Tuple[str, str, str]:
            if can_retire_today:
                return f"Now (Age {cur_a})", "badge-green", f"Plan: Age {plan_a} ({plan_y})"
            if is_sust:
                return f"Age {plan_a} ({plan_y})", "badge-blue", "Sustainable"
            if earliest_a:
                return f"Age {earliest_a} ({earliest_joint_yr})", "badge-orange", f"Plan Age {plan_a}: Depleted"
            return "Infeasible", "badge-red", "Depleted"

        val_primary_ret, val_primary_ret_badge, sub_primary_ret = _ret_badge_tuple(p_cur_age, p_age, p_yr, earliest_p_age)
        val_spouse_ret, val_spouse_ret_badge, sub_spouse_ret = _ret_badge_tuple(s_cur_age, s_age, s_yr, earliest_s_age)

        shelf_data = build_events_and_timeline_shelf(sim, card, cur_scen)
        assumptions_data = build_assumptions_and_overrides(
            sim=sim, card=card, cur_scen=cur_scen, scens=scens,
            selected_scen_id=selected_scen_id, default_scen_id=default_scen_id,
            living_spend_num=float(living_spend_num), annual_savings_num=float(annual_savings_num),
        )
        scorecard_rows = build_scorecard_rows(
            scorecard_items=scorecard_items, catalog=shelf_data["catalog"],
            scen_name_by_id=assumptions_data["scen_name_by_id"], active_scen_id=active_scen_id,
            default_scen_id=default_scen_id, p_cur_age=int(p_cur_age), s_cur_age=int(s_cur_age),
        )
        sched_data = build_schedule_and_inspector(sim, cur_scen, active_scen_id, str(p_name), str(s_name))

        from ssr.widgets import build_scenarios_widgets

        ssr_scenarios = {
            "view_mode": view_mode,
            "plan_name": card.get("name") or cur_scen.get("name") or "Baseline Plan",
            "plan_color": assumptions_data["plan_color"],
            "is_active_plan": is_default_selected,
            "is_default_selected": is_default_selected,
            "is_archived": bool(card.get("is_archived") or cur_scen.get("is_archived", False)),
            "is_baseline": bool(card.get("is_baseline") or cur_scen.get("is_baseline") or active_scen_id == "scen_baseline"),
            "archived_count": archived_count,
            "selected_scenario_id": selected_scen_id,
            "default_scenario_id": default_scen_id,
            "has_parent": bool(assumptions_data["parent_id"]),
            "parent_name": assumptions_data["parent_name"] or "Baseline Plan",
            "parent_id": assumptions_data["parent_id"] or "",
            "override_pills": assumptions_data["override_pills"],
            "overrides_map": assumptions_data["raw_overrides"],
            "overrides_count": assumptions_data["overrides_count"],
            "overrides_summary_text": assumptions_data["overrides_summary_text"],
            "overrides_tooltip": assumptions_data["overrides_tooltip"],
            "can_revert_assumptions": assumptions_data["can_revert_assumptions"],
            "scorecard_count": len(scorecard_items),
            "spending_presets": assumptions_data["spending_presets"],
            "savings_presets": assumptions_data["savings_presets"],
            "primary_ss_claim_age": assumptions_data["primary_ss_claim_age"],
            "spouse_ss_claim_age": assumptions_data["spouse_ss_claim_age"],
            "inflation_pct_str": assumptions_data["inflation_pct_str"],
            "inflation_input_val": assumptions_data["inflation_input_val"],
            "blended_liquid_pct": assumptions_data["blended_liquid_pct"],
            "private_vc_pct": assumptions_data["private_vc_pct"],
            "real_estate_pct": assumptions_data["real_estate_pct"],
            "growth_us_val": assumptions_data["growth_us_val"],
            "growth_intl_val": assumptions_data["growth_intl_val"],
            "growth_bonds_val": assumptions_data["growth_bonds_val"],
            "growth_cash_val": assumptions_data["growth_cash_val"],
            "growth_priv_val": assumptions_data["growth_priv_val"],
            "growth_re_val": assumptions_data["growth_re_val"],
            "market_return_profile": assumptions_data["market_return_profile"],
            "liquid_weights_str": assumptions_data["liquid_weights_str"],
            "equity_holdings": assumptions_data["equity_holdings"],
            "equity_growth_preset": assumptions_data["equity_growth_preset"],
            "spending_guardrail_mode": assumptions_data["spending_guardrail_mode"],
            "guardrails_badge_label": assumptions_data["guardrails_badge_label"],
            "scorecard_rows": scorecard_rows,
            "val_primary_ret": val_primary_ret,
            "val_primary_ret_badge": val_primary_ret_badge,
            "sub_primary_ret": sub_primary_ret,
            "val_spouse_ret": val_spouse_ret,
            "val_spouse_ret_badge": val_spouse_ret_badge,
            "sub_spouse_ret": sub_spouse_ret,
            "val_nw65": nw65,
            "val_nw85": nw85,
            "val_nw95": nw95,
            "is_sustainable": is_sust,
            "val_spend": spend_text,
            "primary_ret_age": p_age,
            "primary_ret_yr": p_yr,
            "spouse_ret_age": s_age,
            "spouse_ret_yr": s_yr,
            "primary_name": p_name,
            "spouse_name": s_name,
            "primary_current_age": p_cur_age,
            "spouse_current_age": s_cur_age,
            "p_years_away": p_years_away,
            "s_years_away": s_years_away,
            "annual_living_spend": living_spend_num,
            "annual_savings": annual_savings_num,
            "spending_amt_str": spending_amt_str,
            "liquid_cap": fmt_short_currency(liquid_cap),
            "liquid_cap_num": liquid_cap,
            "terminal_wealth": f"{'-' if terminal_nw < 0 else ''}${abs(terminal_nw) / 1e9:,.2f}B" if abs(terminal_nw) >= 1e9 else fmt_short_currency(terminal_nw),
            "terminal_nw_num": terminal_nw,
            "diff65_str": diff65_str,
            "diff65_num": diff65,
            "solv_color": solv_color,
            "solv_badge": solv_badge,
            "solv_badge_text": solv_badge_text,
            "solv_subtitle": solv_sub,
            "solv_rate_display": solv_rate_display,
            "plan_solv_badge": plan_solv_badge,
            "plan_solv_text": plan_solv_text,
            "can_retire_today": can_retire_today,
            "fi_achieved": fi_achieved,
            "fi_threshold": fi_threshold,
            "fi_crossover_year": fi_crossover_year,
            "has_feasible_retirement": has_feasible_retirement,
            "earliest_joint_yr": earliest_joint_yr,
            "earliest_p_age": earliest_p_age,
            "earliest_s_age": earliest_s_age,
            "earliest_years_away": earliest_years_away,
            "has_cards": True,
            "scenarios": scens,
            "active_scenario_id": active_scen_id,
            "events": shelf_data["active_events"],
            "schedule_rows": sched_data["schedule_rows"],
        }
        ssr_scenarios["widgets"] = build_scenarios_widgets(family_id, ssr_scenarios, sim)
        return ssr_scenarios, sim
    except Exception as e:
        logger.warning(f"Failed to generate SSR scenarios data: {e}")
        return {}, {}
