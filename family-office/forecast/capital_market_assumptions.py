"""
forecast/capital_market_assumptions.py: The one table of long-run asset-class assumptions.

Means are nominal annual returns, used by both the deterministic waterfall (as scenario
growth defaults) and Monte Carlo (as drift, with the scenario's own growth overrides
taking precedence). Volatilities are used by Monte Carlo only.
"""

from __future__ import annotations
from typing import Any, Dict

DEFAULT_INFLATION_RATE = 0.025
# Tuition and other education costs outrun general prices; scenarios may override with `education_inflation_rate`.
DEFAULT_EDUCATION_INFLATION_RATE = 0.05

# What the projection assumes for a household with nothing on file; `orchestrator_series.resolve_profile_defaults` is
# the only reader. A household that entered nothing spends and saves nothing in the plan, retires at 65 and claims
# Social Security at 67, the SSA full retirement age for anyone born in 1960 or later
# (https://www.ssa.gov/benefits/retirement/planner/agereduction.html).
DEFAULT_RETIREMENT_AGE = 65
DEFAULT_SS_CLAIM_AGE = 67
DEFAULT_ANNUAL_SPENDING = 0.0
DEFAULT_ANNUAL_SAVINGS = 0.0

ASSET_CLASS_ASSUMPTIONS: Dict[str, Dict[str, object]] = {
    "us_equity": {"mean": 0.075, "vol": 0.170, "label": "US Equities"},
    "intl_equity": {"mean": 0.065, "vol": 0.190, "label": "International Equities"},
    "bonds": {"mean": 0.042, "vol": 0.060, "label": "Fixed Income / Bonds"},
    "cash": {"mean": 0.028, "vol": 0.010, "label": "Cash & Equivalents"},
    "private_investments": {"mean": 0.100, "vol": 0.240, "label": "Private VC & Angel"},
    "real_estate": {"mean": 0.035, "vol": 0.080, "label": "Real Estate"},
}

# Scenario field that overrides each asset class's mean.
SCENARIO_GROWTH_FIELDS: Dict[str, str] = {
    "us_equity": "growth_us_equity",
    "intl_equity": "growth_intl_equity",
    "bonds": "growth_bonds",
    "cash": "growth_cash",
    "private_investments": "growth_private_investments",
    "real_estate": "growth_real_estate",
}

DEFAULT_SCENARIO_GROWTH: Dict[str, float] = {
    field: float(ASSET_CLASS_ASSUMPTIONS[asset]["mean"]) for asset, field in SCENARIO_GROWTH_FIELDS.items()
}


# Mix assumed when the household has no holdings-level allocation data (same as the plan's default).
DEFAULT_PORTFOLIO_WEIGHTS: Dict[str, float] = {
    "us_equity": 0.60, "intl_equity": 0.20, "bonds": 0.15, "cash": 0.05,
    "private_investments": 0.0, "real_estate": 0.0,
}


def resolve_portfolio_weights(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    The household's actual investable mix (taxable and retirement holdings together) as weights,
    plus `source`: "holdings" when derived from holdings data, "assumed" when none exists.
    """
    totals = snapshot.get("detailed_asset_allocation", {}).get("totals", {}) or {}
    values = {
        "us_equity": float(totals.get("us_equity", 0.0) or 0.0),
        "intl_equity": float(totals.get("intl_equity", 0.0) or 0.0),
        "bonds": float(totals.get("bonds", 0.0) or 0.0),
        "cash": float(totals.get("cash_liquid", 0.0) or 0.0),
    }
    pool = sum(values.values())
    if pool <= 0:
        return {**DEFAULT_PORTFOLIO_WEIGHTS, "source": "assumed"}
    weights: Dict[str, Any] = {k: round(v / pool, 6) for k, v in values.items()}
    weights.update({"private_investments": 0.0, "real_estate": 0.0, "source": "holdings"})
    return weights
