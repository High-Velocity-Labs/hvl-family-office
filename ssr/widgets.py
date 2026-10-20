"""
Per-household customizable & reorderable Data Widgets engine for Overview and Forecasting.
Persists widget selections and sort order per household in `families.settings`
and computes live data payloads driven by the household balance sheet and Active Plan.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

import security
from routes.helpers import DB_PATH
from ssr.formatting import fmt_currency, fmt_short_currency
from ssr.widgets_charts import (
    build_widget_chart_payloads,
    get_collapsed_charts,
    save_collapsed_chart_state,
)

logger = logging.getLogger(__name__)

OVERVIEW_WIDGET_CATALOG: List[Dict[str, Any]] = [
    {"id": "ov_kpi_grid", "title": "Balance Sheet KPI Grid", "subtitle": "Consolidated net worth, aggregator total, company equity, liquid portfolio, real estate, private NAV, and retirement", "default_on": True, "core": True, "full_width": True, "badge": "Core"},
    {"id": "ov_net_worth_chart", "title": "5-Year Net Worth & Historical Trajectory", "subtitle": "Interactive 5-year projection and 2009–2026 Monarch historical actuals chart", "default_on": True, "full_width": False, "badge": "Chart"},
    {"id": "ov_allocation_chart", "title": "Asset Allocation Breakdown", "subtitle": "Total net worth and liquid public security distribution chart", "default_on": True, "full_width": False, "badge": "Chart"},
    {"id": "ov_lifetime_forecast_chart", "title": "Multi-Scenario Lifetime Net Worth Forecast (2026–2078)", "subtitle": "Interactive multi-decade wealth trajectory with scenario switcher pills and Real/Nominal toggle", "default_on": False, "full_width": True, "badge": "Chart"},
    {"id": "ov_cash_flow_chart", "title": "Active Plan Cash Flow & Tax Drawdown Graph", "subtitle": "Multi-year inflows (Salary, SS, Equity) vs. living spend, taxes, and portfolio withdrawals", "default_on": False, "full_width": False, "badge": "Chart"},
    {"id": "ov_monte_carlo_chart", "title": "Monte Carlo Wealth Fan (P10–P90)", "subtitle": "Stochastic percentile trajectory bands (P10 / P25 / P50 / P75 / P90) for the active plan", "default_on": False, "full_width": False, "badge": "Chart"},
    {"id": "ov_career_comp_chart", "title": "Career Compensation Trajectory Graph", "subtitle": "Historical W-2 base salary and realized bonus progression across career years", "default_on": False, "full_width": False, "badge": "Chart"},
    {"id": "ov_retirement_readiness", "title": "Active Plan Retirement Readiness & FI Progress", "subtitle": "Primary & Spouse retirement ages, Monte Carlo solvency, and 25× FI benchmark from your active plan", "default_on": True, "full_width": True, "badge": "Active Plan"},
    {"id": "ov_steady_state_burn", "title": "Steady-State FIRE Burn Waterfall", "subtitle": "Strips out mortgage P&I and temporary kid/education costs to isolate perpetual retirement burn & Core 25× FI target", "default_on": False, "full_width": False, "badge": "Active Plan"},
    {"id": "ov_crisis_survival", "title": "Historical Cohort Backtest (1928–2025)", "subtitle": "Active plan survival across all 98 rolling historical market cohorts plus 1929, 1966, 2000, and 2008 crash replays", "default_on": False, "full_width": False, "badge": "Active Plan"},
    {"id": "ov_roth_tax_window", "title": "Roth Conversion & Tax-Bracket Window", "subtitle": "Low-tax retirement bridge window between planned retirement and Age 73/75 RMDs", "default_on": False, "full_width": False, "badge": "Active Plan"},
    {"id": "ov_equity_vesting", "title": "Company Equity & Post-Tax Liquidity", "subtitle": "Gross equity valuation, strike + tax drag, post-tax net value, and net worth concentration", "default_on": False, "full_width": False, "badge": "Equity"},
    {"id": "ov_needs_attention", "title": "Survivorship & Readiness Audit", "subtitle": "Deterministic checks across probate exposure, beneficiary designations, runway, and tax gaps", "default_on": False, "full_width": False, "badge": "Helm Audit"},
]

SCENARIOS_WIDGET_CATALOG: List[Dict[str, Any]] = [
    {"id": "scen_chart_networth", "title": "Lifetime Net Worth Trajectory (2018–2078)", "subtitle": "Core multi-scenario wealth trajectory across historical actuals and projected decades", "default_on": True, "core": True, "full_width": True, "badge": "Core"},
    {"id": "scen_retirement_readiness", "title": "Retirement Readiness & Timing (\"When Can You Retire?\")", "subtitle": "Primary & Spouse retirement eligibility, earliest feasible retirement year, and 25× FI benchmark progress", "default_on": True, "core": True, "full_width": True, "badge": "Core KPI"},
    {"id": "scen_chart_cashflow", "title": "Cash Flow (Income vs. Spend) — Sankey & Timeline", "subtitle": "Single-year Cash Flow Sankey diagram (default) and multi-year layered cash flow timeline bars", "default_on": True, "full_width": True, "badge": "Graph"},
    {"id": "scen_chart_longevity", "title": "Longevity & Solvency (SSA Actuarial)", "subtitle": "100% stacked area SSA actuarial survival probabilities alongside portfolio solvency", "default_on": False, "full_width": True, "badge": "Graph"},
    {"id": "scen_chart_montecarlo", "title": "Monte Carlo Stress Test & Historical Backtest", "subtitle": "1,000-trial stochastic percentile corridors, 1928–2025 rolling cohort backtest, and named crisis replays", "default_on": False, "full_width": True, "badge": "Graph"},
    {"id": "scen_steady_state_burn", "title": "Steady-State FIRE Burn Waterfall", "subtitle": "Decomposes current plan spending into Mortgage P&I payoff, temporary child/college events, and Core Perpetual Burn", "default_on": False, "full_width": False, "badge": "Active Plan"},
    {"id": "scen_crisis_survival", "title": "Historical Cohort Survival Summary (1928–2025)", "subtitle": "Compact summary card of rolling historical cohort survival rate and 4 toughest crash eras", "default_on": False, "full_width": False, "badge": "Active Plan"},
    {"id": "scen_roth_tax_window", "title": "Roth Conversion & RMD Tax Window", "subtitle": "Low-tax bridge years between planned retirement and Age 73/75 RMDs with average effective tax rate", "default_on": False, "full_width": False, "badge": "Tax Strategy"},
    {"id": "scen_pre65_healthcare", "title": "Pre-65 Healthcare Bridge (ACA / COBRA Window)", "subtitle": "Years before Age 65 Medicare eligibility for Primary & Spouse and estimated cumulative bridge healthcare cost", "default_on": False, "full_width": False, "badge": "Healthcare"},
    {"id": "scen_milestone_kpis", "title": "Milestone Net Worth & Solvency Cards", "subtitle": "4-card summary strip for Liquid Capital Today, Net Worth @ 65 vs. Baseline, Terminal Wealth @ 100, and Solvency", "default_on": False, "full_width": True, "badge": "KPI Strip"},
]


def _get_catalog(page: str) -> List[Dict[str, Any]]:
    return OVERVIEW_WIDGET_CATALOG if page == "overview" else SCENARIOS_WIDGET_CATALOG


def get_default_widget_ids(page: str) -> List[str]:
    return [w["id"] for w in _get_catalog(page) if w.get("default_on")]


def _ensure_core_widgets(page: str, ids: List[str]) -> List[str]:
    core_ids = [w["id"] for w in _get_catalog(page) if w.get("core")]
    missing = [cid for cid in core_ids if cid not in ids]
    return missing + ids


def _parse_widget_csv(page: str, raw_val: str, valid_ids: set[str], defaults: List[str]) -> List[str]:
    raw_str = str(raw_val).strip()
    if raw_str == "default":
        return defaults
    if raw_str in ("none", ""):
        return _ensure_core_widgets(page, [])
    seen_q: set[str] = set()
    filtered_q: List[str] = []
    for wid in raw_str.split(","):
        s_wid = wid.strip()
        if s_wid in valid_ids and s_wid not in seen_q:
            seen_q.add(s_wid)
            filtered_q.append(s_wid)
    return _ensure_core_widgets(page, filtered_q)


def get_household_widget_ids(family_id: int, page: str) -> List[str]:
    """Returns the ordered list of enabled widget IDs for the given household and page."""
    catalog = _get_catalog(page)
    valid_ids = {w["id"] for w in catalog}
    defaults = get_default_widget_ids(page)
    try:
        from urllib.parse import unquote
        from flask import has_request_context, request, session
        from routes.helpers import get_current_universe
        if has_request_context():
            raw_w = request.args.get("widgets")
            if raw_w is not None:
                return _parse_widget_csv(page, str(raw_w), valid_ids, defaults)
            is_demo_or_viewer = bool(
                session.get("is_demo")
                or get_current_universe() == "demo"
                or session.get("role") == "viewer"
                or request.args.get("demo") == "1"
            )
            if is_demo_or_viewer:
                cookie_val = request.cookies.get(f"hvl_widgets_{page}")
                if cookie_val is not None:
                    return _parse_widget_csv(page, unquote(str(cookie_val)), valid_ids, defaults)
    except Exception:
        pass
    if family_id <= 0:
        return defaults
    try:
        fam = security.get_family(Path(DB_PATH), family_id=family_id) or {}
        settings = fam.get("settings") if isinstance(fam.get("settings"), dict) else {}
        key = "overview_widgets" if page == "overview" else "scenarios_widgets"
        saved = settings.get(key)
        if isinstance(saved, list):
            seen = set()
            filtered = []
            for wid in saved:
                s_wid = str(wid).strip()
                if s_wid in valid_ids and s_wid not in seen:
                    seen.add(s_wid)
                    filtered.append(s_wid)
            return _ensure_core_widgets(page, filtered)
    except Exception as e:
        logger.debug("Could not load household widget preferences for family %s: %s", family_id, e)
    return defaults


def save_household_widget_ids(family_id: int, page: str, active_ids: List[str] | None) -> List[str]:
    """Saves the ordered list of enabled widget IDs for a household (`overview` or `scenarios`)."""
    if page not in ("overview", "scenarios"):
        raise ValueError("Invalid widget page; must be 'overview' or 'scenarios'")
    catalog = _get_catalog(page)
    valid_ids = {w["id"] for w in catalog}
    if active_ids is None:
        final_ids = get_default_widget_ids(page)
    else:
        seen = set()
        final_ids = []
        for wid in active_ids:
            s_wid = str(wid).strip()
            if s_wid in valid_ids and s_wid not in seen:
                seen.add(s_wid)
                final_ids.append(s_wid)
        final_ids = _ensure_core_widgets(page, final_ids)

    fam = security.get_family(Path(DB_PATH), family_id=family_id) or {}
    settings = dict(fam.get("settings") or {}) if isinstance(fam.get("settings"), dict) else {}
    key = "overview_widgets" if page == "overview" else "scenarios_widgets"
    settings[key] = final_ids
    security.update_family(Path(DB_PATH), family_id=family_id, settings=settings)
    return final_ids


def _fmt_compact(val: float) -> str:
    if abs(val) >= 1e9:
        return f"{'-' if val < 0 else ''}${abs(val) / 1e9:,.2f}B"
    return fmt_short_currency(val)


def _compute_plan_analytics(ssr_scenarios: Dict[str, Any], sim: Dict[str, Any], snapshot: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Computes live active-plan data for Steady-State Burn, Crisis Survival, Roth Window, Pre-65 ACA, and Equity."""
    gross_spend = float(ssr_scenarios.get("annual_living_spend") or sim.get("annual_living_spend") or 0.0)
    sched = sim.get("active_schedule") or []
    cf_series = sim.get("active_cash_flow_series") or []

    # 1. Steady-State FIRE Burn Waterfall
    mort_principal = 0.0
    if snapshot:
        mort_principal = abs(float(((snapshot.get("categories") or {}).get("mortgages") or {}).get("total") or 0.0))
    if mort_principal <= 0 and sched:
        mort_principal = abs(float(sched[0].get("mortgage_balance") or 0.0))

    annual_mort_pi = round(mort_principal * 0.068, -2) if mort_principal > 10000 else 0.0
    if gross_spend > 0 and annual_mort_pi > gross_spend * 0.40:
        annual_mort_pi = round(gross_spend * 0.28, -2)

    mort_payoff_yr = 2026 + max(5, min(25, int(round(mort_principal / max(24000.0, annual_mort_pi))))) if annual_mort_pi > 0 else None

    events = ssr_scenarios.get("events") or []
    edu_cats = {"college", "grad_school", "education", "new_child", "wedding", "child_home_gift", "superfund_529"}
    edu_events = [e for e in events if str(e.get("category") or "").lower() in edu_cats]
    kids_annual_est = round(gross_spend * 0.12, -2) if (edu_events or (sim.get("children_edu") and gross_spend > 0)) else 0.0

    core_burn = max(gross_spend * 0.50, gross_spend - annual_mort_pi - kids_annual_est) if gross_spend > 0 else 0.0
    gross_fi_target = gross_spend * 25.0
    core_fi_target = core_burn * 25.0
    fi_savings_delta = max(0.0, gross_fi_target - core_fi_target)

    # 2. Historical Cohort Backtest (1928-2025) & Crisis Survival
    active_mc = sim.get("active_monte_carlo") or {}
    hist = active_mc.get("historical_cohorts") or active_mc.get("historical_backtest") or {}
    hist_rate = hist.get("survival_rate_age_100", hist.get("survival_rate"))
    survived_cnt = int(hist.get("survived_cohorts") or 0)
    total_cnt = int(hist.get("total_cohorts") or 0)
    worst_raw = hist.get("worst_cohorts") or []
    worst_cohorts = []
    for c in worst_raw[:4]:
        trough_num = float(c.get("trough_net_worth", c.get("min_wealth", 0.0)) or 0.0)
        term_num = float(c.get("terminal_net_worth", c.get("terminal_wealth", 0.0)) or 0.0)
        worst_cohorts.append({
            "start_year": c.get("start_year") or "--",
            "label": c.get("label") or f"{c.get('start_year', '')} Cohort",
            "survived": bool(c.get("survived", True)),
            "trough_str": _fmt_compact(trough_num),
            "terminal_str": _fmt_compact(term_num),
        })

    # 3. Roth Conversion & Tax-Bracket Window (Retirement -> Age 73 RMDs)
    p_cur_age = int(ssr_scenarios.get("primary_current_age") or 49)
    s_cur_age = int(ssr_scenarios.get("spouse_current_age") or 47)
    p_ret_age = int(ssr_scenarios.get("primary_ret_age") or 50)
    s_ret_age = int(ssr_scenarios.get("spouse_ret_age") or 52)
    p_ret_yr = int(ssr_scenarios.get("primary_ret_yr") or (2026 + max(0, p_ret_age - p_cur_age)))
    rmd_age = 75 if (2026 - p_cur_age) >= 1960 else 73
    rmd_start_yr = 2026 + max(0, rmd_age - p_cur_age)
    roth_window_years = max(0, rmd_start_yr - p_ret_yr)

    ret_tax_rates = []
    for c_row in cf_series:
        yr = int(c_row.get("year") or 0)
        if p_ret_yr <= yr < rmd_start_yr:
            inf = float(c_row.get("total_inflow") or 0.0)
            tx = float(c_row.get("taxes") or c_row.get("tax_paid") or 0.0)
            if inf > 0:
                ret_tax_rates.append((tx / inf) * 100.0)
    avg_ret_tax_pct = f"{(sum(ret_tax_rates) / len(ret_tax_rates)):.1f}%" if ret_tax_rates else "12.0%–18.0%"

    # 4. Pre-65 Healthcare Bridge (ACA / COBRA Window)
    p_bridge_yrs = max(0, 65 - p_ret_age)
    s_bridge_yrs = max(0, 65 - s_ret_age)
    max_bridge_yrs = max(p_bridge_yrs, s_bridge_yrs)
    annual_aca_est = (28000.0 if (p_bridge_yrs > 0 and s_bridge_yrs > 0) else 15000.0) if max_bridge_yrs > 0 else 0.0
    total_aca_bridge_est = (p_bridge_yrs * 14000.0) + (s_bridge_yrs * 14000.0)

    # 5. Company Equity Concentration & Post-Tax Liquidity
    eq_data = (snapshot or {}).get("company_equity") or {}
    true_nw_num = float((snapshot or {}).get("true_net_worth") or 0.0)
    eq_net_num = float(eq_data.get("true_net_post_tax_value") or 0.0)
    eq_gross_num = float(eq_data.get("total_gross_equity_value") or 0.0)
    eq_drag_num = float(eq_data.get("total_tax_drag") or 0.0) + float(eq_data.get("total_strike_cost_needed") or 0.0)
    eq_conc_pct = f"{(eq_net_num / true_nw_num * 100.0):.1f}%" if true_nw_num > 0 else "--"

    return {
        "plan_name": ssr_scenarios.get("plan_name") or "Baseline Plan",
        "gross_spend_str": fmt_short_currency(gross_spend) if gross_spend > 0 else "--",
        "mort_pi_str": fmt_short_currency(annual_mort_pi) if annual_mort_pi > 0 else "--",
        "mort_payoff_yr": mort_payoff_yr or "Paid Off",
        "kids_annual_str": fmt_short_currency(kids_annual_est) if kids_annual_est > 0 else "--",
        "core_burn_str": fmt_short_currency(core_burn) if core_burn > 0 else "--",
        "gross_fi_str": fmt_short_currency(gross_fi_target) if gross_fi_target > 0 else "--",
        "core_fi_str": fmt_short_currency(core_fi_target) if core_fi_target > 0 else "--",
        "fi_delta_str": fmt_short_currency(fi_savings_delta) if fi_savings_delta > 0 else "--",
        "hist_survival_pct": f"{hist_rate:.0f}%" if isinstance(hist_rate, (int, float)) else (ssr_scenarios.get("solv_rate_display") or "--"),
        "hist_cohorts_str": f"{survived_cnt}/{total_cnt} Historical Cohorts Solvent" if total_cnt > 0 else "1928–2025 S&P 500 + Bond Sequence",
        "worst_cohorts": worst_cohorts,
        "roth_window_years": roth_window_years,
        "roth_window_range": f"{p_ret_yr}–{rmd_start_yr}" if roth_window_years > 0 else f"At/After Age {rmd_age}",
        "rmd_start_yr": rmd_start_yr,
        "rmd_age": rmd_age,
        "avg_ret_tax_pct": avg_ret_tax_pct,
        "p_bridge_yrs": p_bridge_yrs,
        "s_bridge_yrs": s_bridge_yrs,
        "max_bridge_yrs": max_bridge_yrs,
        "annual_aca_str": fmt_short_currency(annual_aca_est) if annual_aca_est > 0 else "--",
        "total_aca_bridge_str": fmt_short_currency(total_aca_bridge_est) if total_aca_bridge_est > 0 else "--",
        "eq_company_name": eq_data.get("company_name") or "Company Equity",
        "eq_gross_str": fmt_currency(eq_gross_num, 0) if eq_gross_num > 0 else "--",
        "eq_drag_str": fmt_short_currency(eq_drag_num) if eq_drag_num > 0 else "--",
        "eq_net_str": fmt_currency(eq_net_num, 0) if eq_net_num > 0 else "--",
        "eq_conc_pct": eq_conc_pct,
    }


