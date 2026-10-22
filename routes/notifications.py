"""
Layer 2 & 3 Notification Bell, Drawer Fragment, and Web Push Blueprint (`routes/notifications.py`).
Mounts `create_notifications_blueprint` at `/api/notifications` and provides sync-outcome helpers.
"""

from __future__ import annotations

from typing import Any
from flask import session
from hvl_common.web.notifications import (
    create_notifications_blueprint,
    get_merged_notifications,
    render_notifications_fragment_response as _render_notifications_fragment_response,
)

import db
from db.domain_versions import bump_domains
from db.models_ops import HouseholdNotification, PushSubscription
from db.notifications import (
    emit_family_notification,
    get_family_computed_alerts,
    resolve_family_notification,
)
from db.session import get_orm_session, resolve_db_path
from routes.helpers import DB_PATH, _is_demo_session, get_current_db_path, get_current_family_id, get_current_universe


def _get_notification_context() -> dict[str, Any]:
    fid = get_current_family_id()
    uni = get_current_universe()
    role = str(session.get("role") or "editor").strip().lower()
    is_demo = bool(_is_demo_session() or uni == "demo" or (uni == "beta" and role != "admin"))
    is_auth = bool(fid > 0 and (session.get("authenticated") or session.get("is_demo") or session.get("is_sandbox")))
    email = str(session.get("user_email") or "").strip().lower()
    target_db = get_current_db_path(family_id=fid) if fid > 0 else DB_PATH
    return {
        "family_id": fid, "household_id": fid, "email": email, "role": role,
        "is_demo": is_demo, "is_authenticated": is_auth, "db_path": target_db,
    }


def get_session_notifications(family_id: int = 0) -> list[dict[str, Any]]:
    fid = int(family_id or get_current_family_id() or 0)
    if fid <= 0:
        return []
    return get_merged_notifications(
        get_orm_session, household_id=fid, email=str(session.get("user_email") or "").strip().lower(),
        db_path=get_current_db_path(family_id=fid), notif_model=HouseholdNotification,
        computed_alerts_fn=get_family_computed_alerts,
    )


def render_notifications_fragment_response(items: list[dict[str, Any]]):
    return _render_notifications_fragment_response(items)


def record_sync_outcome_notification(family_id: int = 0, sync_res: Any = None, db_path: Any = None) -> Any:
    fid = int(family_id or 0)
    if fid <= 0:
        return sync_res
    if not isinstance(sync_res, dict) or not sync_res.get("success"):
        emit_family_notification(
            db_path, family_id=fid, category="async_job", dedupe_key="job:sync:status",
            deep_link="/?settings=integrations", title="Account sync failed",
            body="Check your SimpleFIN or Monarch connection credentials.",
        )
        return sync_res
    resolve_family_notification(db_path, family_id=fid, dedupe_key="job:sync:status")
    resolve_family_notification(db_path, family_id=fid, dedupe_key="health:sync_stale")
    try:
        target_db = resolve_db_path(db_path, family_id=fid)
        accounts = db.accounts.list_accounts(family_id=fid, db_path=target_db) or []
        roles = db.families.get_account_roles(family_id=fid, db_path=target_db) or []
        confirmed = {str(r.get("monarch_account_id")) for r in roles if r.get("is_user_confirmed")}
        unconfirmed = sum(
            1 for a in accounts
            if not a.get("isManual") and not str(a.get("id") or "").startswith("manual_")
            and str(a.get("id") or "") not in confirmed
        )
        if unconfirmed > 0:
            emit_family_notification(
                target_db, family_id=fid, category="async_job", dedupe_key="job:sync:unconfirmed_roles",
                deep_link="/accounts", title=f"{unconfirmed} synced account(s) need role review",
                body="Confirm account classifications so net worth and tax projections stay accurate.",
            )
        else:
            resolve_family_notification(target_db, family_id=fid, dedupe_key="job:sync:unconfirmed_roles")
    except Exception:
        pass
    return sync_res


notifications_bp = create_notifications_blueprint(
    _get_notification_context, get_orm_session, notif_model=HouseholdNotification,
    push_model=PushSubscription, bump_domains_fn=bump_domains, computed_alerts_fn=get_family_computed_alerts,
)
