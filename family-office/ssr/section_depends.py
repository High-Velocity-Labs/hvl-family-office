"""
ssr/section_depends.py: the one source of truth for which domain versions each page section depends on.
Templates render `data-depends` from `section_depends(section_id)` (a Jinja global injected in `app.py`),
`ssr/dashboard.SECTION_METADATA` and its fragment ETags read the same table, and the browser reads only the
rendered `data-depends` attribute. Nothing else may carry a copy.
"""

from __future__ import annotations

SECTION_DEPENDS: dict[str, tuple[str, ...]] = {
    "section-overview": (
        "balance_sheet", "accounts", "equity", "scenarios", "household.identity", "household.members",
        "onboarding.checklist", "compensation", "holdings",
    ),
    "section-scenarios": (
        "balance_sheet", "accounts", "holdings", "equity", "tax_profile", "compensation", "household.members",
        "household.identity", "college", "philanthropy", "gifting", "estate",
    ),
    "section-equity": ("equity", "balance_sheet", "tax_profile"),
    "section-holdings": ("holdings", "holdings.policy", "accounts", "balance_sheet"),
    "section-arbitrage": ("tax_profile", "compensation", "equity", "household.identity"),
    "section-compensation": ("compensation", "tax_profile", "household.members"),
    "section-philanthropy": ("philanthropy", "tax_profile"),
    "section-gifting": ("gifting", "household.members"),
    "section-estate": ("estate", "balance_sheet", "gifting", "household.members", "household.identity"),
    "section-college": ("college", "accounts", "household.members"),
    "section-accounts": ("accounts", "holdings", "balance_sheet"),
    "section-settings": ("settings.invites", "household.identity"),
}


def section_depends(section_id: str) -> str:
    """Returns the comma-joined `data-depends` value for `section_id`; unknown sections are a template bug."""
    return ",".join(SECTION_DEPENDS[section_id])
