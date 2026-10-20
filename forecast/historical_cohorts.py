"""
forecast/historical_cohorts.py: 1928–2025 Historical Cohort Backtesting Engine.
Replays a household's deterministic retirement cash flows against every rolling historical
market cohort since 1928 using actual annual S&P 500 total returns, 10-Year US Treasury bond
returns, 3-Month T-Bill cash yields, and US CPI inflation (Damodaran / Shiller / FRED series).
"""

from __future__ import annotations
from typing import Any, Dict, List
import numpy as np

# =============================================================================
# Historical Annual US Market Returns & CPI Inflation (1928–2025)
# Columns: (year, sp500_total_return, us_10yr_bond_return, tbill_3m_return, cpi_inflation)
# Source: Aswath Damodaran (NYU Stern) / Robert Shiller / FRED historical series.
# =============================================================================
HISTORICAL_MARKET_ROWS: List[tuple[int, float, float, float, float]] = [
    (1928, 0.4381, 0.0084, 0.0308, -0.0115),
    (1929, -0.0830, 0.0420, 0.0316, 0.0058),
    (1930, -0.2512, 0.0454, 0.0455, -0.0640),
    (1931, -0.4384, -0.0256, 0.0231, -0.0932),
    (1932, -0.0864, 0.0879, 0.0107, -0.1027),
    (1933, 0.4998, 0.0186, 0.0096, 0.0076),
    (1934, -0.0119, 0.0796, 0.0032, 0.0152),
    (1935, 0.4674, 0.0447, 0.0018, 0.0299),
    (1936, 0.3194, 0.0502, 0.0017, 0.0145),
    (1937, -0.3534, 0.0138, 0.0030, 0.0286),
    (1938, 0.2928, 0.0421, 0.0008, -0.0278),
    (1939, -0.0110, 0.0441, 0.0004, 0.0000),
    (1940, -0.1067, 0.0540, 0.0003, 0.0071),
    (1941, -0.1277, -0.0202, 0.0008, 0.0993),
    (1942, 0.1917, 0.0229, 0.0034, 0.0903),
    (1943, 0.2506, 0.0249, 0.0038, 0.0296),
    (1944, 0.1903, 0.0258, 0.0038, 0.0230),
    (1945, 0.3582, 0.0380, 0.0038, 0.0225),
    (1946, -0.0843, 0.0313, 0.0038, 0.1813),
    (1947, 0.0520, 0.0092, 0.0057, 0.0884),
    (1948, 0.0570, 0.0195, 0.0102, 0.0299),
    (1949, 0.1830, 0.0466, 0.0110, -0.0207),
    (1950, 0.3081, 0.0043, 0.0117, 0.0593),
    (1951, 0.2368, -0.0030, 0.0148, 0.0600),
    (1952, 0.1815, 0.0227, 0.0167, 0.0075),
    (1953, -0.0121, 0.0414, 0.0189, 0.0075),
    (1954, 0.5256, 0.0329, 0.0096, -0.0074),
    (1955, 0.3260, -0.0134, 0.0166, 0.0037),
    (1956, 0.0744, -0.0226, 0.0256, 0.0299),
    (1957, -0.1046, 0.0680, 0.0323, 0.0290),
    (1958, 0.4372, -0.0210, 0.0178, 0.0176),
    (1959, 0.1206, -0.0265, 0.0326, 0.0173),
    (1960, 0.0034, 0.1164, 0.0305, 0.0136),
    (1961, 0.2664, 0.0206, 0.0227, 0.0067),
    (1962, -0.0881, 0.0569, 0.0278, 0.0133),
    (1963, 0.2261, 0.0168, 0.0311, 0.0164),
    (1964, 0.1642, 0.0373, 0.0351, 0.0097),
    (1965, 0.1240, 0.0072, 0.0390, 0.0192),
    (1966, -0.0997, 0.0291, 0.0484, 0.0346),
    (1967, 0.2380, -0.0158, 0.0433, 0.0304),
    (1968, 0.1081, 0.0327, 0.0526, 0.0472),
    (1969, -0.0824, -0.0501, 0.0656, 0.0620),
    (1970, 0.0356, 0.1675, 0.0669, 0.0557),
    (1971, 0.1422, 0.0979, 0.0454, 0.0327),
    (1972, 0.1876, 0.0282, 0.0395, 0.0341),
    (1973, -0.1431, 0.0366, 0.0673, 0.0871),
    (1974, -0.2590, 0.0199, 0.0778, 0.1234),
    (1975, 0.3700, 0.0361, 0.0599, 0.0694),
    (1976, 0.2383, 0.1598, 0.0497, 0.0486),
    (1977, -0.0706, 0.0129, 0.0513, 0.0670),
    (1978, 0.0651, -0.0078, 0.0693, 0.0902),
    (1979, 0.1852, 0.0067, 0.0994, 0.1329),
    (1980, 0.3174, -0.0299, 0.1122, 0.1252),
    (1981, -0.0470, 0.0820, 0.1430, 0.0892),
    (1982, 0.2042, 0.3281, 0.1101, 0.0383),
    (1983, 0.2234, 0.0320, 0.0845, 0.0379),
    (1984, 0.0615, 0.1373, 0.0961, 0.0395),
    (1985, 0.3124, 0.2571, 0.0749, 0.0380),
    (1986, 0.1849, 0.2428, 0.0604, 0.0110),
    (1987, 0.0581, -0.0496, 0.0572, 0.0443),
    (1988, 0.1654, 0.0822, 0.0645, 0.0442),
    (1989, 0.3148, 0.1769, 0.0811, 0.0465),
    (1990, -0.0306, 0.0624, 0.0755, 0.0611),
    (1991, 0.3023, 0.1500, 0.0561, 0.0306),
    (1992, 0.0749, 0.0936, 0.0341, 0.0290),
    (1993, 0.0997, 0.1421, 0.0298, 0.0275),
    (1994, 0.0133, -0.0804, 0.0399, 0.0267),
    (1995, 0.3720, 0.2348, 0.0552, 0.0254),
    (1996, 0.2268, 0.0143, 0.0502, 0.0332),
    (1997, 0.3310, 0.0994, 0.0505, 0.0170),
    (1998, 0.2834, 0.1492, 0.0473, 0.0161),
    (1999, 0.2089, -0.0825, 0.0451, 0.0268),
    (2000, -0.0903, 0.1666, 0.0576, 0.0339),
    (2001, -0.1185, 0.0557, 0.0367, 0.0155),
    (2002, -0.2197, 0.1512, 0.0166, 0.0238),
    (2003, 0.2836, 0.0038, 0.0103, 0.0188),
    (2004, 0.1074, 0.0449, 0.0123, 0.0326),
    (2005, 0.0483, 0.0287, 0.0301, 0.0342),
    (2006, 0.1561, 0.0196, 0.0468, 0.0254),
    (2007, 0.0548, 0.1021, 0.0464, 0.0408),
    (2008, -0.3655, 0.2010, 0.0159, 0.0009),
    (2009, 0.2594, -0.1112, 0.0014, 0.0272),
    (2010, 0.1482, 0.0846, 0.0013, 0.0150),
    (2011, 0.0210, 0.1604, 0.0005, 0.0296),
    (2012, 0.1589, 0.0297, 0.0009, 0.0174),
    (2013, 0.3215, -0.0910, 0.0006, 0.0150),
    (2014, 0.1352, 0.1075, 0.0003, 0.0076),
    (2015, 0.0138, 0.0128, 0.0005, 0.0073),
    (2016, 0.1177, 0.0069, 0.0032, 0.0207),
    (2017, 0.2161, 0.0280, 0.0093, 0.0211),
    (2018, -0.0423, -0.0002, 0.0194, 0.0191),
    (2019, 0.3121, 0.0964, 0.0206, 0.0229),
    (2020, 0.1802, 0.1133, 0.0035, 0.0136),
    (2021, 0.2847, -0.0442, 0.0005, 0.0704),
    (2022, -0.1804, -0.1783, 0.0202, 0.0645),
    (2023, 0.2606, 0.0388, 0.0507, 0.0335),
    (2024, 0.2488, -0.0164, 0.0518, 0.0290),
    (2025, 0.1778, 0.0420, 0.0435, 0.0260),
]

