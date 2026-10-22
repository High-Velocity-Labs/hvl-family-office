"""
Shared Layer 1 SQLAlchemy 2.0 ORM Models & Repository for Household Notifications
and W3C Web Push Subscriptions (`hvl_common.db.notifications`).

Enforces column-level Fernet encryption at rest (`EncryptedString` for `title` and `body`),
in-place `dedupe_key` upsert for unread stateful notifications, auto-resolution by `dedupe_key`,
and self-authored collaboration broadcast filtering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select, update

from hvl_common.db.push_subscriptions import (
    HouseholdNotification,
    HvlNotificationMixin,
    HvlPushSubscriptionMixin,
    NotificationBase,
    PushSubscription,
    _ACTIVE_MODELS,
    _open_session,
    _resolve_tenant_id,
    _utc_now_iso,
    create_notification_models,
    delete_push_subscription,
    get_member_push_subscriptions,
    save_push_subscription,
)
from hvl_common.security.sanitize import sanitize_text


def create_or_update_notification(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    family_id: int = 0,
    recipient_email: str = "*",
    sender_email: str = "",
    sender_name: str = "",
    category: str = "general",
    dedupe_key: str = "",
    conversation_id: str = "",
    title: str = "",
    body: str = "",
    deep_link: str = "/",
    channel: str = "in_app",
    is_read: int = 0,
    db_path: Path | str | None = None,
    notif_model: Any = None,
) -> dict[str, Any]:
    """Creates or upserts an unread notification by `(household_id, recipient_email, dedupe_key)`."""
    eff_id = _resolve_tenant_id(household_id, family_id)
    if eff_id <= 0:
        return {}
    model = notif_model or _ACTIVE_MODELS.get("notif") or HouseholdNotification
    clean_recipient = sanitize_text(recipient_email or "*", max_length=254, default="*").lower()
    clean_sender_email = sanitize_text(sender_email, max_length=254, default="").lower()
    clean_sender_name = sanitize_text(sender_name, max_length=120, default="")
    clean_category = sanitize_text(category or "general", max_length=64, default="general").lower()
    clean_dedupe = sanitize_text(dedupe_key, max_length=160, default="")
    clean_conv_id = sanitize_text(conversation_id, max_length=128, default="")
    clean_title = sanitize_text(title, max_length=240, default="")
    clean_body = sanitize_text(body, max_length=1000, multiline=True, default="")
    clean_deep_link = sanitize_text(deep_link or "/", max_length=500, default="/")
    clean_channel = sanitize_text(channel or "in_app", max_length=40, default="in_app")
    read_flag = 1 if int(is_read or 0) else 0
    now_iso = _utc_now_iso()

    with _open_session(
        session_scope_fn,
        db_path,
        eff_id,
        member_email=clean_recipient if clean_recipient != "*" else clean_sender_email,
        commit=True,
    ) as session:
        existing = None
        if clean_dedupe:
            stmt = select(model).where(
                model.household_id == eff_id,
                func.lower(model.recipient_email) == clean_recipient,
                model.dedupe_key == clean_dedupe,
            )
            if read_flag == 0:
                stmt = stmt.where(model.is_read == 0)
            existing = session.scalars(stmt.order_by(model.id.desc())).first()

        if existing is not None:
            if clean_title or read_flag == 0:
                existing.title = clean_title
            if clean_body or read_flag == 0:
                existing.body = clean_body
            existing.deep_link = clean_deep_link
            existing.category = clean_category
            existing.sender_email = clean_sender_email
            existing.sender_name = clean_sender_name
            existing.conversation_id = clean_conv_id
            existing.channel = clean_channel
            existing.is_read = read_flag
            existing.created_at = now_iso
            row = existing
        else:
            row = model(
                household_id=eff_id,
                recipient_email=clean_recipient,
                sender_email=clean_sender_email,
                sender_name=clean_sender_name,
                category=clean_category,
                dedupe_key=clean_dedupe,
                conversation_id=clean_conv_id,
                title=clean_title,
                body=clean_body,
                deep_link=clean_deep_link,
                channel=clean_channel,
                is_read=read_flag,
                created_at=now_iso,
            )
            session.add(row)
        session.flush()
        session.refresh(row)
        return row.to_dict()


create_notification = create_or_update_notification


def resolve_notification_by_dedupe_key(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    family_id: int = 0,
    dedupe_key: str,
    recipient_email: str | None = None,
    db_path: Path | str | None = None,
    notif_model: Any = None,
) -> int:
    """Marks any unread notification matching `(household_id, dedupe_key)` as read (`is_read = 1`)."""
    eff_id = _resolve_tenant_id(household_id, family_id)
    clean_dedupe = sanitize_text(dedupe_key, max_length=160, default="")
    if eff_id <= 0 or not clean_dedupe:
        return 0
    model = notif_model or _ACTIVE_MODELS.get("notif") or HouseholdNotification
    with _open_session(session_scope_fn, db_path, eff_id, commit=True) as session:
        stmt = update(model).where(
            model.household_id == eff_id,
            model.dedupe_key == clean_dedupe,
            model.is_read == 0,
        )
        if recipient_email is not None:
            clean_recip = sanitize_text(recipient_email, max_length=254, default="").lower()
            stmt = stmt.where(func.lower(model.recipient_email) == clean_recip)
        res = session.execute(stmt.values(is_read=1))
        return int(res.rowcount or 0)


def list_active_notifications(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    family_id: int = 0,
    recipient_email: str = "",
    include_read: bool = False,
    limit: int = 30,
    db_path: Path | str | None = None,
    notif_model: Any = None,
) -> list[dict[str, Any]]:
    """Lists notifications for `(household_id, recipient_email in [email, '*'])`."""
    eff_id = _resolve_tenant_id(household_id, family_id)
    if eff_id <= 0:
        return []
    model = notif_model or _ACTIVE_MODELS.get("notif") or HouseholdNotification
    clean_email = (recipient_email or "").strip().lower()
    targets = [clean_email, "*"] if clean_email else ["*"]

    with _open_session(
        session_scope_fn, db_path, eff_id, member_email=clean_email, invalidate_cache=False
    ) as session:
        stmt = select(model).where(
            model.household_id == eff_id,
            func.lower(model.recipient_email).in_(targets),
        )
        if not include_read:
            stmt = stmt.where(model.is_read == 0)
        rows = session.scalars(stmt.order_by(model.id.desc())).all()
        items: list[dict[str, Any]] = []
        for r in rows:
            d = r.to_dict()
            if (
                d["recipient_email"] == "*"
                and d["category"] == "collaboration"
                and clean_email
                and d["sender_email"].lower() == clean_email
            ):
                continue
            items.append(d)
            if len(items) >= max(1, int(limit or 30)):
                break
        return items


def list_read_dedupe_keys(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    family_id: int = 0,
    recipient_email: str = "",
    db_path: Path | str | None = None,
    notif_model: Any = None,
) -> set[str]:
    """Returns non-empty `dedupe_key` values already marked read (`is_read == 1`)."""
    eff_id = _resolve_tenant_id(household_id, family_id)
    if eff_id <= 0:
        return set()
    model = notif_model or _ACTIVE_MODELS.get("notif") or HouseholdNotification
    clean_email = (recipient_email or "").strip().lower()
    targets = [clean_email, "*"] if clean_email else ["*"]
    with _open_session(
        session_scope_fn, db_path, eff_id, member_email=clean_email, invalidate_cache=False
    ) as session:
        rows = session.scalars(
            select(model.dedupe_key).where(
                model.household_id == eff_id,
                func.lower(model.recipient_email).in_(targets),
                model.is_read == 1,
                model.dedupe_key != "",
            )
        ).all()
        return {str(k) for k in rows if k}


def mark_notifications_read(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    family_id: int = 0,
    recipient_email: str = "",
    notification_ids: list[int] | None = None,
    dedupe_keys: list[str] | None = None,
    db_path: Path | str | None = None,
    notif_model: Any = None,
) -> int:
    """Marks matching unread notifications as read (`is_read = 1`)."""
    eff_id = _resolve_tenant_id(household_id, family_id)
    if eff_id <= 0:
        return 0
    model = notif_model or _ACTIVE_MODELS.get("notif") or HouseholdNotification
    clean_email = (recipient_email or "").strip().lower()
    targets = [clean_email, "*"] if clean_email else ["*"]
    with _open_session(
        session_scope_fn, db_path, eff_id, member_email=clean_email, commit=True
    ) as session:
        stmt = update(model).where(
            model.household_id == eff_id,
            func.lower(model.recipient_email).in_(targets),
            model.is_read == 0,
        )
        filters = []
        if notification_ids is not None:
            clean_ids = [int(nid) for nid in notification_ids if str(nid).isdigit()]
            if clean_ids:
                filters.append(model.id.in_(clean_ids))
        if dedupe_keys is not None:
            clean_keys = [sanitize_text(k, max_length=160, default="") for k in dedupe_keys]
            clean_keys = [k for k in clean_keys if k]
            if clean_keys:
                filters.append(model.dedupe_key.in_(clean_keys))
        if (notification_ids is not None or dedupe_keys is not None) and not filters:
            return 0
        if filters:
            stmt = stmt.where(or_(*filters))
        res = session.execute(stmt.values(is_read=1))
        return int(res.rowcount or 0)


def clear_all_notifications(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    family_id: int = 0,
    recipient_email: str = "",
    db_path: Path | str | None = None,
    notif_model: Any = None,
) -> int:
    """Deletes notifications for `(household_id, recipient_email in [email, '*'])`."""
    eff_id = _resolve_tenant_id(household_id, family_id)
    if eff_id <= 0:
        return 0
    model = notif_model or _ACTIVE_MODELS.get("notif") or HouseholdNotification
    clean_email = (recipient_email or "").strip().lower()
    targets = [clean_email, "*"] if clean_email else ["*"]
    with _open_session(
        session_scope_fn, db_path, eff_id, member_email=clean_email, commit=True
    ) as session:
        res = session.execute(
            delete(model).where(
                model.household_id == eff_id,
                func.lower(model.recipient_email).in_(targets),
            )
        )
        return int(res.rowcount or 0)


__all__ = [
    "HvlNotificationMixin",
    "HvlPushSubscriptionMixin",
    "NotificationBase",
    "HouseholdNotification",
    "PushSubscription",
    "create_notification_models",
    "create_or_update_notification",
    "create_notification",
    "resolve_notification_by_dedupe_key",
    "list_active_notifications",
    "list_read_dedupe_keys",
    "mark_notifications_read",
    "clear_all_notifications",
    "save_push_subscription",
    "delete_push_subscription",
    "get_member_push_subscriptions",
]
