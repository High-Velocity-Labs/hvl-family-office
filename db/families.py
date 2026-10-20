"""
Repository for Family entities, Household Profiles, and Account Roles.
Uses SQLAlchemy 2.0 ORM (`Family`, `HouseholdProfile`, `AccountRole`) with automatic
`after_commit` cache invalidation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import func, select

from db.models import (
    AccountRole,
    Family,
    FamilyEncryptedStore,
    ForecastScenario,
    HouseholdProfile,
)
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def get_household_profile(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Retrieves household profile assumptions for family_id.
    Strictly isolated: returns None if family_id is 0 or unseeded.
    """
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
        logger.warning(
            "Error fetching household profile for family %s: %s", family_id, e
        )
        return None


def upsert_household_profile(
    family_id: int = 0,
    state: str = "WA",
    filing_status: str = "MFJ",
    annual_spending: float = 0.0,
    annual_savings: float = 0.0,
    retirement_age: int = 65,
    inflation_rate: float = 0.025,
    assumptions_json: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Inserts or updates the household profile for family_id."""
    if not family_id:
        raise ValueError("Valid family_id is required to update profile.")

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        existing = session.get(HouseholdProfile, family_id)
        if existing is not None:
            existing.state = state
            existing.filing_status = filing_status
            existing.annual_spending = annual_spending
            existing.annual_savings = annual_savings
            existing.retirement_age = retirement_age
            existing.inflation_rate = inflation_rate
            if assumptions_json is not None:
                existing.assumptions_json = assumptions_json
        else:
            session.add(
                HouseholdProfile(
                    family_id=family_id,
                    state=state,
                    filing_status=filing_status,
                    annual_spending=annual_spending,
                    annual_savings=annual_savings,
                    retirement_age=retirement_age,
                    inflation_rate=inflation_rate,
                    assumptions_json=assumptions_json or "{}",
                )
            )


def get_account_roles(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all account roles configured for family_id."""
    if not family_id:
        return []

    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(AccountRole).where(AccountRole.family_id == family_id)
            return [r.to_dict() for r in session.scalars(stmt).all()]
    except Exception as e:
        logger.warning("Error fetching account roles for family %s: %s", family_id, e)
        return []


def upsert_account_role(
    family_id: int = 0,
    monarch_account_id: str = "",
    role: str = "",
    beneficiary_user_id: Optional[int] = None,
    is_hidden_from_family_office: Optional[int] = None,
    is_user_confirmed: int = 1,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Sets or overrides an account role and beneficiary mapping for family_id."""
    if not family_id or not monarch_account_id:
        return

    hidden_val = is_hidden_from_family_office
    if hidden_val is None:
        hidden_val = (
            1
            if role
            in (
                "company_equity_nso",
                "tax_liability",
                "hidden_from_family_office",
                "manual_tax_offset",
            )
            else 0
        )

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        existing = session.scalars(
            select(AccountRole).where(
                AccountRole.family_id == family_id,
                AccountRole.monarch_account_id == monarch_account_id,
            )
        ).first()

        if existing is not None:
            existing.role = role
            existing.beneficiary_user_id = beneficiary_user_id
            existing.is_hidden_from_family_office = hidden_val
            existing.is_user_confirmed = is_user_confirmed
        else:
            session.add(
                AccountRole(
                    family_id=family_id,
                    monarch_account_id=monarch_account_id,
                    role=role,
                    beneficiary_user_id=beneficiary_user_id,
                    is_hidden_from_family_office=hidden_val,
                    is_user_confirmed=is_user_confirmed,
                )
            )


def confirm_all_roles(
    family_id: int = 0,
    role_updates: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Confirms multiple account role classifications in a transaction."""
    if not family_id or not role_updates:
        return 0

    count = 0
    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        for item in role_updates:
            acc_id = str(item.get("monarch_account_id") or "")
            if not acc_id:
                continue
            role = str(item.get("role") or "")
            ben_id = item.get("beneficiary_user_id")
            hidden = item.get("is_hidden_from_family_office", 0)

            existing = session.scalars(
                select(AccountRole).where(
                    AccountRole.family_id == family_id,
                    AccountRole.monarch_account_id == acc_id,
                )
            ).first()

            if existing is not None:
                existing.is_user_confirmed = 1
            else:
                session.add(
                    AccountRole(
                        family_id=family_id,
                        monarch_account_id=acc_id,
                        role=role,
                        beneficiary_user_id=ben_id,
                        is_hidden_from_family_office=hidden,
                        is_user_confirmed=1,
                    )
                )
            count += 1
    return count


def get_family(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves family metadata and settings, strictly scoped by family_id."""
    if not family_id:
        return None

    import security

    path = resolve_db_path(db_path, family_id=family_id)
    return security.get_family(Path(path), family_id=family_id)


def ensure_default_family(
    family_id: int = 0,
    name: str = "Primary Family Office",
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Ensures family record exists without overwriting existing data."""
    if not family_id:
        return

    with get_orm_session(
        db_path, family_id=family_id, commit=True, invalidate_cache=False
    ) as session:
        existing = session.get(Family, family_id)
        if existing is None:
            session.add(
                Family(
                    family_id=family_id,
                    name=name,
                    settings='{"primary_state": "WA", "tax_filing_status": "MFJ"}',
                )
            )


def set_support_access(
    family_id: int = 0,
    enabled: bool = False,
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Sets the uniform tenant support access flag (`families.support_access_enabled`)."""
    if not family_id or int(family_id) <= 0:
        return False

    import security

    path = resolve_db_path(db_path, family_id=family_id)
    return security.set_family_support_access(
        Path(path), family_id=int(family_id), enabled=bool(enabled)
    )


def is_support_access_enabled(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Returns True if the specified tenant has explicitly enabled developer/admin support access."""
    if not family_id or int(family_id) <= 0:
        return False

    fam = get_family(family_id=int(family_id), db_path=db_path)
    if not fam:
        return False
    return bool(fam.get("support_access_enabled", False))


def update_household_assumptions_key(
    family_id: int = 0,
    section_key: str = "",
    section_value: Any = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Updates a single top-level key inside `household_profile.assumptions_json`."""
    if not family_id or not section_key:
        return

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        prof = session.get(HouseholdProfile, family_id)
        if prof is None:
            prof = HouseholdProfile(
                family_id=family_id,
                assumptions_json=json.dumps({section_key: section_value}),
            )
            session.add(prof)
            return
        assump: Dict[str, Any] = {}
        if prof.assumptions_json:
            try:
                assump = json.loads(prof.assumptions_json)
            except Exception:
                assump = {}
        assump[section_key] = section_value
        prof.assumptions_json = json.dumps(assump)


def update_household_metrics(
    family_id: int = 0,
    annual_spending: Optional[float] = None,
    annual_savings: Optional[float] = None,
    retirement_age: Optional[int] = None,
    inflation_rate: Optional[float] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Partially updates core numeric metrics on `household_profile`."""
    if not family_id or not any(
        v is not None
        for v in (annual_spending, annual_savings, retirement_age, inflation_rate)
    ):
        return

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        prof = session.get(HouseholdProfile, family_id)
        if prof is None:
            return
        if annual_spending is not None:
            prof.annual_spending = annual_spending
        if annual_savings is not None:
            prof.annual_savings = annual_savings
        if retirement_age is not None:
            prof.retirement_age = retirement_age
        if inflation_rate is not None:
            prof.inflation_rate = inflation_rate


def is_demo_database_seeded(db_path: Union[str, Path]) -> bool:
    """Checks whether the demo database has all required demo families and forecast records seeded."""
    import config

    path = Path(db_path)
    if not path.exists() or path.stat().st_size < 1024:
        return False

    try:
        with get_orm_session(path, family_id=0) as session:
            all_fams = session.execute(select(Family.name, Family.settings)).all()
            if not any(name == "The Foster Family" for name, _ in all_fams):
                return False
            miller_settings = [settings for name, settings in all_fams if name == "The Miller Family"]
            if miller_settings and "Seattle" not in (miller_settings[0] or ""):
                return False


            scen_count = hist_count = 0
            try:
                scen_count = int(session.scalar(select(func.count(func.distinct(ForecastScenario.family_id)))) or 0)
                if scen_count < 7:
                    legacy_scen = int(session.scalar(select(func.count()).where(FamilyEncryptedStore.key == "scenario_system_state")) or 0)
                    scen_count = max(scen_count, legacy_scen)
                hist_count = int(session.scalar(select(func.count()).where(FamilyEncryptedStore.key == "historical_forecast_actuals")) or 0)
            except Exception:
                pass

        if scen_count < 7 or hist_count < 6:
            fam_scen = fam_hist = 0
            for fid in range(1, 8):
                fam_db = config.get_family_db_path(fid, universe="demo")
                if not fam_db.exists():
                    fam_db = path.parent / "families" / f"{fid}.db"
                if not fam_db.exists():
                    continue
                with get_orm_session(fam_db, family_id=fid) as fs:
                    if (fs.scalar(select(func.count()).select_from(ForecastScenario).where(ForecastScenario.family_id == fid)) or 0) > 0 or (
                        fs.scalar(select(func.count()).where(FamilyEncryptedStore.family_id == fid, FamilyEncryptedStore.key == "scenario_system_state")) or 0
                    ) > 0:
                        fam_scen += 1
                    if (fs.scalar(select(func.count()).where(FamilyEncryptedStore.family_id == fid, FamilyEncryptedStore.key == "historical_forecast_actuals")) or 0) > 0:
                        fam_hist += 1
            scen_count, hist_count = max(scen_count, fam_scen), max(hist_count, fam_hist)

        return scen_count >= 7 and hist_count >= 6
    except Exception:
        return False


