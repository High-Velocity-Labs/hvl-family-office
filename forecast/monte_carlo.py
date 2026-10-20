"""
forecast/monte_carlo.py: Monte Carlo Simulation & Sequence-of-Returns Crisis Engine.
Executes stochastic geometric Brownian motion portfolio compounding across 1,000–5,000 trials,
computes percentiles (p10, p25, p50, p75, p90) and longevity survival distributions,
and replays historical sequence-of-returns shocks (1929 Crash, 1973 Stagflation, 2000 Dot-Com, 2008 GFC).
"""

from __future__ import annotations
import atexit
from concurrent.futures import ProcessPoolExecutor
import math
import os
import threading
from typing import Dict, Any, Optional

from forecast.monte_carlo_kernel import (
    HISTORICAL_CRISIS_PROFILES,
    _execute_monte_carlo_kernel,
)


_MC_PROCESS_POOL: Optional[ProcessPoolExecutor] = None
_MC_POOL_LOCK = threading.Lock()


def _shutdown_mc_process_pool() -> None:
    global _MC_PROCESS_POOL
    with _MC_POOL_LOCK:
        pool = _MC_PROCESS_POOL
        _MC_PROCESS_POOL = None
    if pool is not None:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


def _get_mc_process_pool() -> ProcessPoolExecutor:
    global _MC_PROCESS_POOL
    if _MC_PROCESS_POOL is None:
        with _MC_POOL_LOCK:
            if _MC_PROCESS_POOL is None:
                _MC_PROCESS_POOL = ProcessPoolExecutor(max_workers=2)
                atexit.register(_shutdown_mc_process_pool)
    return _MC_PROCESS_POOL


def _should_use_mc_process_pool(trials: int) -> bool:
    force_pool = os.getenv("FO_MC_PROCESS_POOL", "").strip()
    if force_pool == "1":
        return True
    if force_pool == "0":
        return False
    if os.getenv("TESTING") == "1" or os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return int(trials) >= 2500


ASSET_CLASS_PARAMS = {
    "us_equity": {"mean": 0.105, "vol": 0.170, "label": "US Equities"},
    "intl_equity": {"mean": 0.085, "vol": 0.190, "label": "International Equities"},
    "bonds": {"mean": 0.045, "vol": 0.060, "label": "Fixed Income / Bonds"},
    "cash": {"mean": 0.035, "vol": 0.010, "label": "Cash & Equivalents"},
    "private_investments": {"mean": 0.120, "vol": 0.240, "label": "Private VC & Angel"},
    "real_estate": {"mean": 0.045, "vol": 0.080, "label": "Real Estate"},
}


