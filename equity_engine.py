"""
Equity Engine Facade: Company Equity Valuation, Vesting & Exercise Scenario Simulator.
Delegates to the modular `equity` package while preserving 100% backward compatibility.
"""

from equity.models import (
    CURRENT_409A_PRICE,
    DB_PATH,
    EquityGrant,
    _EngineDbPathProxy,
    get_default_equity_grants,
)
from equity.repository import (
    get_company_409a_price,
    get_company_name,
    get_current_409a_price,
    get_historical_equity_fmv,
    get_primary_company_name,
    load_equity_companies_summary,
    load_equity_grants_from_db,
)
from equity.simulator import (
    simulate_multi_year_projections,
    simulate_valuation_scenario,
)

__all__ = [
    "CURRENT_409A_PRICE",
    "DB_PATH",
    "EquityGrant",
    "_EngineDbPathProxy",
    "get_company_409a_price",
    "get_company_name",
    "get_current_409a_price",
    "get_default_equity_grants",
    "get_historical_equity_fmv",
    "get_primary_company_name",
    "load_equity_companies_summary",
    "load_equity_grants_from_db",
    "simulate_multi_year_projections",
    "simulate_valuation_scenario",
]
