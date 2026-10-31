"""
Shared W3C Web Push Subscription, Test-Push & Dispatch Helpers (`hvl_common.web.push_routes`).
"""

from __future__ import annotations

import inspect
import json
import logging
import os
from typing import Any, Callable

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from hvl_common.db.notifications import (
    PushSubscription,
    _ACTIVE_MODELS,
    _open_session,
    create_or_update_notification,
    delete_push_subscription,
    get_member_push_subscriptions,
    save_push_subscription,
)
from hvl_common.web.pwa import get_vapid_public_key

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


def _resolve_dispatcher(custom_fn: Callable[..., bool] | None = None) -> Callable[..., bool]:
    if custom_fn is not None:
        return custom_fn
    try:
        from hvl_common.web import notifications as notif_mod
        return getattr(notif_mod, "dispatch_web_push", dispatch_web_push)
    except Exception:
        return dispatch_web_push


def _invoke_get_subscriptions(
    get_subscriptions_fn: Callable[..., list[dict[str, Any]]] | None,
    session_scope_fn: Any,
    household_id: int,
    email: str,
    db_path: Any = None,
    push_model: Any = None,
) -> list[dict[str, Any]]:
    if get_subscriptions_fn is not None:
        try:
            params = list(inspect.signature(get_subscriptions_fn).parameters.values())
            if len(params) >= 3 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
                return list(get_subscriptions_fn(household_id, email, db_path) or [])
            if len(params) == 2:
                return list(get_subscriptions_fn(household_id, email) or [])
            if len(params) == 1:
                return list(get_subscriptions_fn(email) or [])
            return list(get_subscriptions_fn() or [])
        except TypeError:
            return list(get_subscriptions_fn(household_id, email) or [])
    if session_scope_fn is not None and household_id > 0:
        clean_email = (email or "").strip().lower()
        if clean_email and clean_email != "*":
            return get_member_push_subscriptions(
                session_scope_fn,
                household_id=household_id,
                member_email=clean_email,
                db_path=db_path,
                push_model=push_model,
            )
        model = push_model or _ACTIVE_MODELS.get("push") or PushSubscription
        with _open_session(session_scope_fn, db_path, household_id, invalidate_cache=False) as session:
            rows = session.scalars(
                select(model).where(model.household_id == household_id).order_by(model.id.desc())
            ).all()
            return [r.to_dict() for r in rows]
    return []


def _invoke_create_notification(
    create_notification_fn: Callable[..., Any] | None,
    session_scope_fn: Any,
    ctx: dict[str, Any],
    title: str,
    body: str,
    deep_link: str,
    notif_model: Any = None,
    app_name: str = "HVL",
) -> Any:
    if create_notification_fn is not None:
        try:
            return create_notification_fn(
                household_id=ctx["household_id"],
                recipient_email=ctx["email"] or "*",
                title=title,
                body=body,
                deep_link=deep_link,
                db_path=ctx.get("db_path"),
            )
        except TypeError:
            return create_notification_fn(ctx["household_id"], ctx["email"], title, body, deep_link)
    if session_scope_fn is not None:
        return create_or_update_notification(
            session_scope_fn,
            household_id=ctx["household_id"],
            recipient_email=ctx["email"] or "*",
            sender_email=ctx["email"],
            sender_name=app_name,
            category="system",
            title=title,
            body=body,
            deep_link=deep_link,
            db_path=ctx["db_path"],
            notif_model=notif_model,
        )
    return {"title": title, "body": body, "deep_link": deep_link}


