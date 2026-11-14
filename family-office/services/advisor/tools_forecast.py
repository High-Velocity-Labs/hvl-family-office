"""
Stochastic Monte Carlo Stress Testing and Dynamic What-If Scenario tools for the AI Financial Advisor,
with the compact historical cohort backtest summary they (and the scenario tools) report.
"""

from __future__ import annotations

import logging
import copy
from typing import Any, Dict, Optional

from forecast import engine as forecast_engine
from forecast.dollar_basis import (
    DOLLAR_BASIS_TODAYS, dollar_basis_for_view, dollar_basis_label,
)
from services.request_context import is_sandbox_session
from services.advisor.tool_errors import ADVISOR_TOOL_ERRORS
from services.advisor.tools_cash_flow import get_cash_flow_summary
from services.advisor.tools_core import _resolve_tool_family_id

logger = logging.getLogger(__name__)


def _format_historical_backtest_summary(hist: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts a compact historical cohort backtest summary for advisor tools."""
    if not hist or not isinstance(hist, dict):
        return {}
    worst = [
        {
            "start_year": c.get("start_year"),
            "label": c.get("label"),
            "survived": c.get("survived", False),
            "min_wealth": c.get("trough_net_worth", c.get("min_wealth", 0.0)),
            "terminal_wealth": c.get("terminal_net_worth", c.get("terminal_wealth", 0.0)),
            "depletion_age": c.get("depletion_age"),
        }
        for c in (hist.get("worst_cohorts") or [])[:4]
    ]
    return {
        "historical_survival_rate_pct": hist.get("survival_rate_age_100", hist.get("survival_rate", 0.0)),
        "survived_cohorts": hist.get("survived_cohorts", 0),
        "total_cohorts": hist.get("total_cohorts", 0),
        "failed_cohorts": hist.get("failed_cohorts", 0),
        "median_terminal_wealth": hist.get("median_terminal_wealth", 0.0),
        "spending_guardrail_mode": hist.get("spending_guardrail_mode", "off"),
        "worst_cohorts": worst,
    }


def get_monte_carlo_stress_test(
    family_id: int = 0,
    trials: int = 1000,
    scenario_name: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Executes a stochastic Monte Carlo simulation and historical crisis replays (e.g. 2008 GFC, 1929 Great Crash)."""
    from services.advisor.tools_scenarios import _resolve_scenario

    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        target_scen = None
        precomputed_sim = None
        if scenario_name or scenario_id:
            raw_state = copy.deepcopy(forecast_engine.load_scenario_state(family_id=fam_id))
            target_scen = _resolve_scenario(
                raw_state.get("scenarios", []), scenario_id=scenario_id, scenario_name=scenario_name
            )
            if target_scen:
                raw_state["active_scenario_id"] = target_scen["id"]
                precomputed_sim = forecast_engine.simulate_multi_scenarios(family_id=fam_id, scenario_state=raw_state)
                res = forecast_engine.run_monte_carlo_simulation(
                    sandbox=is_sandbox_session(),
                    family_id=fam_id, trials=trials, precomputed_sim=precomputed_sim
                )
            else:
                res = forecast_engine.run_monte_carlo_simulation(
                    family_id=fam_id, trials=trials, sandbox=is_sandbox_session()
                )
        else:
            res = forecast_engine.run_monte_carlo_simulation(
                family_id=fam_id, trials=trials, sandbox=is_sandbox_session()
            )

        if isinstance(res, dict):
            if target_scen:
                res["scenario_id"] = target_scen["id"]
                res["scenario_name"] = target_scen.get("name")
            if res.get("historical_cohorts"):
                res.setdefault("historical_backtest", res["historical_cohorts"])
                res.setdefault("historical_backtest_summary", _format_historical_backtest_summary(res["historical_cohorts"]))
        return res
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error running Monte Carlo simulation: %s", e)
        return {"error": str(e), "status": "unavailable"}


def _clean_currency_value(val: Any) -> float:
    if not val:
        return 0.0
    return float(str(val).replace("$", "").replace(",", "").strip())


# Amounts the what-if tool reports in the saved view's dollars vs. in today's dollars.
_VIEW_DOLLAR_KEYS = ("median_terminal_net_worth", "worst_10th_percentile_wealth", "nw_age_65", "nw_age_85", "nw_age_95")
_TODAYS_DOLLAR_KEYS = (
    "simulated_spending", "baseline_annual_spending", "additional_annual_expense_modeled", "effective_annual_spending",
)


def simulate_financial_scenario(
    family_id: int = 0,
    custom_spending: Optional[float] = None,
    custom_retirement_age: Optional[int] = None,
    trials: int = 1000,
    spending_guardrail_mode: Optional[str] = None,
    drawdown_order: Optional[str] = None,
    accelerate_lp_calls: Optional[bool] = None,
    additional_annual_expense: Optional[float] = None,
    maximize_annual_gifting_exclusion: Optional[bool] = None,
    annual_gifting_override: Optional[float] = None,
) -> Dict[str, Any]:
    """Simulates a dynamic 'what-if' financial scenario with custom spending, retirement age, drawdown order, accelerated LP calls, lifestyle expenses, or Form 709 family gifting."""
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        baseline_annual_spending = 0.0
        cf = get_cash_flow_summary(family_id=fam_id)
        baseline_annual_spending = float(cf.get("annual_spending") or 0.0)

        gifting_delta = 0.0
        gifting_analysis = None
        has_gifting_intent = bool(maximize_annual_gifting_exclusion) or (annual_gifting_override is not None)
        if has_gifting_intent:
            from services.advisor.tools_tabs import get_family_gifting_summary
            g_info = get_family_gifting_summary(family_id=fam_id) or {}
            tot_limit = _clean_currency_value(g_info.get("total_annual_exclusion_limit"))
            curr_gifted = _clean_currency_value(g_info.get("total_gifted_in_year"))
            rem_head = _clean_currency_value(g_info.get("remaining_tax_exempt_headroom"))
            if annual_gifting_override is not None:
                gifting_delta = max(0.0, float(annual_gifting_override) - curr_gifted)
            elif maximize_annual_gifting_exclusion:
                gifting_delta = rem_head
            if gifting_delta > 0 or annual_gifting_override is not None or maximize_annual_gifting_exclusion:
                gifting_analysis = {
                    "dollar_basis_label": dollar_basis_label(DOLLAR_BASIS_TODAYS),
                    "annual_gifting_limit": tot_limit,
                    "current_annual_gifted": curr_gifted,
                    "additional_annual_gifting_modeled": round(gifting_delta, 2),
                    "estimated_30yr_estate_transfer": round(gifting_delta * 30, 2),
                    "estimated_estate_tax_saved_at_40pct": round(gifting_delta * 30 * 0.40, 2),
                }

        has_spending_override = (additional_annual_expense is not None) or has_gifting_intent
        base_spend = custom_spending if (custom_spending is not None and custom_spending > 0) else baseline_annual_spending
        effective_spending = (base_spend + float(additional_annual_expense or 0.0) + gifting_delta) if has_spending_override else None
        spend_for_sim = effective_spending if has_spending_override else custom_spending

        precomputed_sim = None
        if drawdown_order is not None or accelerate_lp_calls is not None:
            raw_state = copy.deepcopy(forecast_engine.load_scenario_state(family_id=fam_id))
            scenarios = raw_state.get("scenarios", [])
            active_id = raw_state.get("active_scenario_id") or "scen_baseline"
            active_scen = next((s for s in scenarios if s.get("id") == active_id), scenarios[0] if scenarios else None)
            if active_scen is not None:
                if drawdown_order is not None:
                    active_scen["drawdown_order"] = drawdown_order
                if accelerate_lp_calls is not None:
                    active_scen["accelerate_lp_calls"] = bool(accelerate_lp_calls)
            precomputed_sim = forecast_engine.simulate_multi_scenarios(
                family_id=fam_id, annual_living_spend=spend_for_sim,
                primary_retirement_age=custom_retirement_age, spending_guardrail_mode=spending_guardrail_mode,
                scenario_state=raw_state,
            )
        elif spending_guardrail_mode is not None or has_spending_override or custom_spending is not None or custom_retirement_age is not None:
            precomputed_sim = forecast_engine.simulate_multi_scenarios(
                family_id=fam_id, annual_living_spend=spend_for_sim,
                primary_retirement_age=custom_retirement_age, spending_guardrail_mode=spending_guardrail_mode,
            )

        res = forecast_engine.run_monte_carlo_simulation(
            sandbox=is_sandbox_session(),
            family_id=fam_id, trials=trials, custom_spending=spend_for_sim,
            custom_retirement_age=custom_retirement_age, precomputed_sim=precomputed_sim,
        )
        if not res.get("success"):
            return {"error": res.get("error", "Simulation failed")}

        hist_cohorts = res.get("historical_cohorts") or res.get("historical_backtest") or {}
        hist_summary = _format_historical_backtest_summary(hist_cohorts)
        # Net-worth amounts below come from schedules/Monte Carlo in the saved view's dollars; say which.
        view_basis = res.get("dollar_basis") or dollar_basis_for_view(
            (precomputed_sim or {}).get("view_mode")
        )
        out: Dict[str, Any] = {
            "success": True,
            "dollar_basis": view_basis,
            "dollar_basis_label": dollar_basis_label(view_basis),
            "simulated_spending": spend_for_sim if has_spending_override else custom_spending,
            "simulated_retirement_age": custom_retirement_age,
            "spending_guardrail_mode": res.get("spending_guardrail_mode", spending_guardrail_mode or "off"),
            "probability_of_success_pct": res.get(
                "overall_success_rate",
                res.get("probability_of_success", res.get("success_rate_age_100", 0.0)),
            ),
            "median_terminal_net_worth": res.get("median_terminal_wealth", 0.0),
            "worst_10th_percentile_wealth": res.get("percentiles", {}).get("p10", res.get("p10_terminal_wealth", 0.0)),
            "historical_stress_replays": res.get("stress_tests", {}),
            "historical_backtest": hist_summary,
            "historical_backtest_summary": hist_summary,
            "historical_cohorts": hist_summary,
        }
        if has_spending_override:
            out["baseline_annual_spending"] = baseline_annual_spending
            if additional_annual_expense is not None:
                out["additional_annual_expense_modeled"] = float(additional_annual_expense)
            if effective_spending is not None:
                out["effective_annual_spending"] = effective_spending
        if gifting_analysis is not None:
            out["gifting_analysis"] = gifting_analysis
        if drawdown_order is not None:
            out["drawdown_order"] = drawdown_order
        if accelerate_lp_calls is not None:
            out["accelerate_lp_calls"] = bool(accelerate_lp_calls)
        base_basis, base_keys = view_basis, []
        if precomputed_sim:
            active_sc_id = precomputed_sim.get("active_scenario_id")
            scorecard_list = precomputed_sim.get("scorecard") or [{}]
            card = next((r for r in scorecard_list if r.get("id") == active_sc_id), scorecard_list[0])
            sched = precomputed_sim.get("active_schedule") or []
            for k, age in (("nw_age_65", 65), ("nw_age_85", 85), ("nw_age_95", 95)):
                val = card.get(f"net_worth_{age}")
                if val is None:
                    val = next(
                        (s.get("total_net_worth", s.get("net_worth")) for s in sched if s.get("age_primary", s.get("primary_age", s.get("age"))) == age),
                        None,
                    )
                if val is not None:
                    out[k] = val
            base_sim = forecast_engine.simulate_multi_scenarios(family_id=fam_id)
            b_cards = (base_sim or {}).get("scorecard") or [{}]
            b_card = next(
                (r for r in b_cards if r.get("is_baseline") or r.get("id") in ("baseline", "scen_baseline")),
                b_cards[0],
            )
            base_basis = dollar_basis_for_view((base_sim or {}).get("view_mode"))
            for age in (65, 85, 95):
                if b_card.get(f"net_worth_{age}") is not None:
                    out[f"baseline_nw_age_{age}"] = b_card.get(f"net_worth_{age}")
                    base_keys.append(f"baseline_nw_age_{age}")
        # Every amount states its unit: net-worth figures follow the saved view; spending inputs are today's dollars.
        units: Dict[str, str] = {k: dollar_basis_label(view_basis) for k in _VIEW_DOLLAR_KEYS if k in out}
        units.update({k: dollar_basis_label(DOLLAR_BASIS_TODAYS) for k in _TODAYS_DOLLAR_KEYS if k in out})
        units.update({k: dollar_basis_label(base_basis) for k in base_keys})
        out["units"] = units
        return out
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error running what-if scenario: %s", e)
        return {"error": str(e)}
