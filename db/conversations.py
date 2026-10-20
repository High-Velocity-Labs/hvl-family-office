"""
Repository for AI Advisor conversations and messages.
Uses SQLAlchemy 2.0 ORM (`AdvisorConversation`, `AdvisorMessage`) with `lazy="selectin"`
relationship loading and transparent `TypeDecorator` encryption.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

from sqlalchemy import delete, func, or_, select, text

import config
from db.models import AdvisorConversation, AdvisorMessage
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def ensure_conversation_tables(db_path: Optional[Union[str, Path]] = None) -> None:
    """Ensures advisor conversation and message tables exist."""
    path = resolve_db_path(db_path)
    try:
        with get_orm_session(
            path, family_id=0, commit=True, invalidate_cache=False
        ) as session:
            session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS advisor_conversations (
                        conversation_id TEXT PRIMARY KEY,
                        family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
                        page_section TEXT NOT NULL DEFAULT 'section-overview',
                        title TEXT NOT NULL,
                        created_by TEXT,
                        is_pinned INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_adv_conv_fam ON advisor_conversations(family_id, page_section, updated_at DESC)"
                )
            )
            session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_adv_conv_pinned ON advisor_conversations(family_id, is_pinned DESC, updated_at DESC)"
                )
            )
            session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS advisor_messages (
                        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT NOT NULL REFERENCES advisor_conversations(conversation_id) ON DELETE CASCADE,
                        family_id INTEGER NOT NULL REFERENCES families(family_id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_adv_msg_conv ON advisor_messages(conversation_id, created_at ASC)"
                )
            )
    except Exception as e:
        logger.warning("Error ensuring advisor tables: %s", e)


def list_conversations(
    family_id: int = 0,
    page_section: str = "",
    search_query: str = "",
    pinned_only: bool = False,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns saved conversations for the active family, optionally filtered."""
    if not family_id:
        return []

    path = resolve_db_path(db_path, family_id=family_id)
    ensure_conversation_tables(path)

    with get_orm_session(path, family_id=family_id) as session:
        stmt = select(AdvisorConversation).where(
            AdvisorConversation.family_id == family_id
        )
        if page_section:
            stmt = stmt.where(AdvisorConversation.page_section == page_section)
        if pinned_only:
            stmt = stmt.where(AdvisorConversation.is_pinned == 1)
        if search_query:
            pattern = f"%{search_query.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(AdvisorConversation.title).like(pattern),
                    func.lower(AdvisorConversation.page_section).like(pattern),
                )
            )
        stmt = stmt.order_by(
            AdvisorConversation.is_pinned.desc(),
            AdvisorConversation.updated_at.desc(),
        )
        convs = session.scalars(stmt).all()
        out: List[Dict[str, Any]] = []
        for conv in convs:
            msgs = conv.messages or []
            last_msg = msgs[-1].content if msgs else ""
            out.append(
                {
                    "conversation_id": conv.conversation_id,
                    "family_id": conv.family_id,
                    "page_section": conv.page_section,
                    "title": conv.title,
                    "created_by": conv.created_by or "Family Member",
                    "is_pinned": bool(conv.is_pinned),
                    "created_at": conv.created_at,
                    "updated_at": conv.updated_at,
                    "message_count": len(msgs),
                    "last_message": str(last_msg or "")[:140],
                }
            )
        return out