def _package_widget_state(
    page: str,
    active_ids: List[str],
    analytics: Dict[str, Any],
    family_id: int = 0,
    ssr_scen: Dict[str, Any] | None = None,
    sim: Dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> Dict[str, Any]:
    catalog = _get_catalog(page)
    cat_by_id = {w["id"]: w for w in catalog}
    active_set = set(active_ids)
    active_items = [cat_by_id[wid] for wid in active_ids if wid in cat_by_id]
    ordered_catalog = [
        {**w, "enabled": (w["id"] in active_set), "order_idx": idx}
        for idx, w in enumerate(catalog)
    ]
    collapsed_charts = get_collapsed_charts(family_id, db_path=db_path)
    chart_payloads = build_widget_chart_payloads(
        family_id=family_id, ssr_scen=ssr_scen, sim=sim, db_path=db_path
    )
    return {
        "page": page,
        "active_ids": active_ids,
        "active_items": active_items,
        "ordered_catalog": ordered_catalog,
        "analytics": analytics,
        "collapsed_charts": collapsed_charts,
        "chart_payloads": chart_payloads,
    }


def build_scenarios_widgets(
    family_id: int,
    ssr_scenarios: Dict[str, Any],
    sim: Dict[str, Any],
    db_path: Path | None = None,
) -> Dict[str, Any]:
    """Builds the ordered widget state and analytics for the Forecasting (Scenarios) page."""
    active_ids = get_household_widget_ids(family_id, "scenarios")
    analytics = _compute_plan_analytics(ssr_scenarios, sim, snapshot=None)
    return _package_widget_state(
        "scenarios", active_ids, analytics, family_id=family_id, ssr_scen=ssr_scenarios, sim=sim, db_path=db_path
    )


def build_overview_widgets(
    family_id: int,
    snapshot: Dict[str, Any] | None,
    db_path: Path | None = None,
) -> Dict[str, Any]:
    """Builds the ordered widget state and active-plan analytics for the Overview page."""
    active_ids = get_household_widget_ids(family_id, "overview")
    ssr_scen: Dict[str, Any] = {}
    sim: Dict[str, Any] = {}
    if family_id > 0:
        try:
            from ssr.scenarios import build_ssr_scenarios
            ssr_scen, sim = build_ssr_scenarios(family_id=family_id)
        except Exception as e:
            logger.debug("Could not load scenarios for overview widgets: %s", e)
    analytics = _compute_plan_analytics(ssr_scen, sim, snapshot=snapshot)
    if family_id > 0:
        try:
            from services.household_audit_service import evaluate_household_risks
            analytics["needs_attention"] = evaluate_household_risks(family_id=family_id)
        except Exception as e:
            logger.debug("Could not run audit for overview widgets: %s", e)
    state = _package_widget_state(
        "overview", active_ids, analytics, family_id=family_id, ssr_scen=ssr_scen, sim=sim, db_path=db_path
    )
    state["ssr_scenarios"] = ssr_scen
    return state


def build_household_widgets_context(
    family_id: int = 0,
    page: str = "overview",
    ssr_scen: Dict[str, Any] | None = None,
    sim: Dict[str, Any] | None = None,
    snapshot: Dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> Dict[str, Any]:
    """Builds unified household widgets context with chart payloads and collapsed chart state."""
    if page == "overview":
        return build_overview_widgets(family_id=family_id, snapshot=snapshot, db_path=db_path)
    return build_scenarios_widgets(
        family_id=family_id, ssr_scenarios=ssr_scen or {}, sim=sim or {}, db_path=db_path
    )
