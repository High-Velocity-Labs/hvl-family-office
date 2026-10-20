"""
forecast/monte_carlo_kernel.py: Pure numerical Monte Carlo and crisis replay kernel.
Takes primitive / NumPy-serializable inputs to execute directly or across a ProcessPoolExecutor.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
import numpy as np

from forecast.actuarial import get_survival_prob
from forecast.historical_cohorts import run_historical_cohort_backtest

HISTORICAL_CRISIS_PROFILES = {
    "1929_great_crash": {
        "id": "1929_great_crash",
        "name": "1929 Great Crash & Depression",
        "badge": "Severe Depression",
        "icon": "",
        "description": "Historical 4-year equity collapse (-86% real drawdown) with extended deflationary recovery.",
        "returns": [-0.119, -0.285, -0.433, -0.083, 0.540, -0.014, 0.385, 0.339, -0.350, 0.311],
        "default_recovery": 0.065,
    },
    "1973_stagflation": {
        "id": "1973_stagflation",
        "name": "1973–1974 Great Stagflation",
        "badge": "High Inflation",
        "icon": "",
        "description": "OPEC oil shock, double-digit CPI inflation (12.2%), and double-dip equity bear market.",
        "returns": [-0.182, -0.373, 0.315, 0.191, -0.072, 0.066, 0.186, 0.258, -0.050, 0.216],
        "default_recovery": 0.065,
    },
    "2000_dotcom_bust": {
        "id": "2000_dotcom_bust",
        "name": "2000 Dot-Com Tech Bust",
        "badge": "Tech Valuation Reset",
        "icon": "",
        "description": "3-year consecutive tech collapse (-45% S&P, -78% NASDAQ) followed by 2008 GFC aftershock.",
        "returns": [-0.125, -0.130, -0.234, 0.264, 0.084, 0.029, 0.128, 0.035, -0.370, 0.265],
        "default_recovery": 0.065,
    },
    "2008_gfc": {
        "id": "2008_gfc",
        "name": "2008 Global Financial Crisis",
        "badge": "Credit & Liquidity Freeze",
        "icon": "",
        "description": "Subprime mortgage collapse, global credit freeze, and -37.0% equity drawdown.",
        "returns": [-0.370, 0.265, 0.151, 0.021, 0.160, 0.324, 0.137, 0.014, 0.120, 0.218],
        "default_recovery": 0.065,
    },
}


def _execute_monte_carlo_kernel(
    trials: int,
    seed: Optional[int],
    num_years: int,
    years: List[int],
    ages_primary: List[int],
    initial_liquid: float,
    initial_re: float,
    initial_equity: float,
    initial_total_nw: float,
    yearly_net_cf: List[float],
    yearly_re_equity: List[float],
    yearly_comp_equity: List[float],
    yearly_non_liquid: List[float],
    mu_real: float,
    drift: float,
    sigma_port: float,
    inflation_rate: float,
    planned_ret_yr: int,
    port_stats: Dict[str, float],
    active_id: str,
    scenario_name: str,
    spending_guardrail_mode: str = "off",
) -> Dict[str, Any]:
    """
    Pure numerical Monte Carlo + historical crisis simulation kernel.
    Takes only primitive / NumPy-serializable inputs so it can execute directly or in a ProcessPoolExecutor.
    """
    spending_guardrail_mode = str(spending_guardrail_mode or "off").lower().strip()
    if spending_guardrail_mode not in ("moderate", "aggressive"):
        spending_guardrail_mode = "off"

    # Deterministic or stochastic NumPy random generator
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()

    # Pre-generate standard normal shocks for all years and trials in contiguous C memory
    Z = rng.standard_normal((num_years, trials))

    # Vectorized state arrays across all trials
    port_bal = np.full(trials, initial_liquid, dtype=np.float64)
    peak_port_bal = np.full(trials, initial_liquid, dtype=np.float64)
    depleted = np.zeros(trials, dtype=bool)
    survived_85 = np.ones(trials, dtype=bool)
    survived_90 = np.ones(trials, dtype=bool)

    yearly_nw = np.zeros((num_years, trials), dtype=np.float64)
    n_broke_by_year: List[int] = [0] * num_years
    n_growing_by_year: List[int] = [0] * num_years

    # Vectorized year-by-year compounding across all trials
    for t_idx in range(num_years):
        age = ages_primary[t_idx]
        net_cf = yearly_net_cf[t_idx]
        comp_eq = yearly_comp_equity[t_idx]
        non_liq = yearly_non_liquid[t_idx]

        np.maximum(peak_port_bal, port_bal, out=peak_port_bal)

        if net_cf < 0 and spending_guardrail_mode in ("moderate", "aggressive"):
            trial_cf = np.full(trials, net_cf, dtype=np.float64)
            if spending_guardrail_mode == "moderate":
                cut_mask = port_bal < (0.85 * peak_port_bal)
                trial_cf[cut_mask] = net_cf * 0.85
            elif spending_guardrail_mode == "aggressive":
                cut25 = port_bal < (0.85 * peak_port_bal)
                cut15 = (~cut25) & (port_bal < (0.90 * peak_port_bal))
                trial_cf[cut25] = net_cf * 0.75
                trial_cf[cut15] = net_cf * 0.85
        else:
            trial_cf = net_cf

        z = Z[t_idx]
        active_mask = (~depleted) & (port_bal > 0.0)

        if np.any(active_mask):
            ann_return = np.exp(drift + sigma_port * z[active_mask]) - 1.0
            cf_val = trial_cf[active_mask] if isinstance(trial_cf, np.ndarray) else trial_cf
            port_bal[active_mask] = port_bal[active_mask] * (1.0 + ann_return) + cf_val
            newly_depleted = active_mask & (port_bal <= 0.0)
            depleted[newly_depleted] = True

        inactive_mask = ~active_mask
        if np.any(inactive_mask):
            cf_val = trial_cf[inactive_mask] if isinstance(trial_cf, np.ndarray) else trial_cf
            port_bal[inactive_mask] = port_bal[inactive_mask] + cf_val

        np.maximum(port_bal, 0.0, out=port_bal)

        tot_nw = port_bal + non_liq
        yearly_nw[t_idx] = tot_nw

        is_broke = (tot_nw <= 0.0) | ((port_bal <= 0.0) & (comp_eq <= 0.0))
        n_broke = int(np.count_nonzero(is_broke))
        n_growing = int(np.count_nonzero((~is_broke) & (tot_nw > initial_total_nw)))
        n_broke_by_year[t_idx] = n_broke
        n_growing_by_year[t_idx] = n_growing

        if age >= 85:
            fail_85 = (tot_nw <= 0.0) | (depleted & (comp_eq <= 0.0))
            survived_85[fail_85] = False
        if age >= 90:
            fail_90 = (tot_nw <= 0.0) | (depleted & (comp_eq <= 0.0))
            survived_90[fail_90] = False

    last_non_liquid = yearly_non_liquid[-1]
    last_comp_eq = yearly_comp_equity[-1]
    terminal_wealths = port_bal + last_non_liquid

    survived_100_mask = (terminal_wealths > 0.0) & ((port_bal > 0.0) | (last_comp_eq > 0.0))
    trials_survived_to_100 = int(np.count_nonzero(survived_100_mask))
    trials_survived_to_85 = int(np.count_nonzero(survived_85))
    trials_survived_to_90 = int(np.count_nonzero(survived_90))

    # Fast column-wise percentile extraction via NumPy sort
    idx_10 = int(0.10 * trials)
    idx_25 = int(0.25 * trials)
    idx_50 = int(0.50 * trials)
    idx_75 = int(0.75 * trials)
    idx_90 = int(0.90 * trials)

    sorted_yearly_nw = np.sort(yearly_nw, axis=1)
    p10_series = sorted_yearly_nw[:, idx_10]
    p25_series = sorted_yearly_nw[:, idx_25]
    p50_series = sorted_yearly_nw[:, idx_50]
    p75_series = sorted_yearly_nw[:, idx_75]
    p90_series = sorted_yearly_nw[:, idx_90]

    percentiles_timeline = []
    monte_carlo_longevity_breakdown = []

    for t_idx in range(num_years):
        percentiles_timeline.append({
            "year": years[t_idx],
            "age": ages_primary[t_idx],
            "p10": round(float(p10_series[t_idx]), 2),
            "p25": round(float(p25_series[t_idx]), 2),
            "p50": round(float(p50_series[t_idx]), 2),
            "p75": round(float(p75_series[t_idx]), 2),
            "p90": round(float(p90_series[t_idx]), 2),
        })

        n_broke = n_broke_by_year[t_idx]
        n_growing = n_growing_by_year[t_idx]

        surv = get_survival_prob(ages_primary[t_idx])
        p_joint = surv["joint"]
        p_deceased = round(1.0 - p_joint, 4)

        prob_broke = round(p_joint * (n_broke / trials) * 100, 1)
        prob_growing = round(p_joint * (n_growing / trials) * 100, 1)
        prob_deceased = round(p_deceased * 100, 1)
        prob_preserved = round(max(0.0, 100.0 - prob_growing - prob_broke - prob_deceased), 1)

        monte_carlo_longevity_breakdown.append({
            "year": years[t_idx],
            "age": ages_primary[t_idx],
            "age_primary": ages_primary[t_idx],
            "prob_growing": prob_growing,
            "prob_preserved": prob_preserved,
            "prob_broke": prob_broke,
            "prob_deceased": prob_deceased,
        })

    sorted_terminal = np.sort(terminal_wealths)
    median_terminal = float(sorted_terminal[idx_50])
    p10_terminal = float(sorted_terminal[idx_10])
    p90_terminal = float(sorted_terminal[idx_90])

    success_rate_100 = round((trials_survived_to_100 / trials) * 100, 1)
    success_rate_90 = round((trials_survived_to_90 / trials) * 100, 1)
    success_rate_85 = round((trials_survived_to_85 / trials) * 100, 1)

    # =========================================================================
    # Historical Sequence-of-Returns Crisis Replays
    # =========================================================================
    stress_tests = {}
    for crisis_id, c_data in HISTORICAL_CRISIS_PROFILES.items():
        port_bal_c = initial_liquid
        c_returns = c_data["returns"]
        default_rec = c_data["default_recovery"]
        c_trajectory = []
        depleted_c = False
        trough_bal = port_bal_c + initial_re + initial_equity
        trough_yr = years[0]
        peak_bal = trough_bal
        peak_port_bal_c = initial_liquid

        for t_idx in range(num_years):
            yr = years[t_idx]
            net_cf = yearly_net_cf[t_idx]

            if port_bal_c > peak_port_bal_c:
                peak_port_bal_c = port_bal_c

            adj_cf = net_cf
            if net_cf < 0 and spending_guardrail_mode in ("moderate", "aggressive"):
                if spending_guardrail_mode == "moderate" and port_bal_c < (0.85 * peak_port_bal_c):
                    adj_cf = net_cf * 0.85
                elif spending_guardrail_mode == "aggressive":
                    if port_bal_c < (0.85 * peak_port_bal_c):
                        adj_cf = net_cf * 0.75
                    elif port_bal_c < (0.90 * peak_port_bal_c):
                        adj_cf = net_cf * 0.85

            # If before planned retirement, use normal expected growth in real terms
            if yr < planned_ret_yr:
                ann_return = mu_real
            else:
                # Inside crisis window (convert nominal historical returns to real returns)
                c_idx = yr - planned_ret_yr
                if c_idx < len(c_returns):
                    ann_return = ((1.0 + c_returns[c_idx]) / (1.0 + inflation_rate)) - 1.0
                else:
                    ann_return = ((1.0 + default_rec) / (1.0 + inflation_rate)) - 1.0

            if not depleted_c and port_bal_c > 0:
                growth = port_bal_c * ann_return
                port_bal_c += growth + adj_cf
                if port_bal_c <= 0:
                    port_bal_c = 0.0
                    depleted_c = True
            else:
                port_bal_c = max(0.0, port_bal_c + adj_cf)

            tot_nw = port_bal_c + yearly_re_equity[t_idx] + yearly_comp_equity[t_idx]
            c_trajectory.append({"year": yr, "age": ages_primary[t_idx], "net_worth": round(tot_nw, 2)})

            if tot_nw > peak_bal:
                peak_bal = tot_nw
            if tot_nw < trough_bal:
                trough_bal = tot_nw
                trough_yr = yr

        max_dd = round(((peak_bal - trough_bal) / peak_bal * 100), 1) if peak_bal > 0 else 0.0
        term_nw = c_trajectory[-1]["net_worth"] if c_trajectory else 0.0

        stress_tests[crisis_id] = {
            "id": crisis_id,
            "name": c_data["name"],
            "badge": c_data["badge"],
            "icon": c_data["icon"],
            "description": c_data["description"],
            "survived": tot_nw > 0 and (port_bal_c > 0 or yearly_comp_equity[-1] > 0),
            "max_drawdown_pct": max_dd,
            "trough_net_worth": round(trough_bal, 2),
            "trough_year": trough_yr,
            "terminal_net_worth": round(term_nw, 2),
            "trajectory": c_trajectory,
        }

    historical_cohorts = run_historical_cohort_backtest(
        years=years,
        ages_primary=ages_primary,
        initial_liquid=initial_liquid,
        initial_re=initial_re,
        initial_equity=initial_equity,
        yearly_net_cf=yearly_net_cf,
        yearly_re_equity=yearly_re_equity,
        yearly_comp_equity=yearly_comp_equity,
        yearly_non_liquid=yearly_non_liquid,
        port_stats=port_stats,
        spending_guardrail_mode=spending_guardrail_mode,
    )

    return {
        "success": True,
        "scenario_id": active_id,
        "scenario_name": scenario_name,
        "spending_guardrail_mode": spending_guardrail_mode,
        "trials": trials,
        "portfolio_stats": port_stats,
        "initial_net_worth": round(initial_total_nw, 2),
        "initial_liquid": round(initial_liquid, 2),
        "success_rate_age_100": success_rate_100,
        "success_rate_age_90": success_rate_90,
        "success_rate_age_85": success_rate_85,
        "median_terminal_wealth": round(median_terminal, 2),
        "p10_terminal_wealth": round(p10_terminal, 2),
        "p90_terminal_wealth": round(p90_terminal, 2),
        "percentiles_timeline": percentiles_timeline,
        "longevity_breakdown": monte_carlo_longevity_breakdown,
        "stress_tests": stress_tests,
        "historical_cohorts": historical_cohorts,
    }
