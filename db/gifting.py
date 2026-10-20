"""
Repository for Family Gifting Program (`gift_recipients` and `gifts` tables).
Uses SQLAlchemy 2.0 ORM (`GiftRecipient`, `AnnualGift`) with `lazy="selectin"` relationship
loading, transparent `TypeDecorator` encryption, and automatic `after_commit` invalidation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, func, select

import config
from db.models import AnnualGift, GiftRecipient
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def list_gift_recipients(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves all gift recipient groups for family_id.
    Strictly isolated: returns empty list if family_id is 0.
    """
    if not family_id:
        return []

    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = (
                select(GiftRecipient)
                .where(GiftRecipient.family_id == family_id)
                .order_by(GiftRecipient.recipient_group_name.asc())
            )
            return [r.to_dict() for r in session.scalars(stmt).all()]
    except Exception as e:
        logger.warning("Error listing gift recipients for family %s: %s", family_id, e)
        return []


def upsert_gift_recipient(
    family_id: int = 0,
    recipient_group_name: str = "",
    member_count: Optional[int] = None,
    relationship: str = "",
    notes: str = "",
    old_recipient_group_name: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Creates or updates a gift recipient group, supporting renaming via `old_recipient_group_name`.
    """
    if not family_id or not recipient_group_name:
        return {"success": False, "error": "Invalid family_id or recipient name"}

    try:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            target_lookup = (
                old_recipient_group_name
                if (old_recipient_group_name and old_recipient_group_name != recipient_group_name)
                else recipient_group_name
            )
            row = session.scalars(
                select(GiftRecipient).where(
                    GiftRecipient.family_id == family_id,
                    GiftRecipient.recipient_group_name == target_lookup,
                )
            ).first()
            if row is None and target_lookup != recipient_group_name:
                row = session.scalars(
                    select(GiftRecipient).where(
                        GiftRecipient.family_id == family_id,
                        GiftRecipient.recipient_group_name == recipient_group_name,
                    )
                ).first()

            if row is not None:
                eff_count = int(member_count) if member_count is not None else int(row.member_count or 1)
                eff_rel = relationship if relationship else (row.relationship_type or "")
                eff_notes = notes if notes else (row.notes or "")
                row.recipient_group_name = recipient_group_name
                row.member_count = eff_count
                row.relationship_type = eff_rel
                row.notes = eff_notes
                session.flush()
                rec_id = row.recipient_id
            else:
                max_recipients = int(getattr(config, "MAX_GIFT_RECIPIENTS", 50))
                current_count = int(
                    session.scalar(
                        select(func.count())
                        .select_from(GiftRecipient)
                        .where(GiftRecipient.family_id == family_id)
                    )
                    or 0
                )
                if current_count >= max_recipients:
                    raise ValueError(
                        f"Maximum of {max_recipients} gift recipients per household reached."
                    )
                eff_count = int(member_count) if member_count is not None else 1
                new_rec = GiftRecipient(
                    family_id=family_id,
                    recipient_group_name=recipient_group_name,
                    member_count=eff_count,
                    relationship_type=relationship,
                    notes=notes,
                )
                session.add(new_rec)
                session.flush()
                rec_id = new_rec.recipient_id

        return {
            "success": True,
            "recipient_id": rec_id,
            "recipient_group_name": recipient_group_name,
            "member_count": eff_count,
            "relationship": relationship,
            "notes": notes,
        }
    except ValueError:
        raise
    except Exception as e:
        logger.warning("Error upserting gift recipient for family %s: %s", family_id, e)
        return {"success": False, "error": str(e)}


def list_gifts(
    family_id: int = 0,
    year: Optional[int] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves all gifts for family_id, optionally filtered by year.
    Strictly isolated: returns empty list if family_id is 0.
    """
    if not family_id:
        return []

    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = (
                select(AnnualGift)
                .join(AnnualGift.recipient)
                .where(AnnualGift.family_id == family_id)
            )
            if year is not None:
                stmt = stmt.where(AnnualGift.year == year).order_by(
                    AnnualGift.gift_id.asc()
                )
            else:
                stmt = stmt.order_by(AnnualGift.year.asc(), AnnualGift.gift_id.asc())
            return [g.to_dict() for g in session.scalars(stmt).all()]
    except Exception as e:
        logger.warning("Error listing gifts for family %s: %s", family_id, e)
        return []


def record_gift(
    family_id: int = 0,
    recipient_id: int = 0,
    year: int = 2026,
    amount: float = 0.0,
    notes: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Upserts an encrypted gift entry for a recipient and year."""
    if not family_id or not recipient_id or amount < 0:
        return {"success": False, "error": "Invalid gift parameters"}

    try:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            existing = session.scalars(
                select(AnnualGift).where(
                    AnnualGift.family_id == family_id,
                    AnnualGift.recipient_id == recipient_id,
                    AnnualGift.year == int(year),
                )
            ).first()
            rounded_amt = round(float(amount), 2)
            if existing is not None:
                existing.amount = rounded_amt
                if notes:
                    existing.notes = notes
                session.flush()
                gift_id = existing.gift_id
            else:
                max_records = int(getattr(config, "MAX_GIFT_RECORDS", 1000))
                current_count = int(
                    session.scalar(
                        select(func.count())
                        .select_from(AnnualGift)
                        .where(AnnualGift.family_id == family_id)
                    )
                    or 0
                )
                if current_count >= max_records:
                    raise ValueError(
                        f"Maximum of {max_records} gift records per household reached."
                    )
                new_gift = AnnualGift(
                    family_id=family_id,
                    recipient_id=recipient_id,
                    year=int(year),
                    amount=rounded_amt,
                    notes=notes,
                )
                session.add(new_gift)
                session.flush()
                gift_id = new_gift.gift_id

        return {
            "success": True,
            "gift_id": gift_id,
            "recipient_id": recipient_id,
            "year": year,
            "amount": amount,
            "notes": notes,
        }
    except ValueError:
        raise
    except Exception as e:
        logger.warning("Error recording gift for family %s: %s", family_id, e)
        return {"success": False, "error": str(e)}


def delete_gift(
    family_id: int = 0,
    gift_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Deletes a specific gift entry, strictly isolated by family_id."""
    if not family_id or not gift_id:
        return False

    try:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            res = session.execute(
                delete(AnnualGift).where(
                    AnnualGift.gift_id == gift_id,
                    AnnualGift.family_id == family_id,
                )
            )
            return (res.rowcount or 0) > 0
    except Exception as e:
        logger.warning(
            "Error deleting gift %s for family %s: %s", gift_id, family_id, e
        )
        return False


def copy_gifts_to_year(
    family_id: int = 0,
    recipient_amounts: Optional[Dict[str, float]] = None,
    to_year: int = 2026,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Copies recipient gift amounts into a target year in the SQLite `gifts` table."""
    if not family_id or not recipient_amounts:
        return

    try:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            max_records = int(getattr(config, "MAX_GIFT_RECORDS", 1000))
            current_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(AnnualGift)
                    .where(AnnualGift.family_id == family_id)
                )
                or 0
            )
            for rec_name, amt in recipient_amounts.items():
                rec = session.scalars(
                    select(GiftRecipient).where(
                        GiftRecipient.family_id == family_id,
                        GiftRecipient.recipient_group_name == rec_name,
                    )
                ).first()
                if rec is None:
                    continue
                existing = session.scalars(
                    select(AnnualGift).where(
                        AnnualGift.family_id == family_id,
                        AnnualGift.recipient_id == rec.recipient_id,
                        AnnualGift.year == int(to_year),
                    )
                ).first()
                rounded_amt = round(float(amt), 2)
                if existing is not None:
                    existing.amount = rounded_amt
                else:
                    if current_count >= max_records:
                        raise ValueError(
                            f"Maximum of {max_records} gift records per household reached."
                        )
                    current_count += 1
                    session.add(
                        AnnualGift(
                            family_id=family_id,
                            recipient_id=rec.recipient_id,
                            year=int(to_year),
                            amount=rounded_amt,
                        )
                    )
    except ValueError:
        raise
    except Exception as e:
        logger.warning(
            "Error copying gifts to year %s for family %s: %s", to_year, family_id, e
        )


def delete_recipient_gifts(
    family_id: int = 0,
    recipient_group_name: str = "",
    year: Optional[Union[int, str]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Deletes a recipient's gifts for a given year, or the recipient and all their gifts if year is omitted."""
    if not family_id or not recipient_group_name:
        return False

    try:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            rec = session.scalars(
                select(GiftRecipient).where(
                    GiftRecipient.family_id == family_id,
                    GiftRecipient.recipient_group_name == recipient_group_name,
                )
            ).first()
            if rec is None:
                return False
            if year:
                session.execute(
                    delete(AnnualGift).where(
                        AnnualGift.family_id == family_id,
                        AnnualGift.recipient_id == rec.recipient_id,
                        AnnualGift.year == int(year),
                    )
                )
            else:
                session.execute(
                    delete(AnnualGift).where(
                        AnnualGift.family_id == family_id,
                        AnnualGift.recipient_id == rec.recipient_id,
                    )
                )
                session.execute(
                    delete(GiftRecipient).where(
                        GiftRecipient.family_id == family_id,
                        GiftRecipient.recipient_id == rec.recipient_id,
                    )
                )
            return True
    except Exception as e:
        logger.warning(
            "Error deleting recipient %s for family %s: %s",
            recipient_group_name,
            family_id,
            e,
        )
        return False


def count_gift_recipients(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Returns the total number of gift recipient groups for family_id."""
    if not family_id:
        return 0
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return 0
    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(func.count()).select_from(GiftRecipient).where(GiftRecipient.family_id == family_id)
            return int(session.scalar(stmt) or 0)
    except Exception as e:
        logger.warning("Error counting gift recipients for family %s: %s", family_id, e)
        return 0

