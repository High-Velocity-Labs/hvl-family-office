"""
db/estate.py: Normalized SQLAlchemy 2.0 ORM repository for estate planning profiles.
Operates on `EstateProfile` with transparent per-family `TypeDecorator` Fernet encryption.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from db.household_assumptions import get_dict_section, merge_dict_section
from db.models import EstateProfile
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)

ESTATE_PLANNING_KEY = "estate_planning"


def get_estate_planning_assumptions(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """The household's `estate_planning` assumption section ({} when never saved)."""
    return get_dict_section(family_id=family_id, section_key=ESTATE_PLANNING_KEY, db_path=db_path)


def merge_estate_planning_assumptions(
    family_id: int = 0,
    updates: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Merges `updates` into the `estate_planning` assumption section and returns the merged section."""
    if not family_id or family_id <= 0 or not isinstance(updates, dict):
        return {}
    return merge_dict_section(family_id=family_id, section_key=ESTATE_PLANNING_KEY, updates=updates, db_path=db_path)


def toggle_estate_audit_item(
    family_id: int = 0,
    finding_id: str = "",
    verified: Optional[bool] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> List[str]:
    """Adds or removes `finding_id` in `estate_planning.verified_audit_ids` and returns the updated list."""
    clean_id = str(finding_id or "").strip()
    if not family_id or family_id <= 0 or not clean_id:
        return []
    ep = get_estate_planning_assumptions(family_id=family_id, db_path=db_path)
    raw_ids = ep.get("verified_audit_ids")
    verified_list: List[str] = [str(x) for x in raw_ids if x] if isinstance(raw_ids, list) else []
    should_verify = (clean_id not in verified_list) if verified is None else bool(verified)
    if should_verify:
        if clean_id not in verified_list:
            verified_list.append(clean_id)
        verified_list = verified_list[-100:]
    else:
        verified_list = [x for x in verified_list if x != clean_id]
    merge_estate_planning_assumptions(
        family_id=family_id,
        updates={"verified_audit_ids": verified_list},
        db_path=db_path,
    )
    return verified_list


def get_estate_profile_row(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Reads the family's estate profile from `estate_profiles`."""
    if not family_id:
        return {}
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return {}

    with get_orm_session(path, family_id=family_id) as session:
        row = session.get(EstateProfile, family_id)
        if not row:
            return {}
        return row.to_dict()


def save_estate_profile_row(
    family_id: int = 0,
    profile: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Atomically upserts a family's estate profile in `estate_profiles`."""
    if not family_id or not isinstance(profile, dict):
        return

    state = str(profile.get("state_of_residence") or profile.get("state") or "")
    marital = str(profile.get("marital_status") or "married_joint")
    prior_gifts = float(profile.get("prior_lifetime_taxable_gifts", 0.0) or 0.0)
    dsue = float(profile.get("dsue_ported_from_predeceased_spouse", 0.0) or 0.0)
    char_pct = float(
        profile.get("charitable_bequest_pct", profile.get("charitable_pct", 0.0)) or 0.0
    )
    char_fixed = float(profile.get("charitable_bequest_fixed", 0.0) or 0.0)
    ilit = float(profile.get("ilit_death_benefit", 0.0) or 0.0)
    trust_assets = float(profile.get("trust_transferred_assets", 0.0) or 0.0)
    probate_pct = float(profile.get("estimated_probate_admin_pct", 0.015) or 0.015)
    sunset = (
        1
        if profile.get(
            "apply_2026_tcja_sunset", profile.get("apply_tcja_sunset", False)
        )
        else 0
    )

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        session.merge(
            EstateProfile(
                family_id=family_id,
                state_of_residence=state,
                marital_status=marital,
                prior_lifetime_taxable_gifts_enc=prior_gifts,
                dsue_ported_enc=dsue,
                charitable_bequest_pct_enc=char_pct,
                charitable_bequest_fixed_enc=char_fixed,
                ilit_death_benefit_enc=ilit,
                trust_transferred_assets_enc=trust_assets,
                estimated_probate_admin_pct_enc=probate_pct,
                apply_2026_tcja_sunset=sunset,
                payload_enc=profile,
            )
        )
