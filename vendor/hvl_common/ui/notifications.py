"""
Shared Layer 3 Notification Bell & Slide-Over Drawer SSR Helpers (`hvl_common.ui.notifications`).
Renders the topbar notification bell button, unread count badge, slide-over drawer shell,
and Idiomorph-compatible notification item cards.
"""

from __future__ import annotations

from typing import Any, Iterable
from markupsafe import Markup, escape

CATEGORY_ICON_MAP: dict[str, str] = {
    "async_job": "icon-check",
    "sync_health": "icon-shared-sync",
    "security": "icon-shield",
    "invite": "icon-shared-user",
    "collaboration": "icon-sparkles",
    "general": "icon-bell",
}


def _resolve_category_icon(category: str) -> str:
    norm = (category or "general").strip().lower()
    return CATEGORY_ICON_MAP.get(norm, "icon-bell")


def hvl_notification_bell(
    unread_count: int = 0,
    btn_id: str = "btn-notification-bell",
    css_class: str = "",
) -> Markup:
    """Renders the canonical topbar notification bell button with unread badge."""
    cnt = max(0, int(unread_count or 0))
    cnt_text = "9+" if cnt > 9 else str(cnt)
    hidden_attr = " hidden" if cnt <= 0 else ""
    cls_str = f"hvl-notif-bell-btn {css_class}".strip()
    return Markup(
        f'<button type="button" id="{escape(btn_id)}" class="{escape(cls_str)}" '
        'data-action="toggle-notifications-drawer" aria-label="Notifications" title="Notifications">'
        '<svg class="hvl-icon" width="16" height="16" aria-hidden="true">'
        '<use href="/common/icons.svg#icon-bell"></use>'
        "</svg>"
        f'<span id="hvl-notification-badge" class="hvl-notif-badge" '
        f'data-unread-count="{cnt}"{hidden_attr}>{cnt_text}</span>'
        "</button>"
    )


def render_notifications_drawer_items(
    notifications: Iterable[dict[str, Any]] = (),
) -> Markup:
    """Renders the morphable inner body `#hvl-notifications-drawer-body` of the notifications drawer."""
    items = list(notifications or ())
    cnt = len(items)
    if not items:
        return Markup(
            '<div id="hvl-notifications-drawer-body" class="hvl-notif-drawer-body" '
            'data-fragment="notifications" data-depends="notifications" data-unread-count="0">'
            '<div class="hvl-notif-empty">'
            '<div class="hvl-notif-empty-icon">'
            '<svg class="hvl-icon" width="24" height="24" aria-hidden="true">'
            '<use href="/common/icons.svg#icon-bell"></use>'
            "</svg>"
            "</div>"
            '<p class="hvl-notif-empty-title">You\'re all caught up</p>'
            '<p class="hvl-notif-empty-sub">'
            "Actionable alerts for background jobs, sync health, security, and household updates will appear here."
            "</p>"
            "</div>"
            "</div>"
        )

    cards: list[str] = []
    for item in items:
        raw_id = item.get("id", "")
        dedupe_key = str(item.get("dedupe_key") or "")
        category = str(item.get("category") or "general").lower()
        icon_id = _resolve_category_icon(category)
        title = str(item.get("title") or "Notification")
        body = str(item.get("body") or "")
        deep_link = str(item.get("deep_link") or "/")
        created_at = str(item.get("created_at") or "")
        is_read = bool(int(item.get("is_read") or 0))
        read_cls = " is-read" if is_read else ""
        dot_html = (
            ""
            if is_read
            else '<span class="hvl-notif-dot" aria-hidden="true"></span>'
        )
        cards.append(
            f'<a href="{escape(deep_link)}" class="hvl-notif-item{read_cls}" '
            f'data-notif-item="true" data-notif-id="{escape(str(raw_id))}" '
            f'data-dedupe-key="{escape(dedupe_key)}" data-deep-link="{escape(deep_link)}" '
            f'data-category="{escape(category)}">'
            f'<div class="hvl-notif-icon-wrap hvl-notif-cat-{escape(category)}">'
            '<svg class="hvl-icon" width="16" height="16" aria-hidden="true">'
            f'<use href="/common/icons.svg#{escape(icon_id)}"></use>'
            "</svg>"
            "</div>"
            '<div class="hvl-notif-content">'
            '<div class="hvl-notif-title-row">'
            f'<span class="hvl-notif-title">{escape(title)}</span>'
            f'<time class="hvl-notif-time" data-timestamp="{escape(created_at)}"></time>'
            "</div>"
            f'<p class="hvl-notif-body">{escape(body)}</p>'
            "</div>"
            f"{dot_html}"
            "</a>"
        )

    return Markup(
        f'<div id="hvl-notifications-drawer-body" class="hvl-notif-drawer-body" '
        f'data-fragment="notifications" data-depends="notifications" data-unread-count="{cnt}">'
        f'{"".join(cards)}'
        "</div>"
    )


def hvl_notification_drawer(
    notifications: Iterable[dict[str, Any]] = (),
    unread_count: int = 0,
) -> Markup:
    """Renders the shared notification drawer backdrop and `<aside id=\"hvl-notifications-drawer\">`."""
    items = list(notifications or ())
    body_html = render_notifications_drawer_items(items)
    return Markup(
        '<div id="hvl-notifications-backdrop" class="hvl-notif-backdrop" hidden></div>'
        '<aside id="hvl-notifications-drawer" class="hvl-notif-drawer" '
        'aria-label="Notifications" aria-hidden="true">'
        '<div class="hvl-notif-drawer-header">'
        '<div class="hvl-notif-drawer-title-group">'
        '<svg class="hvl-icon" width="16" height="16" aria-hidden="true">'
        '<use href="/common/icons.svg#icon-bell"></use>'
        "</svg>"
        '<h2 class="hvl-notif-drawer-title">Notifications</h2>'
        "</div>"
        '<div class="hvl-notif-drawer-actions">'
        '<button type="button" id="btn-notif-mark-all-read" class="hvl-notif-action-link">'
        "Mark all read"
        "</button>"
        '<button type="button" id="btn-notif-drawer-close" class="hvl-notif-close-btn" '
        'aria-label="Close Notifications" title="Close">'
        '<svg class="hvl-icon" width="16" height="16" aria-hidden="true">'
        '<use href="/common/icons.svg#icon-close"></use>'
        "</svg>"
        "</button>"
        "</div>"
        "</div>"
        f"{body_html}"
        '<div class="hvl-notif-drawer-footer">'
        '<button type="button" id="btn-notif-clear-all" class="btn btn-secondary btn-sm btn-full">'
        "Clear all"
        "</button>"
        "</div>"
        "</aside>"
    )


__all__ = [
    "CATEGORY_ICON_MAP",
    "hvl_notification_bell",
    "render_notifications_drawer_items",
    "hvl_notification_drawer",
]
