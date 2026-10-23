"""
Shared Layer 2 & 3 Notification Blueprint Factory & W3C Web Push Dispatcher
(`hvl_common.web.notifications`).

Provides `dispatch_web_push`, `notify_and_push_member`, `get_merged_notifications`,
`render_notifications_fragment_response`, and `create_notifications_blueprint` with strict
demo/viewer read-only guardrails (`401`/`403`) and declarative `notifications` domain-version bumping.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from flask import Blueprint, Response, jsonify, make_response, request

from hvl_common.db.notifications import (
    clear_all_notifications,
    create_or_update_notification,
    list_active_notifications,
    list_read_dedupe_keys,
    mark_notifications_read,
)
from hvl_common.ui.notifications import render_notifications_drawer_items
from hvl_common.web.push_routes import (
    dispatch_web_push,
    notify_and_push_member,
    register_push_routes,
)

logger = logging.getLogger(__name__)


def get_merged_notifications(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    email: str = "",
    db_path: Any = None,
    notif_model: Any = None,
    computed_alerts_fn: Callable[[int, str, Any], list[dict[str, Any]]] | None = None,
    list_notifications_fn: Callable[..., list[dict[str, Any]]] | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Combines unread DB notifications with live computed alerts, deduplicating by `dedupe_key`."""
    hid = int(household_id or 0)
    if hid <= 0:
        return []
    clean_email = (email or "").strip().lower()
    if list_notifications_fn is not None:
        db_items = list(list_notifications_fn(hid, clean_email, db_path) or [])
    elif session_scope_fn is not None:
        db_items = list_active_notifications(
            session_scope_fn,
            household_id=hid,
            recipient_email=clean_email,
            include_read=False,
            limit=limit,
            db_path=db_path,
            notif_model=notif_model,
        )
    else:
        db_items = []
    if computed_alerts_fn is None:
        return db_items[:limit]

    seen_dedupe = {str(it.get("dedupe_key") or "") for it in db_items if it.get("dedupe_key")}
    read_dedupe = (
        list_read_dedupe_keys(
            session_scope_fn,
            household_id=hid,
            recipient_email=clean_email,
            db_path=db_path,
            notif_model=notif_model,
        )
        if session_scope_fn is not None
        else set()
    )
    try:
        computed_raw = computed_alerts_fn(hid, clean_email, db_path) or []
    except Exception as exc:
        logger.debug("computed_alerts_fn failed for household %s: %s", hid, exc)
        computed_raw = []

    merged: list[dict[str, Any]] = []
    for alert in computed_raw:
        if not isinstance(alert, dict):
            continue
        dkey = str(alert.get("dedupe_key") or "").strip()
        if dkey and (dkey in seen_dedupe or dkey in read_dedupe):
            continue
        if dkey:
            seen_dedupe.add(dkey)
        merged.append({
            "id": alert.get("id") or f"computed:{dkey or len(merged)}",
            "household_id": hid,
            "family_id": hid,
            "recipient_email": clean_email or "*",
            "sender_email": str(alert.get("sender_email") or ""),
            "sender_name": str(alert.get("sender_name") or "System"),
            "category": str(alert.get("category") or "sync_health"),
            "dedupe_key": dkey,
            "conversation_id": "",
            "title": str(alert.get("title") or "Alert"),
            "body": str(alert.get("body") or ""),
            "deep_link": str(alert.get("deep_link") or "/"),
            "channel": "computed",
            "is_read": 0,
            "created_at": str(alert.get("created_at") or ""),
        })
    merged.extend(db_items)
    return merged[:limit]


