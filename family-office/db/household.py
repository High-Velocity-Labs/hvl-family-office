"""
Repository for Household Profile and Household Member entities (`household_profile`, `users`).
Uses SQLAlchemy 2.0 ORM (`HouseholdProfile`, `User`) with scoped database resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select

from db.models import HouseholdProfile, User
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def get_household_profile(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves household profile assumptions for family_id."""
    if not family_id:
        return None
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return None
    try:
        with get_orm_session(path, family_id=family_id) as session:
            prof = session.get(HouseholdProfile, family_id)
            if not prof:
                return None
            return prof.to_dict()
    except Exception as e:
        logger.warning("Error fetching household profile for family %s: %s", family_id, e)
        return None


def get_annual_spending(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> float:
    """Returns annual spending baseline from household profile, or 0.0."""
    prof = get_household_profile(family_id=family_id, db_path=db_path)
    if prof and prof.get("annual_spending"):
        try:
            return float(prof["annual_spending"])
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def get_household_members(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns list of household members (users) for family_id."""
    if not family_id:
        return []
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []
    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(User).where(User.family_id == family_id).order_by(User.user_id.asc())
            return [
                {
                    "user_id": u.user_id,
                    "relationship": u.relationship_type,
                    "name": u.name,
                    "role": u.role,
                }
                for u in session.scalars(stmt).all()
            ]
    except Exception as e:
        logger.warning("Error fetching household members for family %s: %s", family_id, e)
        return []
