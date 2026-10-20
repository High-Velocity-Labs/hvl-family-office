"""
Thin backward-compatibility re-export facade for decomposed SSR wealth modules (`ssr.equity`, `ssr.holdings`, `ssr.accounts`).
"""

from __future__ import annotations
import logging

import db
import equity_engine
import monarch_service
import security
from ssr.accounts import (
    build_ssr_accounts,
    build_ssr_arbitrage,
    build_ssr_compensation,
)
from ssr.equity import build_ssr_equity
from ssr.formatting import fmt_currency, fmt_short_currency, get_private_investments_data
from ssr.holdings import HOLDINGS_PRESETS, build_ssr_holdings

logger = logging.getLogger(__name__)

__all__ = [
    "HOLDINGS_PRESETS",
    "build_ssr_accounts",
    "build_ssr_arbitrage",
    "build_ssr_compensation",
    "build_ssr_equity",
    "build_ssr_holdings",
    "db",
    "equity_engine",
    "fmt_currency",
    "fmt_short_currency",
    "get_private_investments_data",
    "monarch_service",
    "security",
]