def compute_blended_portfolio_stats(
    w_us: float = 0.60,
    w_intl: float = 0.20,
    w_bonds: float = 0.15,
    w_cash: float = 0.05,
    w_private: float = 0.0,
    w_re: float = 0.0,
) -> Dict[str, float]:
    """Computes weighted expected return and diversified portfolio volatility."""
    tot = w_us + w_intl + w_bonds + w_cash + w_private + w_re
    if tot > 0:
        w_us, w_intl, w_bonds, w_cash, w_private, w_re = (
            w_us / tot, w_intl / tot, w_bonds / tot, w_cash / tot, w_private / tot, w_re / tot
        )
    else:
        w_us, w_intl, w_bonds, w_cash, w_private, w_re = 0.60, 0.20, 0.15, 0.05, 0.0, 0.0

    p_us = ASSET_CLASS_PARAMS["us_equity"]
    p_intl = ASSET_CLASS_PARAMS["intl_equity"]
    p_bonds = ASSET_CLASS_PARAMS["bonds"]
    p_cash = ASSET_CLASS_PARAMS["cash"]
    p_pe = ASSET_CLASS_PARAMS["private_investments"]
    p_re = ASSET_CLASS_PARAMS["real_estate"]

    expected_return = (
        (w_us * p_us["mean"]) +
        (w_intl * p_intl["mean"]) +
        (w_bonds * p_bonds["mean"]) +
        (w_cash * p_cash["mean"]) +
        (w_private * p_pe["mean"]) +
        (w_re * p_re["mean"])
    )

    # Simplified variance with cross-asset correlations
    v_direct = (
        (w_us * p_us["vol"]) ** 2 +
        (w_intl * p_intl["vol"]) ** 2 +
        (w_bonds * p_bonds["vol"]) ** 2 +
        (w_cash * p_cash["vol"]) ** 2 +
        (w_private * p_pe["vol"]) ** 2 +
        (w_re * p_re["vol"]) ** 2
    )

    # Cross covariances: rho(US, Intl)=0.75, rho(US, PE)=0.70, rho(US, Bonds)=0.10, rho(Intl, Bonds)=0.15, rho(US, RE)=0.35
    cov = (
        2.0 * w_us * w_intl * 0.75 * p_us["vol"] * p_intl["vol"] +
        2.0 * w_us * w_private * 0.70 * p_us["vol"] * p_pe["vol"] +
        2.0 * w_us * w_bonds * 0.10 * p_us["vol"] * p_bonds["vol"] +
        2.0 * w_intl * w_bonds * 0.15 * p_intl["vol"] * p_bonds["vol"] +
        2.0 * w_us * w_re * 0.35 * p_us["vol"] * p_re["vol"]
    )
    port_vol = math.sqrt(max(0.0009, v_direct + cov))
    port_vol = max(0.03, min(0.30, port_vol))

    return {
        "expected_return": round(expected_return, 4),
        "volatility": round(port_vol, 4),
        "w_us": round(w_us, 4),
        "w_intl": round(w_intl, 4),
        "w_bonds": round(w_bonds, 4),
        "w_cash": round(w_cash, 4),
        "w_private": round(w_private, 4),
        "w_re": round(w_re, 4),
    }


