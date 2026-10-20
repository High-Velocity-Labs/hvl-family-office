"""
forecast_engine.py: Backward-compatible facade for the modular forecast subpackage.

All core capabilities have been decomposed into dedicated submodules under `forecast/`:
- `forecast.actuarial`: SSA survival tables and longevity probability curves.
- `forecast.context`: Household context extraction (equity lots, children, 529 reserves).
- `forecast.catalog`: Growth presets and scenario template definitions.
- `forecast.storage`: Scenario persistence, child tuition/education queries, and dynamic universe routing.
- `forecast.hierarchy`: Scenario tree inheritance and event timeline overlays.
- `forecast.presets`: Default event catalogs and spending/savings preset builders.
- `forecast.waterfall`: Single-scenario cash flow simulation engine.
- `forecast.monte_carlo`: Multi-asset portfolio stats and Monte Carlo stochastic crisis engine.
- `forecast.orchestrator`: Multi-scenario comparison and timeline simulation orchestrator.
"""

from __future__ import annotations

from forecast.storage import (
    _ForecastDbPathProxy,
    DB_PATH,
    get_db_path,
    load_children_edu_reserves,
    load_children_k12_tuition,
    get_child_ledger_expense_for_year,
    child_has_tuition_ledger,
    load_historical_forecast_actuals,
    load_scenario_state,
    save_scenario_state,
)

from forecast.catalog import (
    REINVESTMENT_PRESETS,
    COMPANY_GROWTH_PRESETS,
    EQUITY_GROWTH_PRESETS,
    SCENARIO_TEMPLATES,
)

from forecast.actuarial import (
    SSA_PERIOD_SURVIVAL_TABLE,
    get_survival_prob,
)

from forecast.context import (
    HouseholdContext,
    build_household_context,
)

from forecast.hierarchy import (
    INHERITABLE_ASSUMPTION_KEYS,
    resolve_scenario_hierarchy,
)

from forecast.presets import (
    format_short_currency_spend,
    get_default_event_catalog,
    get_default_scenarios,
    build_living_budget_presets,
    build_annual_savings_presets,
    get_scenario_templates,
)

from forecast.waterfall import (
    run_scenario_simulation,
)

from forecast.monte_carlo import (
    ASSET_CLASS_PARAMS,
    HISTORICAL_CRISIS_PROFILES,
    compute_blended_portfolio_stats,
    run_monte_carlo_simulation,
)

from forecast.orchestrator import (
    simulate_multi_scenarios,
)

__all__ = [
    "_ForecastDbPathProxy",
    "DB_PATH",
    "get_db_path",
    "load_children_edu_reserves",
    "load_children_k12_tuition",
    "get_child_ledger_expense_for_year",
    "child_has_tuition_ledger",
    "load_historical_forecast_actuals",
    "load_scenario_state",
    "save_scenario_state",
    "REINVESTMENT_PRESETS",
    "COMPANY_GROWTH_PRESETS",
    "EQUITY_GROWTH_PRESETS",
    "SCENARIO_TEMPLATES",
    "SSA_PERIOD_SURVIVAL_TABLE",
    "get_survival_prob",
    "HouseholdContext",
    "build_household_context",
    "INHERITABLE_ASSUMPTION_KEYS",
    "resolve_scenario_hierarchy",
    "format_short_currency_spend",
    "get_default_event_catalog",
    "get_default_scenarios",
    "build_living_budget_presets",
    "build_annual_savings_presets",
    "get_scenario_templates",
    "run_scenario_simulation",
    "ASSET_CLASS_PARAMS",
    "HISTORICAL_CRISIS_PROFILES",
    "compute_blended_portfolio_stats",
    "run_monte_carlo_simulation",
    "simulate_multi_scenarios",
]
