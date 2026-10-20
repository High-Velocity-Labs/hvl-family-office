"""
Server-Side Rendering (SSR) view-model builders for Family Office Dashboard.
Delegates to the modular `ssr` package while preserving 100% backward compatibility.
"""

from __future__ import annotations

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
from ssr.settings import build_ssr_settings as _orig_build_ssr_settings
from routes.helpers import is_sandbox_session
from services.sandbox_service import get_sandbox_lease_info


def get_sandbox_template_context(family_id: int = 0) -> dict:
    """Returns standard sandbox view-model variables for SSR templates."""
    is_sb = is_sandbox_session()
    lease = get_sandbox_lease_info(family_id) if (is_sb and family_id > 0) else None
    return {
        "is_sandbox": is_sb,
        "sandbox_lease": lease,
    }


def build_ssr_settings(
    family_id: int = 0,
    active_tab: str | None = None,
    adv_search: str | None = None,
    adv_page: str | None = None,
    adv_pinned_only: bool = False,
) -> dict:
    """Prepares SSR data for Settings modal/tab, augmenting with sandbox lease info."""
    res = _orig_build_ssr_settings(
        family_id=family_id,
        active_tab=active_tab,
        adv_search=adv_search,
        adv_page=adv_page,
        adv_pinned_only=adv_pinned_only,
    )
    is_sb = is_sandbox_session()
    res["is_sandbox"] = is_sb
    res["sandbox_lease"] = get_sandbox_lease_info(family_id) if (is_sb and family_id > 0) else None
    if is_sb:
        res["invites_enabled"] = False
        res["invites"] = []
        res["can_invite_new_household"] = False
        res["support_access_enabled"] = False
    return res


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
    "get_sandbox_template_context",
]
