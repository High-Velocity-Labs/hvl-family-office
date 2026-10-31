"""
Server-Side Rendering (SSR) view-model builders package.
Prepares formatted display strings for initial HTML rendering across all dashboard tabs.
"""

from ssr.accounts import (
    build_ssr_accounts,
    build_ssr_arbitrage,
    build_ssr_compensation,
)
from ssr.equity import build_ssr_equity
from ssr.formatting import (
    fmt_currency,
    fmt_short_currency,
    get_private_investments_data,
)
from ssr.holdings import (
    HOLDINGS_PRESETS,
    build_ssr_holdings,
)
from ssr.overview import build_ssr_overview
from ssr.planning import (
    build_ssr_college,
    build_ssr_estate,
    build_ssr_gifting,
    build_ssr_philanthropy,
)
from ssr.scenarios import build_ssr_scenarios
from ssr.settings import build_ssr_settings

__all__ = [
    "HOLDINGS_PRESETS",
    "build_ssr_accounts",
    "build_ssr_arbitrage",
    "build_ssr_college",
    "build_ssr_compensation",
    "build_ssr_equity",
    "build_ssr_estate",
    "build_ssr_gifting",
    "build_ssr_holdings",
    "build_ssr_overview",
    "build_ssr_philanthropy",
    "build_ssr_scenarios",
    "build_ssr_settings",
    "fmt_currency",
    "fmt_short_currency",
    "get_private_investments_data",
]
