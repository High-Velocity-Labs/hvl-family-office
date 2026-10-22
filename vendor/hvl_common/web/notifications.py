"""
Shared Layer 2 & 3 Notification Blueprint Factory & W3C Web Push Dispatcher
(`hvl_common.web.notifications`).

Provides `dispatch_web_push`, `get_merged_notifications`, `render_notifications_fragment_response`,
and `create_notifications_blueprint` with strict demo/viewer read-only guardrails (`401`/`403`)
and declarative `notifications` domain-version bumping.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from flask import Blueprint, Response, jsonify, make_response, request

from hvl_common.db.notifications import (
    clear_all_notifications,
    create_or_update_notification,
    delete_push_subscription,
    list_active_notifications,
    list_read_dedupe_keys,
    mark_notifications_read,
    save_push_subscription,
)
from hvl_common.ui.notifications import render_notifications_drawer_items

logger = logging.getLogger(__name__)


def dispatch_web_push(
    subscription: dict[str, Any],
    title: str,
    body: str,
    deep_link: str = "/",
) -> bool:
    """Attempts delivery of a W3C Web Push payload if `pywebpush` and `VAPID_PRIVATE_KEY` exist."""
    vapid_key = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    if not vapid_key:
        return False
    try:
        import pywebpush  # type: ignore
    except ImportError:
        return False

    sub_info = {
        "endpoint": subscription.get("endpoint", ""),
        "keys": {
            "p256dh": subscription.get("p256dh", ""),
            "auth": subscription.get("auth", ""),
        },
    }
    payload = json.dumps({"title": title, "body": body, "deep_link": deep_link, "url": deep_link})
    claims = {"sub": os.getenv("VAPID_SUBJECT", "mailto:notifications@highvelocitylabs.dev")}
    try:
        pywebpush.webpush(
            subscription_info=sub_info,
            data=payload,
            vapid_private_key=vapid_key,
            vapid_claims=claims,
        )
        return True
    except Exception as exc:
        logger.warning("Web push dispatch failed for %s: %s", subscription.get("endpoint"), exc)
        return False


def get_merged_notifications(
    session_scope_fn: Any,
    *,
    household_id: int = 0,
    email: str = "",
    db_path: Any = None,
    notif_model: Any = None,
    computed_alerts_fn: Callable[[int, str, Any], list[dict[str, Any]]] | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Combines unread DB notifications with live computed alerts, deduplicating by `dedupe_key`."""
    hid = int(household_id or 0)
    if hid <= 0:
        return []
    clean_email = (email or "").strip().lower()
    db_items = list_active_notifications(
        session_scope_fn,
        household_id=hid,
        recipient_email=clean_email,
        include_read=False,
        limit=limit,
        db_path=db_path,
        notif_model=notif_model,
    )
    if computed_alerts_fn is None:
        return db_items[:limit]

    seen_dedupe = {str(it.get("dedupe_key") or "") for it in db_items if it.get("dedupe_key")}
    read_dedupe = list_read_dedupe_keys(
        session_scope_fn,
        household_id=hid,
        recipient_email=clean_email,
        db_path=db_path,
        notif_model=notif_model,
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
) -> None:
    if not dedupe_key:
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
    session_scope_fn: Any,
    *,
    notif_model: Any = None,
    push_model: Any = None,
    bump_domains_fn: Callable[[int, str], Any] | None = None,
    computed_alerts_fn: Callable[[int, str, Any], list[dict[str, Any]]] | None = None,
    blueprint_name: str = "hvl_notifications",
    url_prefix: str = "/api/notifications",
) -> Blueprint:
    """Creates a shared Flask Blueprint for notification bell, drawer fragments, and Web Push."""
    bp = Blueprint(blueprint_name, __name__, url_prefix=url_prefix)

    def _bump(hid: int) -> None:
        if bump_domains_fn is not None and hid > 0:
            try:
                bump_domains_fn(hid, "notifications")
            except Exception as exc:
                logger.debug("bump_domains_fn failed: %s", exc)

    def _merged_for_ctx(ctx: dict[str, Any]) -> list[dict[str, Any]]:
        return get_merged_notifications(
            session_scope_fn,
            household_id=ctx["household_id"],
            email=ctx["email"],
            db_path=ctx["db_path"],
            notif_model=notif_model,
            computed_alerts_fn=computed_alerts_fn,
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

        updated = mark_notifications_read(
            session_scope_fn,
            household_id=ctx["household_id"],
            recipient_email=ctx["email"],
            notification_ids=None if mark_all else id_list,
            dedupe_keys=None if mark_all else ([dkey] if dkey else None),
            db_path=ctx["db_path"],
            notif_model=notif_model,
        )
        if dkey and updated == 0:
            _record_tombstone(session_scope_fn, ctx, dkey, notif_model)
            updated = 1
        elif mark_all and computed_alerts_fn is not None:
            for item in _merged_for_ctx(ctx):
                if item.get("channel") == "computed" and item.get("dedupe_key"):
                    _record_tombstone(session_scope_fn, ctx, str(item["dedupe_key"]), notif_model)
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
        cleared = clear_all_notifications(
            session_scope_fn,
            household_id=ctx["household_id"],
            recipient_email=ctx["email"],
            db_path=ctx["db_path"],
            notif_model=notif_model,
        )
        if clear_computed and computed_alerts_fn is not None:
            try:
                raw_comp = computed_alerts_fn(ctx["household_id"], ctx["email"], ctx["db_path"]) or []
            except Exception:
                raw_comp = []
            for comp in raw_comp:
                if isinstance(comp, dict) and comp.get("dedupe_key"):
                    _record_tombstone(session_scope_fn, ctx, str(comp["dedupe_key"]), notif_model)
                    cleared += 1
        _bump(ctx["household_id"])
        return jsonify({"success": True, "cleared": cleared})

    @bp.route("/subscribe", methods=["POST"])
    def post_subscribe():
        ctx = _normalize_ctx(get_context_fn)
        guard = _check_mutation_guard(ctx)
        if guard is not None:
            return guard
        data = request.get_json(silent=True) or {}
        keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
        endpoint = str(data.get("endpoint") or "").strip()
        if not endpoint:
            return jsonify({"success": False, "error": "Subscription endpoint is required."}), 400
        sub = save_push_subscription(
            session_scope_fn,
            household_id=ctx["household_id"],
            member_email=ctx["email"],
            endpoint=endpoint,
            p256dh=str(keys.get("p256dh") or data.get("p256dh") or ""),
            auth=str(keys.get("auth") or data.get("auth") or ""),
            device_label=str(data.get("device_label") or ""),
            db_path=ctx["db_path"],
            push_model=push_model,
        )
        return jsonify({"success": True, "subscription": sub})

    @bp.route("/unsubscribe", methods=["POST"])
    def post_unsubscribe():
        ctx = _normalize_ctx(get_context_fn)
        guard = _check_mutation_guard(ctx)
        if guard is not None:
            return guard
        data = request.get_json(silent=True) or {}
        endpoint = str(data.get("endpoint") or "").strip()
        if not endpoint:
            return jsonify({"success": False, "error": "Subscription endpoint is required."}), 400
        removed = delete_push_subscription(
            session_scope_fn,
            household_id=ctx["household_id"],
            member_email=ctx["email"],
            endpoint=endpoint,
            db_path=ctx["db_path"],
            push_model=push_model,
        )
        return jsonify({"success": True, "removed": removed})

    return bp


__all__ = [
    "dispatch_web_push",
    "get_merged_notifications",
    "render_notifications_fragment_response",
    "create_notifications_blueprint",
]