ERA_LABELS: Dict[int, str] = {
    1929: "1929 Great Crash",
    1930: "1930 Depression Spiral",
    1931: "1931 Banking Collapse",
    1937: "1937 Late-Depression Crash",
    1946: "1946 Post-WWII Inflation Spike",
    1965: "1965 Secular Stagflation Start",
    1966: "1966–1981 Stagflation Cohort",
    1968: "1968 Inflation & Bear Market",
    1969: "1969–1974 Double Bear",
    1973: "1973 OPEC Stagflation Shock",
    1974: "1974 Deep Stagflation Trough",
    1999: "1999 Tech Bubble Peak",
    2000: "2000 Dot-Com + 2008 GFC",
    2001: "2001 Tech Bust & 9/11",
    2007: "2007 Pre-GFC Peak",
    2008: "2008 Global Financial Crisis",
    2022: "2022 Rate & Inflation Shock",
}


def run_historical_cohort_backtest(
    years: List[int],
    ages_primary: List[int],
    initial_liquid: float,
    initial_re: float,
    initial_equity: float,
    yearly_net_cf: List[float],
    yearly_re_equity: List[float],
    yearly_comp_equity: List[float],
    yearly_non_liquid: List[float],
    port_stats: Dict[str, float],
    spending_guardrail_mode: str = "off",
) -> Dict[str, Any]:
    """
    Replays the household's projection schedule across all 98 historical market cohorts
    (starting in each year 1928..2025, wrapping around to 1928 for cohorts that reach 2025).
    Computes real (inflation-adjusted) blended returns for each historical year using the
    household's equity, bond, and cash allocation weights.
    """
    spending_guardrail_mode = str(spending_guardrail_mode or "off").lower().strip()
    if spending_guardrail_mode not in ("moderate", "aggressive"):
        spending_guardrail_mode = "off"

    num_years = len(years)
    n_cohorts = len(HISTORICAL_MARKET_ROWS)
    if num_years == 0 or n_cohorts == 0:
        return {"total_cohorts": 0, "survived_cohorts": 0, "survival_rate": 0.0, "spending_guardrail_mode": spending_guardrail_mode}

    # Normalize liquid weights across US Equity, Intl Equity, Bonds, and Cash
    w_us = float(port_stats.get("w_us", 0.60) + port_stats.get("w_private", 0.0))
    w_intl = float(port_stats.get("w_intl", 0.20))
    w_bd = float(port_stats.get("w_bonds", 0.15) + port_stats.get("w_re", 0.0))
    w_ca = float(port_stats.get("w_cash", 0.05))
    w_tot = w_us + w_intl + w_bd + w_ca
    if w_tot > 0:
        w_us, w_intl, w_bd, w_ca = w_us / w_tot, w_intl / w_tot, w_bd / w_tot, w_ca / w_tot
    else:
        w_us, w_intl, w_bd, w_ca = 0.60, 0.20, 0.15, 0.05

    # Precompute real blended portfolio return for each historical calendar year (1928..2025)
    hist_years = [r[0] for r in HISTORICAL_MARKET_ROWS]
    hist_real_returns = np.empty(n_cohorts, dtype=np.float64)
    for idx, (_, sp_ret, bd_ret, tb_ret, cpi) in enumerate(HISTORICAL_MARKET_ROWS):
        intl_ret = (0.85 * sp_ret) - 0.012
        nom_ret = (w_us * sp_ret) + (w_intl * intl_ret) + (w_bd * bd_ret) + (w_ca * tb_ret)
        # Fisher real return using that exact historical year's CPI inflation
        hist_real_returns[idx] = ((1.0 + nom_ret) / max(0.5, 1.0 + cpi)) - 1.0

    # Matrix of cohort net worth paths: shape (num_years, n_cohorts)
    port_bal = np.full(n_cohorts, initial_liquid, dtype=np.float64)
    peak_port_bal = np.full(n_cohorts, initial_liquid, dtype=np.float64)
    cum_deficit = np.zeros(n_cohorts, dtype=np.float64)
    depleted = np.zeros(n_cohorts, dtype=bool)
    depletion_age = np.full(n_cohorts, -1, dtype=np.int32)
    depletion_year = np.full(n_cohorts, -1, dtype=np.int32)

    init_nw = initial_liquid + initial_re + initial_equity
    peak_nw = np.full(n_cohorts, init_nw, dtype=np.float64)
    trough_nw = np.full(n_cohorts, init_nw, dtype=np.float64)
    trough_yr = np.full(n_cohorts, years[0], dtype=np.int32)
    max_dd_pct = np.zeros(n_cohorts, dtype=np.float64)

    yearly_nw = np.zeros((num_years, n_cohorts), dtype=np.float64)
    cohort_indices = np.arange(n_cohorts, dtype=np.int32)

    for t_idx in range(num_years):
        yr = years[t_idx]
        age = ages_primary[t_idx]
        net_cf = yearly_net_cf[t_idx]
        non_liq = yearly_non_liquid[t_idx]

        np.maximum(peak_port_bal, port_bal, out=peak_port_bal)

        if net_cf < 0 and spending_guardrail_mode in ("moderate", "aggressive"):
            adj_cf = np.full(n_cohorts, net_cf, dtype=np.float64)
            if spending_guardrail_mode == "moderate":
                cut_mask = port_bal < (0.85 * peak_port_bal)
                adj_cf[cut_mask] = net_cf * 0.85
            elif spending_guardrail_mode == "aggressive":
                cut25 = port_bal < (0.85 * peak_port_bal)
                cut15 = (~cut25) & (port_bal < (0.90 * peak_port_bal))
                adj_cf[cut25] = net_cf * 0.75
                adj_cf[cut15] = net_cf * 0.85
        else:
            adj_cf = net_cf

        # Each cohort c uses historical return at (c + t_idx) % n_cohorts
        ret_idx = (cohort_indices + t_idx) % n_cohorts
        ann_ret = hist_real_returns[ret_idx]

        active_mask = (~depleted) & (port_bal > 0.0)
        if np.any(active_mask):
            cf_val = adj_cf[active_mask] if isinstance(adj_cf, np.ndarray) else adj_cf
            port_bal[active_mask] = port_bal[active_mask] * (1.0 + ann_ret[active_mask]) + cf_val
            newly_depleted = active_mask & (port_bal <= 0.0)
            if np.any(newly_depleted):
                depleted[newly_depleted] = True
                first_dep = newly_depleted & (depletion_age < 0)
                depletion_age[first_dep] = age
                depletion_year[first_dep] = yr

        inactive_mask = ~active_mask
        if np.any(inactive_mask):
            cf_val = adj_cf[inactive_mask] if isinstance(adj_cf, np.ndarray) else adj_cf
            port_bal[inactive_mask] = port_bal[inactive_mask] + cf_val

        shortfall = np.maximum(0.0, -port_bal)
        cum_deficit += shortfall
        np.maximum(port_bal, 0.0, out=port_bal)
        tot_nw = np.maximum(0.0, port_bal + non_liq - cum_deficit)
        yearly_nw[t_idx] = tot_nw

        # Track peak-to-trough drawdown per cohort
        higher = tot_nw > peak_nw
        peak_nw[higher] = tot_nw[higher]
        lower = tot_nw < trough_nw
        trough_nw[lower] = tot_nw[lower]
        trough_yr[lower] = yr
        dd = np.divide(peak_nw - tot_nw, peak_nw, out=np.zeros_like(peak_nw), where=peak_nw > 0.0) * 100.0
        max_dd_pct = np.maximum(max_dd_pct, dd)

    last_comp_eq = yearly_comp_equity[-1]
    terminal_wealths = yearly_nw[-1]
    survived_mask = (terminal_wealths > 0.0) & ((port_bal > 0.0) | ((last_comp_eq - cum_deficit) > 0.0))
    survived_count = int(np.count_nonzero(survived_mask))
    survival_rate = round((survived_count / n_cohorts) * 100.0, 1)

    # Percentiles across the 98 historical cohorts by year
    sorted_yearly = np.sort(yearly_nw, axis=1)
    idx_10 = int(0.10 * n_cohorts)
    idx_25 = int(0.25 * n_cohorts)
    idx_50 = int(0.50 * n_cohorts)
    idx_75 = int(0.75 * n_cohorts)
    idx_90 = int(0.90 * n_cohorts)

    percentiles_timeline = []
    for t_idx in range(num_years):
        percentiles_timeline.append({
            "year": years[t_idx],
            "age": ages_primary[t_idx],
            "p10": round(float(sorted_yearly[t_idx, idx_10]), 2),
            "p25": round(float(sorted_yearly[t_idx, idx_25]), 2),
            "p50": round(float(sorted_yearly[t_idx, idx_50]), 2),
            "p75": round(float(sorted_yearly[t_idx, idx_75]), 2),
            "p90": round(float(sorted_yearly[t_idx, idx_90]), 2),
        })

    # Rank cohorts from worst to best (by survival first, then depletion age, then terminal wealth, then max drawdown)
    cohort_summaries: List[Dict[str, Any]] = []
    failed_start_years: List[int] = []
    for c_idx in range(n_cohorts):
        s_yr = hist_years[c_idx]
        surv = bool(survived_mask[c_idx])
        if not surv:
            failed_start_years.append(s_yr)
        cohort_summaries.append({
            "start_year": s_yr,
            "label": ERA_LABELS.get(s_yr, f"{s_yr} Market Cohort"),
            "survived": surv,
            "depletion_age": int(depletion_age[c_idx]) if depletion_age[c_idx] > 0 else None,
            "depletion_year": int(depletion_year[c_idx]) if depletion_year[c_idx] > 0 else None,
            "max_drawdown_pct": round(float(max_dd_pct[c_idx]), 1),
            "trough_net_worth": round(float(trough_nw[c_idx]), 2),
            "trough_year": int(trough_yr[c_idx]),
            "terminal_net_worth": round(float(terminal_wealths[c_idx]), 2),
        })

    worst_sorted = sorted(
        cohort_summaries,
        key=lambda x: (
            1 if x["survived"] else 0,
            x["depletion_age"] if x["depletion_age"] is not None else 999,
            x["terminal_net_worth"],
            -x["max_drawdown_pct"],
        ),
    )

    sorted_term = np.sort(terminal_wealths)
    return {
        "start_year_min": hist_years[0],
        "start_year_max": hist_years[-1],
        "spending_guardrail_mode": spending_guardrail_mode,
        "total_cohorts": n_cohorts,
        "survived_cohorts": survived_count,
        "failed_cohorts": n_cohorts - survived_count,
        "survival_rate_age_100": survival_rate,
        "median_terminal_wealth": round(float(sorted_term[idx_50]), 2),
        "p10_terminal_wealth": round(float(sorted_term[idx_10]), 2),
        "p90_terminal_wealth": round(float(sorted_term[idx_90]), 2),
        "worst_terminal_wealth": round(float(sorted_term[0]), 2),
        "best_terminal_wealth": round(float(sorted_term[-1]), 2),
        "failed_start_years": failed_start_years,
        "worst_cohorts": worst_sorted[:6],
        "percentiles_timeline": percentiles_timeline,
    }
