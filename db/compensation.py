"""
Repository for Career Compensation records (`compensation` table).
Uses SQLAlchemy 2.0 ORM (`CompensationRecord`) with transparent `TypeDecorator` column encryption.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, func, select

import config
from db.models import CompensationRecord, User
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def list_compensation_records(
    family_id: int = 0,
    user_id: Optional[int] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves decrypted compensation rows for a family, optionally filtered by user_id.
    Strictly isolated: returns empty list if family_id is 0.
    """
    if not family_id:
        return []

    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(CompensationRecord).where(
                CompensationRecord.family_id == family_id
            )
            if user_id is not None:
                stmt = stmt.where(CompensationRecord.user_id == user_id)
            stmt = stmt.order_by(
                CompensationRecord.tax_year.desc(),
                CompensationRecord.comp_id.desc(),
            )
            return [r.to_dict() for r in session.scalars(stmt).all()]
    except Exception as e:
        logger.warning(
            "Error listing compensation records for family %s: %s", family_id, e
        )
        return []


def upsert_compensation_record(
    family_id: int = 0,
    year: int = 2026,
    company: str = "",
    salary: float = 0.0,
    bonus: float = 0.0,
    source: str = "Manual Entry",
    user_id: Optional[int] = None,
    original_year: Optional[int] = None,
    original_company: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Inserts or updates an encrypted compensation record in the database."""
    if not family_id:
        return {"success": False, "error": "Invalid family_id"}

    try:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            db_user_id = user_id
            if db_user_id is not None and session.get(User, db_user_id) is None:
                db_user_id = None

            lookup_yr = int(original_year) if original_year is not None else int(year)
            lookup_comp = (original_company or company or "").lower()
            rows = session.scalars(
                select(CompensationRecord).where(
                    CompensationRecord.family_id == family_id,
                    CompensationRecord.tax_year == lookup_yr,
                )
            ).all()

            target: Optional[CompensationRecord] = None
            for r in rows:
                if (
                    db_user_id is not None
                    and r.user_id is not None
                    and r.user_id != db_user_id
                ):
                    continue
                dec_emp = (r.employer_name or "").lower()
                if dec_emp == lookup_comp or (lookup_comp and lookup_comp in dec_emp):
                    target = r
                    break

            if target is None:
                for r in rows:
                    dec_emp = (r.employer_name or "").lower()
                    if dec_emp == lookup_comp or (
                        lookup_comp and lookup_comp in dec_emp
                    ):
                        target = r
                        break

            if (
                target is None
                and len(rows) == 1
                and (
                    original_year is not None
                    or bool(original_company)
                    or not lookup_comp
                )
            ):
                target = rows[0]

            if target is not None:
                target.tax_year = int(year)
                target.base_salary = float(salary or 0.0)
                target.bonus = float(bonus or 0.0)
                target.notes = source
                if db_user_id is not None:
                    target.user_id = db_user_id
                target.employer_name = company
                session.flush()
                comp_id = target.comp_id
            else:
                max_records = int(getattr(config, "MAX_COMPENSATION_RECORDS", 200))
                current_count = int(
                    session.scalar(
                        select(func.count())
                        .select_from(CompensationRecord)
                        .where(CompensationRecord.family_id == family_id)
                    )
                    or 0
                )
                if current_count >= max_records:
                    raise ValueError(
                        f"Maximum of {max_records} compensation records per household reached."
                    )

                new_rec = CompensationRecord(
                    family_id=family_id,
                    user_id=db_user_id,
                    tax_year=int(year),
                    employer_name=company,
                    base_salary=float(salary or 0.0),
                    bonus=float(bonus or 0.0),
                    notes=source,
                )
                session.add(new_rec)
                session.flush()
                comp_id = new_rec.comp_id

        return {
            "success": True,
            "comp_id": comp_id,
            "year": year,
            "company": company,
            "salary": salary,
            "bonus": bonus,
            "source": source,
            "user_id": user_id,
        }
    except ValueError:
        raise
    except Exception as e:
        logger.warning(
            "Error upserting compensation record for family %s: %s", family_id, e
        )
        return {"success": False, "error": str(e)}


save_compensation_records = upsert_compensation_record


def delete_compensation_record_by_year(
    family_id: int = 0,
    year: int = 2026,
    company_filter: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """
    Deletes compensation record(s) for a family and tax year, optionally filtering by company name.
    Returns the count of deleted rows.
    """
    if not family_id:
        return 0

    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return 0

    try:
        with get_orm_session(path, family_id=family_id, commit=True) as session:
            if company_filter:
                rows = session.scalars(
                    select(CompensationRecord).where(
                        CompensationRecord.family_id == family_id,
                        CompensationRecord.tax_year == year,
                    )
                ).all()
                count = 0
                filt = company_filter.lower()
                for r in rows:
                    if filt in (r.employer_name or "").lower():
                        session.delete(r)
                        count += 1
                return count

            res = session.execute(
                delete(CompensationRecord).where(
                    CompensationRecord.family_id == family_id,
                    CompensationRecord.tax_year == year,
                )
            )
            return int(res.rowcount or 0)
    except Exception as e:
        logger.warning(
            "Error deleting compensation record for family %s: %s", family_id, e
        )
        return 0


def get_latest_compensation(
    family_id: int = 0,
    user_id: Optional[int] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves the most recent compensation record for a user in the family."""
    if not family_id or user_id is None:
        return None
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return None
    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = (
                select(CompensationRecord)
                .where(
                    CompensationRecord.family_id == family_id,
                    CompensationRecord.user_id == user_id,
                )
                .order_by(
                    CompensationRecord.tax_year.desc(),
                    CompensationRecord.comp_id.desc(),
                )
                .limit(1)
            )
            rec = session.scalars(stmt).first()
            return rec.to_dict() if rec is not None else None
    except Exception as e:
        logger.warning(
            "Error fetching latest compensation for family %s, user %s: %s",
            family_id,
            user_id,
            e,
        )
        return None

