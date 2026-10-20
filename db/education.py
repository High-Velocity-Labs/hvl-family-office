"""
Repository for Tuition and Education records (`tuition` and `tuition_year_records` tables).
Uses SQLAlchemy 2.0 ORM (`TuitionRecord`, `TuitionYearRecord`) with transparent `TypeDecorator` encryption.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, func, or_, select

import config
from db.models import TuitionRecord, TuitionYearRecord
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def list_tuition_records(
    family_id: int = 0,
    child_user_id: Optional[int] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves decrypted tuition entries for family_id, optionally filtered by child_user_id.
    Strictly isolated: returns empty list if family_id is 0.
    """
    if not family_id:
        return []

    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(TuitionRecord).where(TuitionRecord.family_id == family_id)
            if child_user_id is not None:
                stmt = stmt.where(TuitionRecord.child_user_id == child_user_id)
            stmt = stmt.order_by(
                TuitionRecord.school_year.asc(), TuitionRecord.tuition_id.asc()
            )
            return [r.to_dict() for r in session.scalars(stmt).all()]
    except Exception as e:
        logger.warning("Error listing tuition records for family %s: %s", family_id, e)
        return []


def upsert_tuition_record(
    family_id: int = 0,
    child_user_id: int = 0,
    school_year: str = "",
    tuition_amount: float = 0.0,
    is_projected: bool = False,
    notes: str = "",
    school_name: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Creates or updates an encrypted tuition record for a specific child and school year."""
    if not family_id or not child_user_id or not school_year:
        return {"success": False, "error": "Invalid tuition parameters"}

    try:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            existing = session.scalars(
                select(TuitionRecord).where(
                    TuitionRecord.family_id == family_id,
                    TuitionRecord.child_user_id == child_user_id,
                    TuitionRecord.school_year == school_year,
                )
            ).first()

            if existing is not None:
                existing.tuition_amount = float(tuition_amount or 0.0)
                existing.is_projected = 1 if is_projected else 0
                existing.notes = notes
                if school_name:
                    existing.school_name = school_name
                session.flush()
                t_id = existing.tuition_id
            else:
                max_records = int(getattr(config, "MAX_TUITION_RECORDS", 500))
                current_count = int(
                    session.scalar(
                        select(func.count())
                        .select_from(TuitionRecord)
                        .where(TuitionRecord.family_id == family_id)
                    )
                    or 0
                )
                if current_count >= max_records:
                    raise ValueError(
                        f"Maximum of {max_records} tuition records per household reached."
                    )

                new_rec = TuitionRecord(
                    family_id=family_id,
                    child_user_id=child_user_id,
                    school_year=school_year,
                    school_name=school_name,
                    tuition_amount=float(tuition_amount or 0.0),
                    is_projected=1 if is_projected else 0,
                    notes=notes,
                )
                session.add(new_rec)
                session.flush()
                t_id = new_rec.tuition_id

        return {
            "success": True,
            "tuition_id": t_id,
            "child_user_id": child_user_id,
            "school_year": school_year,
            "amount": tuition_amount,
            "is_projected": is_projected,
            "notes": notes,
        }
    except ValueError:
        raise
    except Exception as e:
        logger.warning(
            "Error upserting tuition record for family %s: %s", family_id, e
        )
        return {"success": False, "error": str(e)}


def delete_tuition_by_year(
    family_id: int = 0,
    school_year: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Deletes all tuition rows for a specific school year for family_id."""
    if not family_id or not school_year:
        return 0

    try:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            res = session.execute(
                delete(TuitionRecord).where(
                    TuitionRecord.family_id == family_id,
                    TuitionRecord.school_year == school_year,
                )
            )
            return int(res.rowcount or 0)
    except Exception as e:
        logger.warning(
            "Error deleting tuition for year %s, family %s: %s",
            school_year,
            family_id,
            e,
        )
        return 0


def get_latest_high_school_grad_year(
    family_id: int = 0,
    child_user_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[int]:
    """Finds the graduation year from high school tuition records for a child, if present."""
    if not family_id or not child_user_id:
        return None

    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return None

    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(func.max(TuitionRecord.school_year)).where(
                TuitionRecord.child_user_id == child_user_id,
                TuitionRecord.family_id == family_id,
                or_(
                    TuitionRecord.school_name.ilike("%high school%"),
                    TuitionRecord.school_name.ilike("%hs%"),
                    TuitionRecord.notes.ilike("%high school%"),
                    TuitionRecord.notes.ilike("%hs%"),
                    TuitionRecord.notes.ilike("%12th%"),
                    TuitionRecord.notes.ilike("%senior%"),
                ),
                ~func.coalesce(TuitionRecord.school_name, "").ilike("%college%"),
                ~func.coalesce(TuitionRecord.school_name, "").ilike("%university%"),
                ~func.coalesce(TuitionRecord.notes, "").ilike("%college%"),
            )
            max_sy = session.scalar(stmt)
            if max_sy:
                parts = str(max_sy).split("-")
                if len(parts) > 1:
                    return int(parts[1])
            return None
    except Exception:
        return None


def list_tuition_year_records(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns decrypted list of per-year school tuition records from `tuition_year_records`."""
    if not family_id:
        return []
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = (
                select(TuitionYearRecord)
                .where(TuitionYearRecord.family_id == family_id)
                .order_by(TuitionYearRecord.school_year.asc())
            )
            return [r.to_dict() for r in session.scalars(stmt).all()]
    except Exception as e:
        logger.warning(
            "Error reading tuition_year_records for family %s: %s", family_id, e
        )
        return []


def get_tuition_store_payload(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Reconstructs `{"records": [...], "summary": {...}}` from `tuition_year_records`."""
    records = list_tuition_year_records(family_id=family_id, db_path=db_path)
    if not records:
        return {"records": []}
    total_actual = sum(
        float(r.get("total", 0.0) or 0.0)
        for r in records
        if not r.get("is_projected")
    )
    total_projected = sum(
        float(r.get("total", 0.0) or 0.0)
        for r in records
        if r.get("is_projected")
    )
    return {
        "records": records,
        "summary": {
            "total_actual_paid": round(total_actual, 2),
            "total_projected": round(total_projected, 2),
            "grand_total": round(total_actual + total_projected, 2),
        },
    }


def upsert_tuition_year_record(
    family_id: int = 0,
    school_year: str = "",
    record: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Atomically upserts a single school year record into `tuition_year_records`."""
    if not family_id or not school_year or not isinstance(record, dict):
        return

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        existing = session.get(TuitionYearRecord, (family_id, str(school_year)))
        if existing is None:
            max_years = int(getattr(config, "MAX_TUITION_YEARS", 50))
            current_years = int(
                session.scalar(
                    select(func.count())
                    .select_from(TuitionYearRecord)
                    .where(TuitionYearRecord.family_id == family_id)
                )
                or 0
            )
            if current_years >= max_years:
                raise ValueError(
                    f"Maximum of {max_years} tuition school years per household reached."
                )

        school_name = str(record.get("school") or record.get("school_name") or "")
        total_amt = float(record.get("total", 0.0) or 0.0)
        is_proj = 1 if record.get("is_projected") else 0
        notes = str(record.get("notes") or "")
        session.merge(
            TuitionYearRecord(
                family_id=family_id,
                school_year=str(school_year),
                school_name_enc=school_name,
                total_amount_enc=total_amt,
                is_projected=is_proj,
                notes_enc=notes,
                payload_enc=record,
            )
        )


def delete_tuition_year_record(
    family_id: int = 0,
    school_year: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Atomically deletes a single school year record from `tuition_year_records`."""
    if not family_id or not school_year:
        return 0

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        res = session.execute(
            delete(TuitionYearRecord).where(
                TuitionYearRecord.family_id == family_id,
                TuitionYearRecord.school_year == str(school_year),
            )
        )
        return int(res.rowcount or 0)


def save_tuition_store_payload(
    family_id: int = 0,
    payload: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Atomically replaces all `tuition_year_records` for a family from a tuition payload dict."""
    if not family_id or not isinstance(payload, dict):
        return
    records = payload.get("records") if isinstance(payload.get("records"), list) else []

    by_year: Dict[str, TuitionYearRecord] = {}
    for rec in records:
        if not isinstance(rec, dict) or not rec.get("school_year"):
            continue
        sy = str(rec["school_year"])
        school_name = str(rec.get("school") or rec.get("school_name") or "")
        total_amt = float(rec.get("total", 0.0) or 0.0)
        is_proj = 1 if rec.get("is_projected") else 0
        notes = str(rec.get("notes") or "")
        by_year[sy] = TuitionYearRecord(
            family_id=family_id,
            school_year=sy,
            school_name_enc=school_name,
            total_amount_enc=total_amt,
            is_projected=is_proj,
            notes_enc=notes,
            payload_enc=rec,
        )

    max_years = int(getattr(config, "MAX_TUITION_YEARS", 50))
    if len(by_year) > max_years:
        raise ValueError(
            f"Maximum of {max_years} tuition school years per household reached."
        )

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        session.execute(
            delete(TuitionYearRecord).where(TuitionYearRecord.family_id == family_id)
        )
        if by_year:
            session.add_all(by_year.values())


from db.education_helpers import (
    build_college_education_payload,
    load_tuition_records,
    parse_grade_index,
    save_tuition_year_entry,
)

__all__ = [
    "list_tuition_records",
    "upsert_tuition_record",
    "delete_tuition_by_year",
    "get_latest_high_school_grad_year",
    "list_tuition_year_records",
    "get_tuition_store_payload",
    "upsert_tuition_year_record",
    "delete_tuition_year_record",
    "save_tuition_store_payload",
    "parse_grade_index",
    "load_tuition_records",
    "build_college_education_payload",
    "save_tuition_year_entry",
]