def run_monte_carlo_simulation(
    family_id: int = 0,
    scenario_id: Optional[str] = None,
    trials: int = 1000,
    seed: Optional[int] = 42,
    custom_spending: Optional[float] = None,
    custom_retirement_age: Optional[int] = None,
    precomputed_sim: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Executes a high-performance stochastic Monte Carlo simulation across 1,000 to 5,000 trials
    and replays historical sequence-of-returns crisis shocks (1929, 1973, 2000, 2008).
    Strictly isolated by family_id.
    """
    trials = max(100, min(5000, int(trials or 1000)))
    try:
        from routes.helpers import is_sandbox_session
        if is_sandbox_session():
            trials = min(trials, 1000)
    except Exception:
        pass

    if precomputed_sim is not None and precomputed_sim.get("success"):
        sim_base = precomputed_sim
    else:
        # Import lazily to decouple from circular module initialization
        from forecast.orchestrator import simulate_multi_scenarios
        sim_base = simulate_multi_scenarios(
            family_id=family_id,
            target_scenario_id=scenario_id,
            annual_living_spend=custom_spending,
            primary_retirement_age=custom_retirement_age,
        )
    if not sim_base.get("success"):
        return {"success": False, "error": "Failed to load underlying scenario data."}

    scenarios = sim_base.get("scenarios", [])
    active_id = scenario_id or sim_base.get("active_scenario_id") or "scen_baseline"
    target_scen = next((s for s in scenarios if s.get("id") == active_id), scenarios[0] if scenarios else {})
    scorecard_entry = next((s for s in sim_base.get("scorecard", []) if s.get("id") == active_id), {})

    scen_schedules = sim_base.get("scenario_schedules", {})
    schedule = scen_schedules.get(active_id) or sim_base.get("active_schedule", [])
    if not schedule:
        return {"success": False, "error": "No simulation schedule available."}

    inflation_rate = float(sim_base.get("inflation_rate") or 0.025)

    # Extract asset allocation weights
    w_us = float(target_scen.get("weight_us_equity") or 0.60)
    w_intl = float(target_scen.get("weight_intl_equity") or 0.20)
    w_bonds = float(target_scen.get("weight_bonds") or 0.15)
    w_cash = float(target_scen.get("weight_cash") or 0.05)
    w_pe = float(target_scen.get("weight_private_investments") or 0.0)
    w_re = float(target_scen.get("weight_real_estate") or 0.0)

    port_stats = compute_blended_portfolio_stats(w_us, w_intl, w_bonds, w_cash, w_pe, w_re)
    mu_port = port_stats["expected_return"]
    sigma_port = port_stats["volatility"]

    # Starting portfolio balance (liquid + retirement)
    s0 = schedule[0]
    initial_liquid = float(s0.get("liquid_assets", 0.0) + s0.get("retirement_assets", 0.0))
    initial_re = float(s0.get("real_estate_net", 0.0))
    initial_equity = float(s0.get("company_equity", 0.0))
    initial_total_nw = initial_liquid + initial_re + initial_equity

    years = [int(s["year"]) for s in schedule]
    ages_primary = [int(s.get("age_primary", s.get("age", 45))) for s in schedule]
    num_years = len(years)

    # Net cash flows per year from deterministic baseline
    yearly_net_cf = []
    yearly_re_equity = []
    yearly_comp_equity = []
    yearly_non_liquid = []
    for s in schedule:
        cf_net = float(s.get("net_cash_flow", 0.0))
        re_eq = float(s.get("real_estate_net", 0.0))
        comp_eq = float(s.get("company_equity", 0.0))
        yearly_net_cf.append(cf_net)
        yearly_re_equity.append(re_eq)
        yearly_comp_equity.append(comp_eq)
        yearly_non_liquid.append(re_eq + comp_eq)

    # Real expected return using Fisher equation: (1 + r_nom) / (1 + inf) - 1
    # Ensures portfolio compounding, cash flows, and balance sheet assets compound consistently in Today's Real Dollars.
    mu_real = ((1.0 + mu_port) / (1.0 + inflation_rate)) - 1.0
    drift = mu_real - 0.5 * (sigma_port ** 2)

    ret_readiness = scorecard_entry.get("retirement_readiness", {})
    planned_ret_yr = int(ret_readiness.get("primary_planned_year", 2035))

    raw_guardrail = target_scen.get("spending_guardrail_mode") or "off"
    spending_guardrail_mode = str(raw_guardrail).lower().strip()
    if spending_guardrail_mode not in ("moderate", "aggressive"):
        spending_guardrail_mode = "off"

    kernel_kwargs = dict(
        trials=trials,
        seed=seed,
        num_years=num_years,
        years=years,
        ages_primary=ages_primary,
        initial_liquid=initial_liquid,
        initial_re=initial_re,
        initial_equity=initial_equity,
        initial_total_nw=initial_total_nw,
        yearly_net_cf=yearly_net_cf,
        yearly_re_equity=yearly_re_equity,
        yearly_comp_equity=yearly_comp_equity,
        yearly_non_liquid=yearly_non_liquid,
        mu_real=mu_real,
        drift=drift,
        sigma_port=sigma_port,
        inflation_rate=inflation_rate,
        planned_ret_yr=planned_ret_yr,
        port_stats=port_stats,
        active_id=active_id,
        scenario_name=target_scen.get("name", "Active Scenario"),
        spending_guardrail_mode=spending_guardrail_mode,
    )

    if _should_use_mc_process_pool(trials):
        try:
            pool = _get_mc_process_pool()
            future = pool.submit(_execute_monte_carlo_kernel, **kernel_kwargs)
            return future.result(timeout=30.0)
        except Exception:
            pass

    return _execute_monte_carlo_kernel(**kernel_kwargs)