def get_conversation(
    conv_id: str,
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves full conversation details and all associated messages for family_id."""
    if not family_id or not conv_id:
        return None

    path = resolve_db_path(db_path, family_id=family_id)
    ensure_conversation_tables(path)

    with get_orm_session(path, family_id=family_id) as session:
        conv = session.scalars(
            select(AdvisorConversation).where(
                AdvisorConversation.conversation_id == conv_id,
                AdvisorConversation.family_id == family_id,
            )
        ).first()
        if not conv:
            return None

        messages = [
            m.to_dict() for m in (conv.messages or []) if m.family_id == family_id
        ]
        return {
            "conversation_id": conv.conversation_id,
            "family_id": conv.family_id,
            "page_section": conv.page_section,
            "title": conv.title,
            "created_by": conv.created_by or "Family Member",
            "is_pinned": bool(conv.is_pinned),
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "messages": messages,
        }


def get_conversation_messages(
    conv_id: str,
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns only the message list for a conversation."""
    if not family_id or not conv_id:
        return []

    path = resolve_db_path(db_path, family_id=family_id)
    ensure_conversation_tables(path)

    with get_orm_session(path, family_id=family_id) as session:
        stmt = (
            select(AdvisorMessage)
            .where(
                AdvisorMessage.conversation_id == conv_id,
                AdvisorMessage.family_id == family_id,
            )
            .order_by(
                AdvisorMessage.created_at.asc(),
                AdvisorMessage.message_id.asc(),
            )
        )
        return [m.to_dict() for m in session.scalars(stmt).all()]


def create_conversation(
    conv_id: str,
    family_id: int = 0,
    page_section: str = "section-overview",
    title: str = "New Advisory Thread",
    created_by: str = "Family Member",
    db_path: Optional[Union[str, Path]] = None,
) -> str:
    """Inserts a new conversation record."""
    if not family_id:
        raise ValueError("Valid family_id is required to create a conversation.")

    actual_id = conv_id or uuid.uuid4().hex[:16]
    path = resolve_db_path(db_path, family_id=family_id)
    ensure_conversation_tables(path)

    with get_orm_session(
        path, family_id=family_id, commit=True, invalidate_cache=False
    ) as session:
        max_convs = int(getattr(config, "MAX_ADVISOR_CONVERSATIONS", 50))
        conv_count = int(
            session.scalar(
                select(func.count())
                .select_from(AdvisorConversation)
                .where(AdvisorConversation.family_id == family_id)
            )
            or 0
        )
        if conv_count >= max_convs:
            raise ValueError(
                f"Maximum of {max_convs} AI Advisor conversations per household reached."
            )

        session.add(
            AdvisorConversation(
                conversation_id=actual_id,
                family_id=family_id,
                page_section=page_section,
                title=title,
                created_by=created_by,
                is_pinned=0,
            )
        )
    return actual_id


def update_conversation(
    conv_id: str,
    family_id: int = 0,
    title: Optional[str] = None,
    is_pinned: Optional[bool] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Updates title and/or pin status of an existing conversation."""
    if not family_id or not conv_id:
        return False
    if (title is None or not title.strip()) and is_pinned is None:
        return False

    path = resolve_db_path(db_path, family_id=family_id)
    ensure_conversation_tables(path)

    with get_orm_session(
        path, family_id=family_id, commit=True, invalidate_cache=False
    ) as session:
        conv = session.scalars(
            select(AdvisorConversation).where(
                AdvisorConversation.conversation_id == conv_id,
                AdvisorConversation.family_id == family_id,
            )
        ).first()
        if not conv:
            return False
        if title is not None and title.strip():
            conv.title = title.strip()
        if is_pinned is not None:
            conv.is_pinned = 1 if is_pinned else 0
        return True


def add_message(
    conv_id: str,
    family_id: int = 0,
    role: str = "user",
    content: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Appends a new turn to `advisor_messages` and touches conversation `updated_at`."""
    if not family_id or not conv_id or not content:
        return

    path = resolve_db_path(db_path, family_id=family_id)
    ensure_conversation_tables(path)

    with get_orm_session(
        path, family_id=family_id, commit=True, invalidate_cache=False
    ) as session:
        max_msgs = int(getattr(config, "MAX_ADVISOR_MESSAGES_PER_CONV", 200))
        msg_count = int(
            session.scalar(
                select(func.count())
                .select_from(AdvisorMessage)
                .where(
                    AdvisorMessage.conversation_id == conv_id,
                    AdvisorMessage.family_id == family_id,
                )
            )
            or 0
        )
        if msg_count >= max_msgs:
            raise ValueError(
                f"Maximum of {max_msgs} messages per conversation reached. Please start a new conversation."
            )

        session.add(
            AdvisorMessage(
                conversation_id=conv_id,
                family_id=family_id,
                role=role,
                content=content,
            )
        )
        session.execute(
            text(
                "UPDATE advisor_conversations SET updated_at = CURRENT_TIMESTAMP WHERE conversation_id = :cid AND family_id = :fid"
            ),
            {"cid": conv_id, "fid": family_id},
        )


append_message = add_message


def delete_conversation(
    conv_id: str,
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Deletes a conversation and its messages."""
    if not family_id or not conv_id:
        return False

    path = resolve_db_path(db_path, family_id=family_id)
    ensure_conversation_tables(path)

    with get_orm_session(
        path, family_id=family_id, commit=True, invalidate_cache=False
    ) as session:
        session.execute(
            delete(AdvisorMessage).where(
                AdvisorMessage.conversation_id == conv_id,
                AdvisorMessage.family_id == family_id,
            )
        )
        res = session.execute(
            delete(AdvisorConversation).where(
                AdvisorConversation.conversation_id == conv_id,
                AdvisorConversation.family_id == family_id,
            )
        )
        return (res.rowcount or 0) > 0


def bulk_delete_conversations(
    conv_ids: List[str],
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Deletes multiple conversations in a single transaction."""
    if not family_id or not conv_ids:
        return 0

    sanitized = [str(c).strip() for c in conv_ids if str(c).strip()]
    if not sanitized:
        return 0

    path = resolve_db_path(db_path, family_id=family_id)
    ensure_conversation_tables(path)

    with get_orm_session(
        path, family_id=family_id, commit=True, invalidate_cache=False
    ) as session:
        session.execute(
            delete(AdvisorMessage).where(
                AdvisorMessage.family_id == family_id,
                AdvisorMessage.conversation_id.in_(sanitized),
            )
        )
        res = session.execute(
            delete(AdvisorConversation).where(
                AdvisorConversation.family_id == family_id,
                AdvisorConversation.conversation_id.in_(sanitized),
            )
        )
        return int(res.rowcount or 0)
