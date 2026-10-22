"""
Layer 1 Household Notification & Web Push Repository Wrapper (`db/notifications.py`).
Binds `hvl_common.db.notifications` to `db.session.get_orm_session`, `HouseholdNotification`,
and `PushSubscription`, with locked-vault tolerance (`PermissionError`) and domain-version bumping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Any, Callable

from hvl_common.db.notifications import (
    clear_all_notifications as _clear_all_notifications,
    create_or_update_notification as _create_or_update_notification,
    delete_push_subscription as _delete_push_subscription,
    get_member_push_subscriptions as _get_member_push_subscriptions,
    list_active_notifications as _list_active_notifications,
    list_read_dedupe_keys as _list_read_dedupe_keys,
    mark_notifications_read as _mark_notifications_read,
    resolve_notification_by_dedupe_key as _resolve_notification_by_dedupe_key,
    save_push_subscription as _save_push_subscription,
)

from db.domain_versions import bump_domains
from db.models_ops import HouseholdNotification, PushSubscription
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def _call_notif(
    fn: Callable[..., Any],
    family_id: int = 0,
    household_id: int = 0,
    db_path: Path | str | None = None,
    default: Any = None,
    is_push: bool = False,
    **kwargs: Any,
) -> Any:
    fid = int(family_id or household_id or 0)
    if fid <= 0:
        return default
    model_kw = {"push_model": PushSubscription} if is_push else {"notif_model": HouseholdNotification}
    return fn(
        get_orm_session,
        household_id=fid,
        db_path=resolve_db_path(db_path, family_id=fid),
        **model_kw,
        **kwargs,
    )


def create_or_update_notification(
    family_id: int = 0, *, household_id: int = 0, db_path: Path | str | None = None, **kwargs: Any
) -> dict[str, Any]:
    return _call_notif(_create_or_update_notification, family_id, household_id, db_path, {}, **kwargs)


create_notification = create_or_update_notification


def resolve_notification_by_dedupe_key(
    family_id: int = 0, dedupe_key: str = "", *, household_id: int = 0,
    recipient_email: str | None = None, db_path: Path | str | None = None,
) -> int:
    if not dedupe_key:
        return 0
    return _call_notif(
        _resolve_notification_by_dedupe_key, family_id, household_id, db_path, 0,
        dedupe_key=dedupe_key, recipient_email=recipient_email,
    )


def list_active_notifications(
    family_id: int = 0, recipient_email: str = "", *, household_id: int = 0,
    include_read: bool = False, limit: int = 30, db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    return _call_notif(
        _list_active_notifications, family_id, household_id, db_path, [],
        recipient_email=recipient_email, include_read=include_read, limit=limit,
    )


def list_read_dedupe_keys(
    family_id: int = 0, recipient_email: str = "", *, household_id: int = 0, db_path: Path | str | None = None,
) -> set[str]:
    return _call_notif(
        _list_read_dedupe_keys, family_id, household_id, db_path, set(), recipient_email=recipient_email,
    )


def mark_notifications_read(
    family_id: int = 0, recipient_email: str = "", *, household_id: int = 0,
    notification_ids: list[int] | None = None, dedupe_keys: list[str] | None = None,
    db_path: Path | str | None = None,
) -> int:
    return _call_notif(
        _mark_notifications_read, family_id, household_id, db_path, 0,
        recipient_email=recipient_email, notification_ids=notification_ids, dedupe_keys=dedupe_keys,
    )


def clear_all_notifications(
    family_id: int = 0, recipient_email: str = "", *, household_id: int = 0, db_path: Path | str | None = None,
) -> int:
    return _call_notif(
        _clear_all_notifications, family_id, household_id, db_path, 0, recipient_email=recipient_email,
    )


def save_push_subscription(
    family_id: int = 0, member_email: str = "", endpoint: str = "",
    p256dh: str = "", auth: str = "", device_label: str = "", *,
    household_id: int = 0, db_path: Path | str | None = None,
) -> dict[str, Any]:
    return _call_notif(
        _save_push_subscription, family_id, household_id, db_path, {}, is_push=True,
        member_email=member_email, endpoint=endpoint, p256dh=p256dh, auth=auth, device_label=device_label,
    )


def delete_push_subscription(
    family_id: int = 0, endpoint: str = "", *, household_id: int = 0,
    member_email: str | None = None, db_path: Path | str | None = None,
) -> int:
    return _call_notif(
        _delete_push_subscription, family_id, household_id, db_path, 0, is_push=True,
        endpoint=endpoint, member_email=member_email,
    )


def get_member_push_subscriptions(
    family_id: int = 0, member_email: str | None = None, *,
    household_id: int = 0, db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    return _call_notif(
        _get_member_push_subscriptions, family_id, household_id, db_path, [], is_push=True,
        member_email=member_email,
    )


def emit_family_notification(
    db_path: Any = None, family_id: int = 0, *, title: str = "", body: str = "",
    category: str = "general", dedupe_key: str = "", deep_link: str = "/",
    recipient_email: str = "*", sender_email: str = "", sender_name: str = "",
) -> dict[str, Any]:
    """Safely creates/updates a household notification and bumps the `notifications` domain."""
    fid = int(family_id or 0)
    if fid <= 0 or not title:
        return {}
    if category == "collaboration" and not sender_email:
        try:
            from flask import has_request_context, session as flask_session
            if has_request_context():
                sender_email = str(flask_session.get("user_email") or "")
                sender_name = sender_name or str(flask_session.get("user") or "")
        except Exception:
            pass
    try:
        target_db = resolve_db_path(db_path, family_id=fid)
        res = create_or_update_notification(
            family_id=fid, recipient_email=recipient_email, sender_email=sender_email,
            sender_name=sender_name, category=category, dedupe_key=dedupe_key,
            title=title, body=body, deep_link=deep_link, db_path=target_db,
        )
        bump_domains(fid, "notifications", state_db=target_db)
        return res
    except (PermissionError, Exception) as exc:
        logger.debug("Skipping notification emission for family %s: %s", fid, exc)
        return {}


def resolve_family_notification(
    db_path: Any = None, family_id: int = 0, dedupe_key: str = "", *,
    recipient_email: str | None = None,
) -> int:
    """Safely resolves unread notifications matching `dedupe_key` and bumps `notifications`."""
    fid = int(family_id or 0)
    if fid <= 0 or not dedupe_key:
        return 0
    try:
        target_db = resolve_db_path(db_path, family_id=fid)
        count = resolve_notification_by_dedupe_key(
            family_id=fid, dedupe_key=dedupe_key, recipient_email=recipient_email, db_path=target_db,
        )
        bump_domains(fid, "notifications", state_db=target_db)
        return count
    except (PermissionError, Exception) as exc:
        logger.debug("Skipping notification resolution for family %s: %s", fid, exc)
        return 0


def get_family_computed_alerts(
    family_id: int = 0, email: str = "", db_path: Any = None,
) -> list[dict[str, Any]]:
    """Computes live stateful alerts for stale sync providers (>7d) and Support Access ON."""
    fid = int(family_id or 0)
    if fid <= 0:
        return []
    alerts: list[dict[str, Any]] = []
    try:
        import security
        target_db = resolve_db_path(db_path, family_id=fid)
        if not target_db.exists():
            return []

        fam = security.get_family(target_db, family_id=fid) or {}
        if bool(fam.get("support_access_enabled")):
            alerts.append({
                "title": "Developer Support Access is ON",
                "body": "Your household vault key is currently escrowed for support. Review or lock when finished.",
                "category": "security", "dedupe_key": "security:support_access_on", "deep_link": "/?settings=members",
            })

        m_creds = security.db_load_encrypted(target_db, "monarch_credentials", family_id=fid) or {}
        s_creds = security.db_load_encrypted(target_db, "simplefin_credentials", family_id=fid) or {}
        has_provider = bool(
            (isinstance(m_creds, dict) and (m_creds.get("token") or m_creds.get("email")))
            or (isinstance(s_creds, dict) and s_creds.get("access_url"))
        )
        if has_provider:
            sync_meta = security.db_load_encrypted(target_db, "last_sync_metadata", family_id=fid) or {}
            sfin_meta = security.db_load_encrypted(target_db, "simplefin_sync_metadata", family_id=fid) or {}
            raw_ts = (
                (sync_meta.get("timestamp") if isinstance(sync_meta, dict) else None)
                or (sfin_meta.get("timestamp") if isinstance(sfin_meta, dict) else None)
            )
            if raw_ts:
                dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - dt > timedelta(days=7):
                    alerts.append({
                        "title": "Account sync is stale",
                        "body": "Connected accounts haven't synced in over 7 days.",
                        "category": "sync_health", "dedupe_key": "health:sync_stale",
                        "deep_link": "/?settings=integrations", "created_at": str(raw_ts),
                    })
    except (PermissionError, Exception) as exc:
        logger.debug("Computed alerts skipped for family %s: %s", fid, exc)
    return alerts