def notify_and_push_member(
    session_scope_fn: Any = None,
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
    db_path: Any = None,
    notif_model: Any = None,
    push_model: Any = None,
    get_subscriptions_fn: Callable[..., list[dict[str, Any]]] | None = None,
    dispatch_push_fn: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    """Creates an in-app notification and dispatches W3C Web Push across member devices."""
    eff_id = int(household_id or family_id or 0)
    created: dict[str, Any] = {}
    if session_scope_fn is not None and eff_id > 0:
        created = create_or_update_notification(
            session_scope_fn, household_id=eff_id, recipient_email=recipient_email,
            sender_email=sender_email, sender_name=sender_name, category=category,
            dedupe_key=dedupe_key, conversation_id=conversation_id, title=title,
            body=body, deep_link=deep_link, channel=channel, db_path=db_path, notif_model=notif_model,
        )
    subs = _invoke_get_subscriptions(get_subscriptions_fn, session_scope_fn, eff_id, recipient_email, db_path, push_model)
    clean_sender = (sender_email or "").strip().lower()
    dispatcher = _resolve_dispatcher(dispatch_push_fn)
    pushed = sum(
        1 for sub in subs
        if not (recipient_email == "*" and category in ("collaboration", "invite") and clean_sender and str(sub.get("member_email") or "").strip().lower() == clean_sender)
        and dispatcher(sub, title=title, body=body, deep_link=deep_link)
    )
    out = dict(created) if created else {"title": title, "body": body, "deep_link": deep_link}
    out.update({"devices_registered": len(subs), "devices_notified": pushed})
    return out


def _execute_subscribe_action(ctx: dict[str, Any], cfg: dict[str, Any]):
    data = request.get_json(silent=True) or {}
    keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
    endpoint = str(data.get("endpoint") or "").strip()
    if not endpoint:
        return jsonify({"success": False, "error": "Subscription endpoint is required."}), 400
    p256dh = str(keys.get("p256dh") or data.get("p256dh") or "")
    auth = str(keys.get("auth") or data.get("auth") or "")
    label = str(data.get("device_label") or "")
    save_fn = cfg.get("save_subscription_fn")
    sub = (
        save_fn(ctx, endpoint=endpoint, p256dh=p256dh, auth=auth, device_label=label)
        if save_fn is not None
        else save_push_subscription(
            cfg.get("session_scope_fn"),
            household_id=ctx["household_id"],
            member_email=ctx["email"],
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            device_label=label,
            db_path=ctx["db_path"],
            push_model=cfg.get("push_model"),
        )
    )
    return jsonify({"success": True, "subscription": sub})


def _execute_unsubscribe_action(ctx: dict[str, Any], cfg: dict[str, Any]):
    data = request.get_json(silent=True) or {}
    endpoint = str(data.get("endpoint") or "").strip()
    if not endpoint:
        return jsonify({"success": False, "error": "Subscription endpoint is required."}), 400
    del_fn = cfg.get("delete_subscription_fn")
    removed = (
        bool(del_fn(ctx, endpoint=endpoint))
        if del_fn is not None
        else delete_push_subscription(
            cfg.get("session_scope_fn"),
            household_id=ctx["household_id"],
            member_email=ctx["email"],
            endpoint=endpoint,
            db_path=ctx["db_path"],
            push_model=cfg.get("push_model"),
        )
    )
    return jsonify({"success": True, "removed": removed})


def _execute_test_push_action(ctx: dict[str, Any], cfg: dict[str, Any]):
    data = request.get_json(silent=True) or {}
    app_name = str(cfg.get("app_name") or "HVL")
    title = str(data.get("title") or f"{app_name} Test Push").strip()
    body = str(data.get("body") or f"Push notifications are active for {ctx['email'] or 'your device'}.").strip()
    deep_link = str(data.get("deep_link") or "/").strip() or "/"
    created = _invoke_create_notification(
        cfg.get("create_notification_fn"),
        cfg.get("session_scope_fn"),
        ctx,
        title,
        body,
        deep_link,
        notif_model=cfg.get("notif_model"),
        app_name=app_name,
    )
    subs = _invoke_get_subscriptions(
        cfg.get("get_subscriptions_fn"),
        cfg.get("session_scope_fn"),
        ctx["household_id"],
        ctx["email"],
        ctx["db_path"],
        cfg.get("push_model"),
    )
    dispatcher = _resolve_dispatcher()
    pushed = sum(1 for sub in subs if dispatcher(sub, title=title, body=body, deep_link=deep_link))
    cfg["bump_fn"](ctx["household_id"])
    return jsonify({
        "success": True,
        "status": "ok",
        "devices_registered": len(subs),
        "devices_notified": pushed,
        "push_dispatched": pushed,
        "in_app_created": bool(created),
        "title": title,
        "body": body,
    })


def register_push_routes(bp: Blueprint, **cfg: Any) -> None:
    """Attaches `/vapid-public-key`, `/subscribe`, `/unsubscribe`, and `/test-push` onto `bp`."""
    get_ctx = cfg["get_context_fn"]
    norm_ctx = cfg["normalize_ctx_fn"]
    guard_fn = cfg["check_mutation_guard_fn"]

    def _guarded(handler: Callable[[dict[str, Any], dict[str, Any]], Any]):
        ctx = norm_ctx(get_ctx)
        guard = guard_fn(ctx)
        return guard if guard is not None else handler(ctx, cfg)

    bp.add_url_rule(
        "/vapid-public-key",
        endpoint="get_vapid_key",
        view_func=lambda: jsonify({"success": True, "public_key": get_vapid_public_key()}),
        methods=["GET"],
    )
    bp.add_url_rule(
        "/subscribe",
        endpoint="post_subscribe",
        view_func=lambda: _guarded(_execute_subscribe_action),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/unsubscribe",
        endpoint="post_unsubscribe",
        view_func=lambda: _guarded(_execute_unsubscribe_action),
        methods=["POST"],
    )
    bp.add_url_rule(
        "/test-push",
        endpoint="post_test_push",
        view_func=lambda: _guarded(_execute_test_push_action),
        methods=["POST"],
    )


__all__ = [
    "dispatch_web_push",
    "notify_and_push_member",
    "register_push_routes",
]
