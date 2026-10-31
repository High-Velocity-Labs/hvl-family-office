"""
The household's state of residence as the tax engines need it: one normalized code, or unset.

Every equity, advisor and forecast tax path reads the state from here, so a figure never depends on whether
the caller happened to pass a family id.
"""

from __future__ import annotations

from services import residence_state


def household_state(family_id: int = 0) -> str:
    """
    The supported two-letter state of `family_id`'s household profile, or `residence_state.UNSET`.
    Without a family id it is the household of the current request or background job; with no household
    at all it is UNSET, which every engine taxes as "no state tax", never as a particular state.
    """
    from db.families import get_household_profile

    fam_id = int(family_id or 0)
    if fam_id <= 0:
        from services.request_context import get_current_family_id

        fam_id = max(int(get_current_family_id()), 0)
    if fam_id <= 0:
        return residence_state.UNSET
    profile = get_household_profile(family_id=fam_id) or {}
    return residence_state.normalize(profile.get("state"))
