"""
Settings view-model with sandbox-lease overrides applied (invites and support access are disabled in a sandbox).
"""

from __future__ import annotations

from services.request_context import is_sandbox_session
from services.sandbox_service import get_sandbox_lease_info
from ssr.settings import build_ssr_settings as build_base_ssr_settings


def build_ssr_settings(
    family_id: int = 0,
    active_tab: str | None = None,
    adv_search: str | None = None,
    adv_page: str | None = None,
    adv_pinned_only: bool = False,
) -> dict:
    """Prepares SSR data for Settings modal/tab, augmenting with sandbox lease info."""
    res = build_base_ssr_settings(
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