def render_notifications_fragment_response(items: list[dict[str, Any]]) -> Response:
    """Renders the SSR HTML fragment for `#hvl-notifications-drawer-body` with count header."""
    resp = make_response(str(render_notifications_drawer_items(items)), 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["X-Notification-Count"] = str(len(items))
    return resp


def _normalize_ctx(get_context_fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    raw = get_context_fn() or {}
    hid = int(raw.get("household_id") or raw.get("family_id") or 0)
    return {
        "household_id": hid,
        "email": str(raw.get("email") or "").strip().lower(),
        "role": str(raw.get("role") or "member").strip().lower(),
        "is_demo": bool(raw.get("is_demo")),
        "is_authenticated": bool(raw.get("is_authenticated", hid > 0)),
        "db_path": raw.get("db_path"),
    }


def _check_mutation_guard(ctx: dict[str, Any]) -> tuple[Response, int] | None:
    if not ctx["is_authenticated"] or ctx["household_id"] <= 0:
        return jsonify({"success": False, "error": "Authentication required."}), 401
    if ctx["is_demo"] or ctx["role"] == "viewer":
        return (
            jsonify({"success": False, "error": "Read-only session cannot modify notifications."}),
            403,
        )
    return None


def _record_tombstone(
    session_scope_fn: Any,
    ctx: dict[str, Any],
    dedupe_key: str,
    notif_model: Any,
    record_tombstone_fn: Callable[[dict[str, Any], str], Any] | None = None,
) -> None:
    if not dedupe_key:
        return
    if record_tombstone_fn is not None:
        record_tombstone_fn(ctx, dedupe_key)
        return
    if session_scope_fn is None:
        return
    create_or_update_notification(
        session_scope_fn,
        household_id=ctx["household_id"],
        recipient_email=ctx["email"] or "*",
        category="system",
        dedupe_key=dedupe_key,
        title="Dismissed Alert",
        body="",
        is_read=1,
        db_path=ctx["db_path"],
        notif_model=notif_model,
    )


def create_notifications_blueprint(
    get_context_fn: Callable[[], dict[str, Any]],
    session_scope_fn: Any = None,
    *,
    notif_model: Any = None,
    push_model: Any = None,
    bump_domains_fn: Callable[[int, str], Any] | None = None,
    bump_signal_fn: Callable[..., Any] | None = None,
    computed_alerts_fn: Callable[[int, str, Any], list[dict[str, Any]]] | None = None,
    get_subscriptions_fn: Callable[..., list[dict[str, Any]]] | None = None,
    create_notification_fn: Callable[..., Any] | None = None,
    save_subscription_fn: Callable[..., dict[str, Any]] | None = None,
    delete_subscription_fn: Callable[..., bool] | None = None,
    list_notifications_fn: Callable[..., list[dict[str, Any]]] | None = None,
    mark_read_fn: Callable[..., int] | None = None,
    clear_notifications_fn: Callable[..., int] | None = None,
    record_tombstone_fn: Callable[[dict[str, Any], str], Any] | None = None,
    app_name: str = "HVL",
    blueprint_name: str = "hvl_notifications",
    url_prefix: str = "/api/notifications",
) -> Blueprint:
    """Creates a shared Flask Blueprint for notification bell, drawer fragments, and Web Push."""
    bp = Blueprint(blueprint_name, __name__, url_prefix=url_prefix)

    def _bump(hid: int) -> None:
        for fn in (bump_domains_fn, bump_signal_fn):
            if fn is not None and hid > 0:
                try:
                    fn(hid, "notifications")
                except TypeError:
                    fn("notifications")
                except Exception as exc:
                    logger.debug("bump signal failed: %s", exc)

    def _merged_for_ctx(ctx: dict[str, Any]) -> list[dict[str, Any]]:
        return get_merged_notifications(
            session_scope_fn,
            household_id=ctx["household_id"],
            email=ctx["email"],
            db_path=ctx["db_path"],
            notif_model=notif_model,
            computed_alerts_fn=computed_alerts_fn,
            list_notifications_fn=list_notifications_fn,
        )

    @bp.route("/unread", methods=["GET"])
    def get_unread():
        ctx = _normalize_ctx(get_context_fn)
        if not ctx["is_authenticated"] or ctx["household_id"] <= 0:
            return jsonify({"success": False, "error": "Authentication required."}), 401
        items = _merged_for_ctx(ctx)
        return jsonify({"success": True, "unread_count": len(items), "notifications": items})

    @bp.route("/fragment", methods=["GET"])
    def get_fragment():
        ctx = _normalize_ctx(get_context_fn)
        if not ctx["is_authenticated"] or ctx["household_id"] <= 0:
            return jsonify({"success": False, "error": "Authentication required."}), 401
        return render_notifications_fragment_response(_merged_for_ctx(ctx))

    @bp.route("/mark-read", methods=["POST"])
    def post_mark_read():
        ctx = _normalize_ctx(get_context_fn)
        guard = _check_mutation_guard(ctx)
        if guard is not None:
            return guard
        data = request.get_json(silent=True) or {}
        raw_ids = data.get("ids")
        single_id = data.get("id")
        dkey = str(data.get("dedupe_key") or "").strip()
        mark_all = bool(data.get("all")) or (raw_ids is None and not single_id and not dkey)

        id_list: list[int] | None = None
        if isinstance(raw_ids, list):
            id_list = [int(x) for x in raw_ids if str(x).isdigit()]
        elif single_id is not None and str(single_id).isdigit():
            id_list = [int(single_id)]

        if mark_read_fn is not None:
            updated = int(mark_read_fn(ctx, notification_ids=None if mark_all else id_list, dedupe_keys=None if mark_all else ([dkey] if dkey else None), mark_all=mark_all) or 0)
        elif session_scope_fn is not None:
            updated = mark_notifications_read(
                session_scope_fn,
                household_id=ctx["household_id"],
                recipient_email=ctx["email"],
                notification_ids=None if mark_all else id_list,
                dedupe_keys=None if mark_all else ([dkey] if dkey else None),
                db_path=ctx["db_path"],
                notif_model=notif_model,
            )
        else:
            updated = 0
        if dkey and updated == 0:
            _record_tombstone(session_scope_fn, ctx, dkey, notif_model, record_tombstone_fn)
            updated = 1
        elif mark_all and computed_alerts_fn is not None:
            for item in _merged_for_ctx(ctx):
                if item.get("channel") == "computed" and item.get("dedupe_key"):
                    _record_tombstone(session_scope_fn, ctx, str(item["dedupe_key"]), notif_model, record_tombstone_fn)
                    updated += 1
        _bump(ctx["household_id"])
        return jsonify({"success": True, "marked_read": updated})

    @bp.route("/clear", methods=["POST"])
    def post_clear():
        ctx = _normalize_ctx(get_context_fn)
        guard = _check_mutation_guard(ctx)
        if guard is not None:
            return guard
        data = request.get_json(silent=True) or {}
        clear_computed = bool(data.get("clear_computed", True))
        if clear_notifications_fn is not None:
            cleared = int(clear_notifications_fn(ctx) or 0)
        elif session_scope_fn is not None:
            cleared = clear_all_notifications(
                session_scope_fn,
                household_id=ctx["household_id"],
                recipient_email=ctx["email"],
                db_path=ctx["db_path"],
                notif_model=notif_model,
            )
        else:
            cleared = 0
        if clear_computed and computed_alerts_fn is not None:
            try:
                raw_comp = computed_alerts_fn(ctx["household_id"], ctx["email"], ctx["db_path"]) or []
            except Exception:
                raw_comp = []
            for comp in raw_comp:
                if isinstance(comp, dict) and comp.get("dedupe_key"):
                    _record_tombstone(session_scope_fn, ctx, str(comp["dedupe_key"]), notif_model, record_tombstone_fn)
                    cleared += 1
        _bump(ctx["household_id"])
        return jsonify({"success": True, "cleared": cleared})

    register_push_routes(
        bp,
        get_context_fn=get_context_fn,
        normalize_ctx_fn=_normalize_ctx,
        check_mutation_guard_fn=_check_mutation_guard,
        session_scope_fn=session_scope_fn,
        notif_model=notif_model,
        push_model=push_model,
        get_subscriptions_fn=get_subscriptions_fn,
        create_notification_fn=create_notification_fn,
        save_subscription_fn=save_subscription_fn,
        delete_subscription_fn=delete_subscription_fn,
        bump_fn=_bump,
        app_name=app_name,
    )
    return bp


__all__ = [
    "create_notifications_blueprint",
    "dispatch_web_push",
    "get_merged_notifications",
    "notify_and_push_member",
    "render_notifications_fragment_response",
]
