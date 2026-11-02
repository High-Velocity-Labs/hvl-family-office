"""
Core callable tools for the AI Financial Advisor:
Portfolio Allocation & Holdings, Company Equity & Vesting, Cash Flow & Balance Sheet Summary,
Stochastic Monte Carlo Stress Testing, Estate Tax Profile, Dynamic What-If Scenarios,
and Equity Option Exercise Tax Estimation.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

import account_sync
import db
from forecast import engine as forecast_engine
from forecast.dollar_basis import (
    DOLLAR_BASIS_TODAYS, dollar_basis_for_view, dollar_basis_label,
)
import security
from equity.iso_amt import amt_credit_recovery_years, iso_exercise_amt
from equity.state_tax import compensation_option_tax, stock_sale_tax_for_state
from services.request_context import DB_PATH, get_current_family_id, is_sandbox_session
from services import equity_engine, estate_engine, residence_state
from services.household_income import household_prior_income
from ssr.holdings import HOLDINGS_PRESETS, build_ssr_holdings
from services.advisor.tool_errors import ADVISOR_TOOL_ERRORS

logger = logging.getLogger(__name__)


def _resolve_tool_family_id(family_id: int = 0) -> int:
    """
    Resolves the household from the trusted request or background context only.
    The model-supplied `family_id` argument is ignored so a tool call can never pick its own tenant.
    """
    return max(get_current_family_id(), 0)


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


def get_portfolio_allocation(family_id: int = 0) -> Dict[str, Any]:
    """
    Retrieves the household investment policy statement (IPS), target vs. actual asset allocation,
    drift tolerance, rebalancing action steps, brokerage/401(k) ticker positions, and private investments.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    policy_data: Dict[str, Any] = {
        "anchor_preset": "core_satellite",
        "preset_name": "Core & Satellite (50/20/15/5/10)",
        "drift_tolerance": 0.05,
        "deviations_rationale": "Adhering to standard core-satellite asset allocation.",
        "target_allocation": {
            "us_total_market": 0.50,
            "international_equities": 0.20,
            "us_aggregate_bonds": 0.15,
            "cash_reserves": 0.05,
            "satellite_growth": 0.10,
        },
        "rebalancing_guidelines": [
            "Rebalance tax-free via incoming cash sweeps and 401(k) reallocations.",
            "Avoid selling appreciated taxable lots to satisfy drift tolerance.",
        ],
    }

    try:
        hp = db.household.get_household_profile(family_id=fam_id, db_path=DB_PATH)
        if hp and hp.get("assumptions_json"):
            assumptions = json.loads(hp["assumptions_json"]) if isinstance(hp["assumptions_json"], str) else hp["assumptions_json"]
            if isinstance(assumptions, dict) and isinstance(assumptions.get("investment_policy"), dict):
                pol = assumptions["investment_policy"]
                preset_id = pol.get("anchor_preset", "core_satellite")
                preset_names = {
                    "core_satellite": "Core & Satellite (50/20/15/5/10)",
                    "boglehead_80_20": "Classic Three-Fund (80/20)",
                    "all_equity_90_10": "Aggressive All-Equity (90/10)",
                    "boglehead_90_10": "Aggressive All-Equity (90/10)",
                    "glidepath_60_40": "Age-Based Glidepath (60/40)",
                    "boglehead_60_40": "Age-Based Glidepath (60/40)",
                    "core_four_reit": "Core Four with Real Estate REITs (48/24/20/8)",
                }
                policy_data["anchor_preset"] = preset_id
                policy_data["preset_name"] = preset_names.get(preset_id, preset_id.replace("_", " ").title())
                policy_data["drift_tolerance"] = float(pol.get("drift_tolerance", 0.05))
                policy_data["deviations_rationale"] = str(pol.get("deviations_rationale", ""))
                norm_key = {"boglehead_90_10": "all_equity_90_10", "boglehead_60_40": "glidepath_60_40"}.get(preset_id, preset_id)
                if norm_key in HOLDINGS_PRESETS:
                    t_map = HOLDINGS_PRESETS[norm_key]["targets"]
                    policy_data["target_allocation"] = {
                        "us_total_market": t_map.get("us_equity", 0.0),
                        "international_equities": t_map.get("intl_equity", 0.0),
                        "real_estate_reits": t_map.get("real_estate", 0.0),
                        "us_aggregate_bonds": t_map.get("bonds", 0.0),
                        "cash_reserves": t_map.get("cash", 0.0),
                        "satellite_growth": t_map.get("private_vc", 0.0),
                    }
    except json.JSONDecodeError as e:
        logger.warning("Stored investment-policy assumptions for family %s are not valid JSON: %s", fam_id, e)

    snap = account_sync.get_financial_snapshot(family_id=fam_id) or {}
    ssr_h = build_ssr_holdings(snap, family_id=fam_id)
    if ssr_h:
        policy_data["total_portfolio_value"] = ssr_h.get("deltas_foot", {}).get("tot_actual", "$0")
        policy_data["actual_balances"] = {
            "us_equity": ssr_h.get("us_equity_raw", 0.0),
            "intl_equity": ssr_h.get("intl_equity_raw", 0.0),
            "bonds": ssr_h.get("bonds_raw", 0.0),
            "cash": ssr_h.get("cash_raw", 0.0),
            "real_estate": ssr_h.get("real_estate_raw", 0.0),
            "private_vc": ssr_h.get("private_raw", 0.0),
        }
        policy_data["asset_class_drift_rows"] = [
            {
                "asset_class": r.get("label"),
                "actual": r.get("actual_str"),
                "actual_pct": r.get("actual_pct_str"),
                "target": r.get("target_str"),
                "target_pct": r.get("target_pct_str"),
                "delta": r.get("delta_str"),
                "drift_pct": r.get("drift_pct_str"),
                "exceeds_tolerance": r.get("is_excess", False),
            }
            for r in (ssr_h.get("deltas_rows") or [])
        ]
        policy_data["rebalance_action_steps"] = ssr_h.get("rebalance_steps") or []
        policy_data["private_investments"] = [
            {
                "name": p.get("name"),
                "category": p.get("category"),
                "institution": p.get("institution"),
                "value": p.get("val_str"),
                "percentage": p.get("percentage"),
            }
            for p in (ssr_h.get("private_rows") or [])
        ]
        policy_data["brokerage_accounts"] = [
            {
                "account_name": a.get("account_name"),
                "type": a.get("type_label"),
                "balance": a.get("balance_str"),
                "positions": [
                    {
                        "ticker": pos.get("ticker"),
                        "name": pos.get("name"),
                        "asset_class": pos.get("badge_text"),
                        "quantity": pos.get("quantity_str"),
                        "price": pos.get("price_str"),
                        "value": pos.get("value_str"),
                        "pct_of_account": pos.get("pct_of_acc"),
                    }
                    for pos in (a.get("positions") or [])[:25]
                ],
            }
            for a in (ssr_h.get("brokerage_accounts") or [])
        ]
    from services.private_markets_service import get_lp_commitments_summary
    policy_data["lp_commitment_book"] = get_lp_commitments_summary(family_id=fam_id)

    return policy_data


