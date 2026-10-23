"""
Simulation, stress-testing, estate tax, and equity exercise tax tools for the AI Financial Advisor.
Extracted from services.advisor.tools_core to keep modules focused and under size budgets.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Optional

import db
import equity_engine
import estate_engine
import forecast.orchestrator
import forecast_engine
import tax_engine
from routes.helpers import DB_PATH

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
    from services.advisor import tools_core as _tc
    from services.advisor.tools_scenarios import _resolve_scenario

    fam_id = _tc._resolve_tool_family_id(family_id)
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
                orig_load = forecast_engine.load_scenario_state
                try:
                    forecast_engine.load_scenario_state = lambda family_id=0: raw_state
                    forecast.orchestrator.load_scenario_state = forecast_engine.load_scenario_state
                    precomputed_sim = forecast_engine.simulate_multi_scenarios(family_id=fam_id)
                    res = forecast_engine.run_monte_carlo_simulation(
                        family_id=fam_id, trials=trials, precomputed_sim=precomputed_sim
                    )
                finally:
                    forecast_engine.load_scenario_state = orig_load
                    forecast.orchestrator.load_scenario_state = orig_load
            else:
                res = forecast_engine.run_monte_carlo_simulation(family_id=fam_id, trials=trials)
        else:
            res = forecast_engine.run_monte_carlo_simulation(family_id=fam_id, trials=trials)

        if isinstance(res, dict):
            if target_scen:
                res["scenario_id"] = target_scen["id"]
                res["scenario_name"] = target_scen.get("name")
            if res.get("historical_cohorts"):
                res.setdefault("historical_backtest", res["historical_cohorts"])
                res.setdefault("historical_backtest_summary", _format_historical_backtest_summary(res["historical_cohorts"]))
        return res
    except Exception as e:
        logger.warning("Error running Monte Carlo simulation: %s", e)
        return {"error": str(e), "status": "unavailable"}


def get_estate_tax_summary(
    family_id: int = 0,
    state_override: Optional[str] = None,
    apply_tcja_sunset: Optional[bool] = None,
) -> Dict[str, Any]:
    """Retrieves family estate tax calculations, federal vs. state death taxes, TCJA sunset impact, and SLAT/IDGT/ILIT trusts."""
    from services.advisor import tools_core as _tc

    fam_id = _tc._resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        kwargs: Dict[str, Any] = {"family_id": fam_id}
        if state_override:
            kwargs["state_override"] = str(state_override).strip().upper()
        if apply_tcja_sunset is not None:
            kwargs["apply_tcja_sunset"] = bool(apply_tcja_sunset)
        return estate_engine.get_family_estate_profile(**kwargs)
    except Exception as e:
        logger.warning("Error getting estate tax profile: %s", e)
        return {"error": str(e), "status": "unavailable"}


def _clean_currency_value(val: Any) -> float:
    if not val:
        return 0.0
    return float(str(val).replace("$", "").replace(",", "").strip())


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
    from services.advisor import tools_core as _tc

    fam_id = _tc._resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        baseline_annual_spending = 0.0
        try:
            cf = _tc.get_cash_flow_summary(family_id=fam_id)
            baseline_annual_spending = float(cf.get("annual_spending") or 0.0)
        except Exception:
            pass

        gifting_delta = 0.0
        gifting_analysis = None
        has_gifting_intent = bool(maximize_annual_gifting_exclusion) or (annual_gifting_override is not None)
        if has_gifting_intent:
            try:
                from services.advisor.tools_tabs import get_family_gifting_summary
                g_info = get_family_gifting_summary(family_id=fam_id) or {}
            except Exception as e:
                logger.warning("Error fetching gifting summary for scenario: %s", e)
                g_info = {}
            tot_limit = _clean_currency_value(g_info.get("total_annual_exclusion_limit"))
            curr_gifted = _clean_currency_value(g_info.get("total_gifted_in_year"))
            rem_head = _clean_currency_value(g_info.get("remaining_tax_exempt_headroom"))
            if annual_gifting_override is not None:
                gifting_delta = max(0.0, float(annual_gifting_override) - curr_gifted)
            elif maximize_annual_gifting_exclusion:
                gifting_delta = rem_head
            if gifting_delta > 0 or annual_gifting_override is not None or maximize_annual_gifting_exclusion:
                gifting_analysis = {
                    "annual_gifting_limit": tot_limit,
                    "current_annual_gifted": curr_gifted,
                    "additional_annual_gifting_modeled": round(gifting_delta, 2),
                    "estimated_30yr_estate_transfer": round(gifting_delta * 30, 2),
                    "estimated_estate_tax_saved_at_40pct": round(gifting_delta * 30 * 0.40, 2),
                }

        has_spending_override = (additional_annual_expense is not None) or has_gifting_intent
        base_spend = custom_spending if (custom_spending is not None and custom_spending > 0) else baseline_annual_spending
        effective_spending = (
            (base_spend + float(additional_annual_expense or 0.0) + gifting_delta)
            if has_spending_override
            else None
        )
        spend_for_sim = effective_spending if has_spending_override else custom_spending

        precomputed_sim = None
        if drawdown_order is not None or accelerate_lp_calls is not None:
            raw_state = copy.deepcopy(forecast_engine.load_scenario_state(family_id=fam_id))
            scenarios = raw_state.get("scenarios", [])
            active_id = raw_state.get("active_scenario_id") or "scen_baseline"
            active_scen = next(
                (s for s in scenarios if s.get("id") == active_id),
                scenarios[0] if scenarios else None,
            )
            if active_scen is not None:
                if drawdown_order is not None:
                    active_scen["drawdown_order"] = drawdown_order
                if accelerate_lp_calls is not None:
                    active_scen["accelerate_lp_calls"] = bool(accelerate_lp_calls)
            orig_load = forecast_engine.load_scenario_state
            try:
                forecast_engine.load_scenario_state = lambda family_id=0: raw_state
                forecast.orchestrator.load_scenario_state = forecast_engine.load_scenario_state
                precomputed_sim = forecast_engine.simulate_multi_scenarios(
                    family_id=fam_id,
                    annual_living_spend=spend_for_sim,
                    primary_retirement_age=custom_retirement_age,
                    spending_guardrail_mode=spending_guardrail_mode,
                )
            finally:
                forecast_engine.load_scenario_state = orig_load
                forecast.orchestrator.load_scenario_state = orig_load
        elif spending_guardrail_mode is not None:
            precomputed_sim = forecast_engine.simulate_multi_scenarios(
                family_id=fam_id,
                annual_living_spend=spend_for_sim,
                primary_retirement_age=custom_retirement_age,
                spending_guardrail_mode=spending_guardrail_mode,
            )

        res = forecast_engine.run_monte_carlo_simulation(
            family_id=fam_id,
            trials=trials,
            custom_spending=spend_for_sim,
            custom_retirement_age=custom_retirement_age,
            precomputed_sim=precomputed_sim,
        )
        if not res.get("success"):
            return {"error": res.get("error", "Simulation failed")}

        hist_cohorts = res.get("historical_cohorts") or res.get("historical_backtest") or {}
        hist_summary = _format_historical_backtest_summary(hist_cohorts)
        out: Dict[str, Any] = {
            "success": True,
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
        if precomputed_sim:
            active_sc_id = precomputed_sim.get("active_scenario_id")
            scorecard_list = precomputed_sim.get("scorecard") or [{}]
            card = next((r for r in scorecard_list if r.get("id") == active_sc_id), scorecard_list[0])
            sched = precomputed_sim.get("active_schedule") or []
            for k, age in (("nw_age_65", 65), ("nw_age_85", 85), ("nw_age_95", 95)):
                val = card.get(f"net_worth_{age}")
                if val is None:
                    val = next(
                        (
                            s.get("total_net_worth", s.get("net_worth"))
                            for s in sched
                            if s.get("age_primary", s.get("primary_age", s.get("age"))) == age
                        ),
                        None,
                    )
                if val is not None:
                    out[k] = val
        return out
    except Exception as e:
        logger.warning("Error running what-if scenario: %s", e)
        return {"error": str(e)}


def estimate_equity_exercise_tax(
    family_id: int = 0,
    shares_to_exercise: float = 0.0,
    strike_price: Optional[float] = None,
    share_price: Optional[float] = None,
    grant_type: str = "nso",
    include_wa_millionaire_tax: bool = False,
) -> Dict[str, Any]:
    """Calculates tax liability, strike cost, and net proceed impact for exercising equity options or stock sales."""
    from services.advisor import tools_core as _tc

    fam_id = _tc._resolve_tool_family_id(family_id)
    if not fam_id or shares_to_exercise <= 0:
        return {"error": "Invalid shares or unauthenticated session"}

    try:
        current_409a = equity_engine.get_company_409a_price(family_id=fam_id)
        effective_share_price = share_price if share_price is not None and share_price > 0 else current_409a
        effective_strike = strike_price if strike_price is not None else 0.0
        if strike_price is None:
            grants = equity_engine.load_equity_grants_from_db(family_id=fam_id)
            if grants:
                effective_strike = grants[0].strike_price

        strike_cost = round(shares_to_exercise * effective_strike, 2)
        gross_value = round(shares_to_exercise * effective_share_price, 2)
        spread = max(0.0, gross_value - strike_cost)
        cf = _tc.get_cash_flow_summary(family_id=fam_id)
        is_mfj = cf.get("tax_filing_status", "MFJ") == "MFJ"
        prior_ordinary_income = 0.0
        try:
            comp_rows = db.compensation.list_compensation_records(family_id=fam_id, db_path=DB_PATH) if DB_PATH.exists() else []
            if comp_rows:
                latest = max(comp_rows, key=lambda r: int(r.get("year") or 0))
                prior_ordinary_income = max(0.0, float(latest.get("salary") or 0.0) + float(latest.get("bonus") or 0.0))
        except Exception:
            pass

        if grant_type.lower() == "nso":
            tax_res = tax_engine.calculate_nso_exercise_tax(
                spread=spread, prior_ordinary_income=prior_ordinary_income,
                include_wa_millionaire_tax=include_wa_millionaire_tax, is_mfj=is_mfj,
            )
            tot_tax = tax_res.get("total_tax", 0.0)
            return {
                "shares": shares_to_exercise, "share_price": effective_share_price, "strike_price": effective_strike,
                "total_strike_cost": strike_cost, "gross_spread": round(spread, 2),
                "prior_ordinary_income_used": prior_ordinary_income, "federal_tax": tax_res.get("federal_income_tax", 0.0),
                "medicare_tax": tax_res.get("medicare_tax", 0.0), "wa_state_tax": tax_res.get("wa_state_tax", 0.0),
                "total_tax_liability": round(tot_tax, 2), "effective_tax_rate_pct": round(tax_res.get("effective_rate", 0.0) * 100, 2),
                "net_take_home_cashless": round(spread - tot_tax, 2),
            }

        sale_tax = tax_engine.calculate_stock_sale_tax(
            sale_proceeds=gross_value, cost_basis=strike_cost, holding_period_days=366, is_mfj=is_mfj
        )
        return {
            "shares": shares_to_exercise, "share_price": effective_share_price, "cost_basis": strike_cost,
            "gross_proceeds": gross_value, "capital_gain": sale_tax.get("gain", 0.0),
            "federal_ltcg_tax": sale_tax.get("federal_capital_gains_tax", 0.0), "niit_tax": sale_tax.get("niit_tax", 0.0),
            "wa_capital_gains_tax": sale_tax.get("wa_capital_gains_tax", 0.0), "total_tax_liability": sale_tax.get("total_tax", 0.0),
            "net_proceeds": round(gross_value - strike_cost - sale_tax.get("total_tax", 0.0), 2),
        }
    except Exception as e:
        logger.warning("Error estimating equity exercise tax: %s", e)
        return {"error": str(e), "status": "unavailable"}
