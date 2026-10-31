"""
services/advisor/conversation_ownership.py: Who may continue, rename or delete an advisor thread.

Threads are owned by a stable identity: the login email, or `user:<id>` for sessions that have no email
(local desktop passphrase login, sandbox). Display names are user-chosen and never identify an owner.

Legacy rows store a first name (or an anonymous marker) in `created_by`. A caller may touch those only when
they may change household data AND their session display name matches; any turn on such a thread starts
TAINTED because its stored text cannot be attributed. No data migration is performed.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, List, Optional, Union

from flask import session

import db
from services.request_context import can_mutate
from services.advisor.tool_permissions import TurnTrust

_ANONYMOUS_LEGACY_OWNERS = frozenset({"Family Member", "Advisor Carryover", "Advisor Compact", "Demo Visitor"})
NOT_OWNER_MESSAGE = "You can only continue conversations you started."


class Ownership(Enum):
    OWNER = "owner"
    LEGACY_EDITOR = "legacy_editor"
    DENIED = "denied"


def caller_identity() -> str:
    """The caller's stable identity; PermissionError when the session carries none (never a shared fallback)."""
    email = str(session.get("user_email") or "").strip().lower()
    if email:
        return email
    uid = session.get("user_id")
    if uid:
        return f"user:{uid}"
    raise PermissionError("Your session has no stable identity; sign in again to use the advisor.")


def _is_stable_identity(created_by: str) -> bool:
    return "@" in created_by or created_by.startswith("user:")


def classify(created_by: Optional[str]) -> Ownership:
    stored = str(created_by or "")
    try:
        identity = caller_identity()
    except PermissionError:
        return Ownership.DENIED
    if stored.lower() == identity:
        return Ownership.OWNER
    if _is_stable_identity(stored) or not can_mutate():
        return Ownership.DENIED
    display = str(session.get("user") or "")
    if stored in _ANONYMOUS_LEGACY_OWNERS or (display and stored == display):
        return Ownership.LEGACY_EDITOR
    return Ownership.DENIED


def require_access(conv: dict) -> Ownership:
    ownership = classify(conv.get("created_by"))
    if ownership is Ownership.DENIED:
        raise PermissionError(NOT_OWNER_MESSAGE)
    return ownership


def history_trust(ownership: Ownership) -> TurnTrust:
    return TurnTrust.CLEAN if ownership is Ownership.OWNER else TurnTrust.TAINTED


def _load(conv_id: str, family_id: int, db_path: Union[str, Path]) -> Optional[dict]:
    return db.conversations.get_conversation(conv_id=conv_id, family_id=family_id, db_path=db_path)


def update_owned_conversation(conv_id: str, family_id: int, db_path: Any, title: Optional[str], is_pinned: Any) -> bool:
    conv = _load(conv_id, family_id, db_path)
    if not conv:
        return False
    require_access(conv)
    return db.conversations.update_conversation(
        conv_id=conv_id, family_id=family_id, title=title, is_pinned=is_pinned, db_path=db_path,
    )


def delete_owned_conversation(conv_id: str, family_id: int, db_path: Any) -> bool:
    conv = _load(conv_id, family_id, db_path)
    if not conv:
        return False
    require_access(conv)
    return db.conversations.delete_conversation(conv_id=conv_id, family_id=family_id, db_path=db_path)


def bulk_delete_owned_conversations(conv_ids: List[str], family_id: int, db_path: Any) -> int:
    """Deletes only the listed threads the caller may touch; the rest are skipped."""
    allowed = []
    for conv_id in conv_ids:
        conv = _load(conv_id, family_id, db_path)
        if conv and classify(conv.get("created_by")) is not Ownership.DENIED:
            allowed.append(conv_id)
    return db.conversations.bulk_delete_conversations(conv_ids=allowed, family_id=family_id, db_path=db_path) if allowed else 0
