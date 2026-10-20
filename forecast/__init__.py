"""
forecast package: Modular forecasting engine subpackage.
Exports actuarial tables, catalog presets, household context, storage, hierarchy,
waterfall, Monte Carlo, and multi-scenario orchestrator engines.
"""

from __future__ import annotations
from .actuarial import SSA_PERIOD_SURVIVAL_TABLE, get_survival_prob
from .catalog import (
    REINVESTMENT_PRESETS,
    COMPANY_GROWTH_PRESETS,
    EQUITY_GROWTH_PRESETS,
    SCENARIO_TEMPLATES,
)
from .context import HouseholdContext, build_household_context
from .storage import (
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
from .hierarchy import (
    INHERITABLE_ASSUMPTION_KEYS,
    resolve_scenario_hierarchy,
)
from .presets import (
    format_short_currency_spend,
    get_default_event_catalog,
    get_default_scenarios,
    build_living_budget_presets,
    build_annual_savings_presets,
    get_scenario_templates,
)
from .waterfall import run_scenario_simulation
from .monte_carlo import (
    ASSET_CLASS_PARAMS,
    HISTORICAL_CRISIS_PROFILES,
    compute_blended_portfolio_stats,
    run_monte_carlo_simulation,
)
from .orchestrator import simulate_multi_scenarios

__all__ = [
    "SSA_PERIOD_SURVIVAL_TABLE",
    "get_survival_prob",
    "REINVESTMENT_PRESETS",
    "COMPANY_GROWTH_PRESETS",
    "EQUITY_GROWTH_PRESETS",
    "SCENARIO_TEMPLATES",
    "HouseholdContext",
    "build_household_context",
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
