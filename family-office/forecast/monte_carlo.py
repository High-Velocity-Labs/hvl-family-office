"""
forecast/monte_carlo.py: Monte Carlo Simulation & Sequence-of-Returns Crisis Engine.
Executes stochastic geometric Brownian motion portfolio compounding across 1,000–5,000 trials,
computes percentiles (p10, p25, p50, p75, p90) and longevity survival distributions,
and replays historical sequence-of-returns shocks (1929 Crash, 1973 Stagflation, 2000 Dot-Com, 2008 GFC).
"""

from __future__ import annotations
import atexit
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool
import math
import multiprocessing
import os
import threading
from typing import Dict, Any, Optional

from forecast.hierarchy import normalize_guardrail_mode
from forecast.dollar_basis import dollar_basis_for_view
from forecast.capital_market_assumptions import (
    ASSET_CLASS_ASSUMPTIONS,
    SCENARIO_GROWTH_FIELDS,
)
from forecast.monte_carlo_kernel import (
    HISTORICAL_CRISIS_PROFILES,
    _execute_monte_carlo_kernel,
)


_MC_PROCESS_POOL: Optional[ProcessPoolExecutor] = None
# Guards only this process's pool handle across its request threads; it never coordinates processes.
_MC_POOL_LOCK = threading.Lock()
MC_POOL_TIMEOUT_SECONDS = 30.0


class MonteCarloPoolError(RuntimeError):
    """The Monte Carlo worker pool timed out or broke; the job was cancelled, not re-run inline."""


def _discard_mc_process_pool(pool: ProcessPoolExecutor) -> None:
    """Stops `pool`'s workers (including a job already running) and forgets it if it is the live pool."""
    global _MC_PROCESS_POOL
    with _MC_POOL_LOCK:
        if _MC_PROCESS_POOL is pool:
            _MC_PROCESS_POOL = None
    pool.shutdown(wait=False, cancel_futures=True)
    pool.terminate_workers()


def _shutdown_mc_process_pool() -> None:
    global _MC_PROCESS_POOL
    with _MC_POOL_LOCK:
        pool = _MC_PROCESS_POOL
        _MC_PROCESS_POOL = None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def _get_mc_process_pool() -> ProcessPoolExecutor:
    """The shared pool. `forkserver` workers never inherit the threaded parent's locks or open DB handles."""
    global _MC_PROCESS_POOL
    with _MC_POOL_LOCK:
        if _MC_PROCESS_POOL is None:
            _MC_PROCESS_POOL = ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("forkserver"))
            atexit.register(_shutdown_mc_process_pool)
        return _MC_PROCESS_POOL