def get_equity_schedule(family_id: int = 0) -> Dict[str, Any]:
    """
    Retrieves executive equity grants (NSOs, ISOs, RSUs), vesting schedules, 409A share valuation,
    multi-company breakdowns, strike capital required, and 5-year net proceeds projections.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    try:
        equity_data = equity_engine.simulate_valuation_scenario(family_id=fam_id)
        equity_wa_2028 = equity_engine.simulate_valuation_scenario(include_wa_millionaire_tax=True, family_id=fam_id)
        grants_list = equity_data.get("grants", [])
        nso_count = sum(1 for g in grants_list if str(g.get("grant_type", "NSO")).upper() != "RSU")
        rsu_count = sum(1 for g in grants_list if str(g.get("grant_type", "NSO")).upper() == "RSU")
        net_pre_2028 = float(equity_data.get("true_net_post_tax_value", 0.0) or 0.0)
        net_2028_plus = float(equity_wa_2028.get("true_net_post_tax_value", net_pre_2028) or 0.0)

        companies_summary, projections_5yr = [], []
        companies_summary = equity_engine.load_equity_companies_summary(family_id=fam_id) or []
        share_p = float(equity_data.get("share_price") or 0.0)
        raw_proj = (
            equity_engine.simulate_multi_year_projections(
                annual_growth_rate=0.105,
                years=5,
                base_share_price=share_p if share_p > 0 else 100.0,
                family_id=fam_id,
            )
            or []
        )
        projections_5yr = [
            {
                "year": p.get("year"),
                "projected_share_price": p.get("projected_share_price"),
                "vested_gross_value": p.get("total_gross_value"),
                "true_net_post_tax_value": p.get("true_net_value"),
                "strike_cost_needed": p.get("total_strike_cost"),
                "estimated_tax_drag": p.get("total_tax_drag"),
            }
            for p in raw_proj[:6]
        ]

        return {
            "company_name": equity_data.get("company_name", "Primary Company"),
            "share_price": equity_data.get("share_price", 0.0),
            "total_gross_equity_value": equity_data.get("total_gross_equity_value", 0.0),
            "true_net_post_tax_value": net_pre_2028,
            "true_net_post_tax_value_with_wa_2028_tax": net_2028_plus,
            "wa_sb6346_2028_tax_penalty": round(max(0.0, net_pre_2028 - net_2028_plus), 2),
            "total_strike_cost_needed": equity_data.get("total_strike_cost_needed", 0.0),
            "total_tax_drag": equity_data.get("total_tax_drag", 0.0),
            "grants_count": len(grants_list),
            "nso_count": nso_count,
            "rsu_count": rsu_count,
            "companies": companies_summary,
            "grants": [
                {
                    "grant_id": g.get("grant_id"),
                    "nickname": g.get("nickname"),
                    "grant_type": g.get("grant_type", "NSO"),
                    "company_name": g.get("company_name"),
                    "grant_date": g.get("grant_date"),
                    "vesting_completion": g.get("vesting_completion"),
                    "total_granted": g.get("total_granted", 0),
                    "strike_price": g.get("strike_price", 0.0),
                    "unexercised_options": g.get("unexercised_options", 0),
                    "unvested_options": g.get("unvested_options", 0),
                    "owned_shares": g.get("owned_shares", 0),
                    "strike_cost": g.get("strike_cost", 0.0),
                    "spread": g.get("spread", 0.0),
                    "true_net_value": g.get("true_net_value", 0.0),
                }
                for g in grants_list
            ],
            "five_year_projections_at_10_5_pct_cagr": projections_5yr,
            "tax_guidelines": [
                "RSUs vest with $0 strike cost; taxed as ordinary income.",
                "NSOs require strike capital to exercise; spread (FMV - Strike) is taxed as ordinary income at exercise and steps up share cost basis to the exercise FMV.",
                "WA SB 6346 (9.9% Millionaire's Tax on taxable income > $1M) takes effect Jan 1, 2028 (tax years 2028+). Exercising NSOs in 2026–2027 (whether selling immediately or holding) locks in 0% WA state tax on the existing spread; if held and sold later, only post-exercise appreciation above the stepped-up FMV basis is taxed as capital gain.",
            ],
        }
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error evaluating equity schedule for family %s: %s", fam_id, e)
        return {"error": str(e), "status": "unavailable"}


def get_cash_flow_summary(family_id: int = 0) -> Dict[str, Any]:
    """
    Retrieves the household balance sheet, net worth snapshot, liquid cash reserves,
    investable portfolios, liabilities, annual spending, safe withdrawal rate, and family members.
    """
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}

    summary: Dict[str, Any] = {
        "net_worth": 0.0,
        "liquid_cash": 0.0,
        "investments": 0.0,
        "real_estate": 0.0,
        "total_liabilities": 0.0,
        "annual_spending": 0.0,
        "annual_savings": 0.0,
        "retirement_age": 0,
        "safe_withdrawal_rate_pct": 0.0,
        "state_residence": "",
        "tax_filing_status": "MFJ",
        "family_members": [],
    }
    try:
        hp = db.household.get_household_profile(family_id=fam_id, db_path=DB_PATH)
        if hp:
            summary.update({
                "state_residence": str(hp.get("state") or ""),
                "tax_filing_status": str(hp.get("filing_status") or "MFJ"),
                "annual_spending": float(hp.get("annual_spending") or 0.0),
                "annual_savings": float(hp.get("annual_savings") or 0.0),
                "retirement_age": int(hp.get("retirement_age") or 0),
            })
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error loading profile assumptions for cash flow: %s", e)
        return {"error": f"Failed to load household profile: {e}", "status": "unavailable"}

    members = security.get_family_members(DB_PATH, family_id=fam_id) if DB_PATH.exists() else []
    summary["family_members"] = [
        {"name": m.get("name"), "relationship": m.get("relationship"), "birthdate": m.get("birthdate")}
        for m in (members or [])
    ]

    try:
        snap = account_sync.get_financial_snapshot(family_id=fam_id)
        if snap:
            cats = snap.get("categories", {})
            liquid_cash = cats.get("cash_liquid", {}).get("total", snap.get("liquid_cash", 0.0))
            investments = (
                cats.get("public_brokerage", {}).get("total", 0.0)
                + cats.get("retirement", {}).get("total", 0.0)
                + cats.get("private_investments", {}).get("total", 0.0)
            )
            real_estate = cats.get("real_estate", {}).get("total", snap.get("real_estate", 0.0))
            liabilities = cats.get("mortgages", {}).get("total", 0.0) + cats.get("credit_cards", {}).get("total", 0.0)
            nw = snap.get("true_net_worth", snap.get("monarch_reported_net_worth", 0.0))
            summary.update({
                "net_worth": nw,
                "liquid_cash": liquid_cash,
                "real_estate": real_estate,
                "investments": investments if investments > 0 else snap.get("total_investments", snap.get("investments", 0.0)),
                "total_liabilities": liabilities if liabilities > 0 else snap.get("total_liabilities", 0.0),
                "safe_withdrawal_rate_pct": round(summary["annual_spending"] / nw * 100, 2) if (nw > 0 and summary["annual_spending"] > 0) else 0.0,
            })
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error loading balance sheet for cash flow: %s", e)
        return {"error": str(e), "status": "unavailable"}

    return summary


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


def get_estate_tax_summary(
    family_id: int = 0,
    state_override: Optional[str] = None,
    apply_tcja_sunset: Optional[bool] = None,
) -> Dict[str, Any]:
    """Retrieves family estate tax calculations, federal vs. state death taxes, a federal-exemption rollback stress test, and SLAT/IDGT/ILIT trusts."""
    fam_id = _resolve_tool_family_id(family_id)
    if not fam_id:
        return {}
    try:
        kwargs: Dict[str, Any] = {"family_id": fam_id}
        if state_override:
            kwargs["state_override"] = str(state_override).strip().upper()
        if apply_tcja_sunset is not None:
            kwargs["apply_tcja_sunset"] = bool(apply_tcja_sunset)
        return estate_engine.get_family_estate_profile(**kwargs)
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error getting estate tax profile: %s", e)
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


def estimate_equity_exercise_tax(
    family_id: int = 0,
    shares_to_exercise: float = 0.0,
    strike_price: Optional[float] = None,
    share_price: Optional[float] = None,
    grant_type: str = "nso",
    include_wa_millionaire_tax: bool = False,
    tax_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Calculates tax liability, stepped-up cost basis, strike cost, and pre-2028 vs. 2028+ WA SB 6346 net proceeds for exercising options or stock sales."""
    fam_id = _resolve_tool_family_id(family_id)
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
        cf = get_cash_flow_summary(family_id=fam_id)
        filing_status = cf.get("tax_filing_status", "MFJ")
        # The exercise stacks on the whole household's income, not one earner's.
        prior_ordinary_income = household_prior_income(fam_id, db_path=DB_PATH if DB_PATH.exists() else None)

        state = residence_state.normalize(cf.get("state_residence"))
        gtype = grant_type.lower()
        if gtype in ("nso", "rsu"):
            # NSO spread and RSU vest are wages: federal, Medicare and the household's own state income tax.
            if gtype == "rsu":
                spread, strike_cost, effective_strike = gross_value, 0.0, 0.0
            wa_toggle = include_wa_millionaire_tax or (tax_year is not None and tax_year >= 2028)
            tax_res = compensation_option_tax(
                spread, prior_ordinary_income, state, wa_toggle, tax_year, filing_status,
            )
            tax_2028 = compensation_option_tax(spread, prior_ordinary_income, state, True, 2028, filing_status)
            tot_tax = tax_res.get("total_tax", 0.0)
            return {
                "shares": shares_to_exercise,
                "share_price": effective_share_price,
                "strike_price": effective_strike,
                "total_strike_cost": strike_cost,
                "gross_spread": round(spread, 2),
                "stepped_up_cost_basis_after_exercise": gross_value,
                "prior_ordinary_income_used": prior_ordinary_income,
                "state_code": state,
                "federal_tax": tax_res.get("federal_income_tax", 0.0),
                "medicare_tax": tax_res.get("medicare_tax", 0.0),
                "state_income_tax": round(tax_res.get("state_tax", 0.0), 2),
                "wa_state_tax": tax_res.get("wa_state_tax", 0.0),
                "wa_state_tax_pre_2028": 0.0,
                "wa_sb6346_tax_if_exercised_2028_plus": round(tax_2028.get("wa_state_tax", 0.0), 2),
                "total_tax_liability": round(tot_tax, 2),
                "effective_tax_rate_pct": round(tax_res.get("effective_rate", 0.0) * 100, 2),
                "net_take_home_cashless": round(spread - tot_tax, 2),
            }

        sale_tax = stock_sale_tax_for_state(
            gross_value, strike_cost, prior_ordinary_income, state, tax_year, filing_status,
        )
        result = {
            "shares": shares_to_exercise,
            "share_price": effective_share_price,
            "cost_basis": strike_cost,
            "gross_proceeds": gross_value,
            "state_code": state,
            "capital_gain": sale_tax.get("gain", 0.0),
            "federal_ltcg_tax": sale_tax.get("federal_capital_gains_tax", 0.0),
            "niit_tax": sale_tax.get("niit_tax", 0.0),
            "state_capital_gains_tax": round(sale_tax.get("state_capital_gains_tax", 0.0), 2),
            "wa_capital_gains_tax": sale_tax.get("wa_capital_gains_tax", 0.0),
            "total_tax_liability": round(sale_tax.get("total_tax", 0.0), 2),
            "net_proceeds": round(gross_value - strike_cost - sale_tax.get("total_tax", 0.0), 2),
        }
        if gtype == "iso":
            # Exercising and holding ISOs owes no regular tax but triggers AMT on the spread (credit carries forward).
            amt = iso_exercise_amt(spread, prior_ordinary_income, filing_status)
            result.update({
                "amt_preference_if_exercised_and_held": round(amt["amt_preference"], 2),
                "amt_if_exercised_and_held": round(amt["amt"], 2),
                "amt_credit_carryforward": round(amt["amt_credit_carryforward"], 2),
                "amt_credit_recovery_years": amt_credit_recovery_years(
                    amt["amt_credit_carryforward"], prior_ordinary_income, filing_status, tax_year or date.today().year,
                ),
            })
        return result
    except ADVISOR_TOOL_ERRORS as e:
        logger.warning("Error estimating equity exercise tax: %s", e)
        return {"error": str(e), "status": "unavailable"}


get_net_worth_summary = get_cash_flow_summary
get_tax_profile = get_estate_tax_summary
get_monte_carlo_summary = get_monte_carlo_stress_test

__all__ = [
    "_format_historical_backtest_summary",
    "_resolve_tool_family_id",
    "estimate_equity_exercise_tax",
    "get_cash_flow_summary",
    "get_equity_schedule",
    "get_estate_tax_summary",
    "get_monte_carlo_stress_test",
    "get_monte_carlo_summary",
    "get_net_worth_summary",
    "get_portfolio_allocation",
    "get_tax_profile",
    "simulate_financial_scenario",
]