def _run_kernel_in_pool(kernel_kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Runs the kernel in the pool; on timeout or a broken pool, kills the workers and raises."""
    pool = _get_mc_process_pool()
    future = pool.submit(_execute_monte_carlo_kernel, **kernel_kwargs)
    try:
        return future.result(timeout=MC_POOL_TIMEOUT_SECONDS)
    except FutureTimeoutError as exc:
        future.cancel()
        _discard_mc_process_pool(pool)
        raise MonteCarloPoolError(f"Monte Carlo timed out after {MC_POOL_TIMEOUT_SECONDS:.0f}s") from exc
    except BrokenProcessPool as exc:
        _discard_mc_process_pool(pool)
        raise MonteCarloPoolError("Monte Carlo worker pool broke") from exc


def _should_use_mc_process_pool(trials: int) -> bool:
    force_pool = os.getenv("FO_MC_PROCESS_POOL", "").strip()
    if force_pool == "1":
        return True
    if force_pool == "0":
        return False
    if os.getenv("TESTING") == "1" or os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return int(trials) >= 2500


ASSET_CLASS_PARAMS = ASSET_CLASS_ASSUMPTIONS


def compute_blended_portfolio_stats(
    w_us: float = 0.60,
    w_intl: float = 0.20,
    w_bonds: float = 0.15,
    w_cash: float = 0.05,
    w_private: float = 0.0,
    w_re: float = 0.0,
    means: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Computes weighted expected (nominal) return and diversified portfolio volatility.
    `means` overrides the table's per-asset-class means (e.g. a scenario's growth assumptions).
    """
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

    mean = {asset: float(params["mean"]) for asset, params in ASSET_CLASS_PARAMS.items()}
    mean.update(means or {})
    expected_return = (
        (w_us * mean["us_equity"]) +
        (w_intl * mean["intl_equity"]) +
        (w_bonds * mean["bonds"]) +
        (w_cash * mean["cash"]) +
        (w_private * mean["private_investments"]) +
        (w_re * mean["real_estate"])
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
    *,
    sandbox: bool,
) -> Dict[str, Any]:
    """
    Executes a high-performance stochastic Monte Carlo simulation across 1,000 to 5,000 trials
    and replays historical sequence-of-returns crisis shocks (1929, 1973, 2000, 2008).
    Strictly isolated by family_id. `sandbox` is required: True caps trials at 1,000.
    Raises MonteCarloPoolError if the process pool times out or breaks.
    """
    trials = max(100, min(5000, int(trials or 1000)))
    if sandbox:
        trials = min(trials, 1000)

    if precomputed_sim is not None:
        # A supplied simulation may be an unsaved plan; never silently swap in the stored one.
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

    # The orchestrator resolved the scenario's plan; Monte Carlo takes those values and has no defaults of its own.
    raw_inflation = target_scen.get("inflation_rate")
    if raw_inflation is None:
        raw_inflation = sim_base.get("inflation_rate")
    planned_year = scorecard_entry.get("retirement_readiness", {}).get("primary_planned_year")
    if raw_inflation is None or planned_year is None:
        return {"success": False, "error": "Scenario has no resolved inflation rate or planned retirement year."}
    inflation_rate = float(raw_inflation)

    # The household's real allocation and the scenario's own return assumptions (set by the orchestrator).
    weights = target_scen.get("portfolio_weights")
    if not weights:
        return {"success": False, "error": "Scenario has no portfolio allocation."}
    means = {
        asset: float(target_scen[field])
        for asset, field in SCENARIO_GROWTH_FIELDS.items()
        if target_scen.get(field) is not None
    }
    port_stats = compute_blended_portfolio_stats(
        float(weights.get("us_equity", 0.0)), float(weights.get("intl_equity", 0.0)),
        float(weights.get("bonds", 0.0)), float(weights.get("cash", 0.0)),
        float(weights.get("private_investments", 0.0)), float(weights.get("real_estate", 0.0)),
        means=means,
    )
    mu_port = port_stats["expected_return"]
    sigma_port = port_stats["volatility"]

    # The kernel works in today's dollars; `to_todays_dollars` makes that independent of the view mode.
    s0 = schedule[0]
    f0 = float(s0["to_todays_dollars"])
    initial_liquid = float(s0.get("liquid_assets", 0.0) + s0.get("retirement_assets", 0.0)) * f0
    initial_re = float(s0.get("real_estate_net", 0.0)) * f0
    initial_equity = float(s0.get("company_equity", 0.0)) * f0
    initial_total_nw = initial_liquid + initial_re + initial_equity

    years = [int(s["year"]) for s in schedule]
    ages_primary = [int(s["age_primary"]) for s in schedule]
    num_years = len(years)

    # Net cash flows per year from deterministic baseline
    yearly_net_cf = []
    yearly_re_equity = []
    yearly_comp_equity = []
    yearly_non_liquid = []
    for s in schedule:
        to_today = float(s["to_todays_dollars"])
        cf_net = float(s.get("net_cash_flow", 0.0)) * to_today
        re_eq = float(s.get("real_estate_net", 0.0)) * to_today
        comp_eq = float(s.get("company_equity", 0.0)) * to_today
        yearly_net_cf.append(cf_net)
        yearly_re_equity.append(re_eq)
        yearly_comp_equity.append(comp_eq)
        yearly_non_liquid.append(re_eq + comp_eq)

    # Real expected return using Fisher equation: (1 + r_nom) / (1 + inf) - 1
    # The table and scenario means are nominal and every series above is in today's dollars.
    mu_real = ((1.0 + mu_port) / (1.0 + inflation_rate)) - 1.0
    drift = math.log(1.0 + mu_real) - 0.5 * (sigma_port ** 2)

    planned_ret_yr = int(planned_year)

    spending_guardrail_mode = normalize_guardrail_mode(target_scen.get("spending_guardrail_mode"))

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
        result = _run_kernel_in_pool(kernel_kwargs)
    else:
        result = _execute_monte_carlo_kernel(**kernel_kwargs)

    display_factor_by_year = {int(s["year"]): 1.0 / float(s["to_todays_dollars"]) for s in schedule}
    out = _in_schedule_dollars(result, display_factor_by_year, years[-1])
    out["dollar_basis"] = dollar_basis_for_view(sim_base.get("view_mode"))
    return out


_TIMELINE_MONEY_KEYS = ("p10", "p25", "p50", "p75", "p90", "net_worth")
_TERMINAL_MONEY_KEYS = ("median_terminal_wealth", "p10_terminal_wealth", "p90_terminal_wealth", "terminal_net_worth")


def _in_schedule_dollars(node: Any, factor_by_year: Dict[int, float], last_year: int) -> Any:
    """
    The kernel works in today's dollars. Re-expresses its amounts in the dollars of the schedule it
    was given (future dollars in nominal view), so bands overlay the plan's net-worth lines.
    Success rates and percentages are unit-free and unchanged.
    """
    if isinstance(node, list):
        return [_in_schedule_dollars(item, factor_by_year, last_year) for item in node]
    if not isinstance(node, dict):
        return node
    out = {k: _in_schedule_dollars(v, factor_by_year, last_year) for k, v in node.items()}
    if "year" in out:
        f = factor_by_year.get(int(out["year"]), 1.0)
        for key in _TIMELINE_MONEY_KEYS:
            if isinstance(out.get(key), (int, float)):
                out[key] = round(out[key] * f, 2)
    terminal_f = factor_by_year.get(last_year, 1.0)
    for key in _TERMINAL_MONEY_KEYS:
        if isinstance(out.get(key), (int, float)):
            out[key] = round(out[key] * terminal_f, 2)
    if isinstance(out.get("trough_net_worth"), (int, float)) and out.get("trough_year") is not None:
        out["trough_net_worth"] = round(out["trough_net_worth"] * factor_by_year.get(int(out["trough_year"]), 1.0), 2)
    return out
