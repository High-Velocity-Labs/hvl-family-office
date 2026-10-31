"""
Canonical Layer 0 Card Header, Icon Action Button & Subcard Primitives (hvl_common.ui.cards).
Provides reusable SSR Jinja globals (`hvl_icon_btn`, `hvl_card_header`, `hvl_subcard`)
paired with `/common/components.css` rules across all High Velocity Labs applications.
"""

from __future__ import annotations

from typing import Any, Iterable
from markupsafe import Markup, escape


def _resolve_asset_version(kwargs: dict[str, Any]) -> str:
    ver = kwargs.pop("version", None) or kwargs.pop("v", None)
    if ver:
        return str(ver)
    try:
        from flask import current_app, g

        return str(
            getattr(g, "asset_version", None)
            or current_app.config.get("ASSET_VERSION")
            or current_app.config.get("APP_VERSION")
            or ""
        )
    except Exception:
        return ""


def _format_html_attrs(attrs: dict[str, Any] | None, kwargs: dict[str, Any]) -> str:
    merged: dict[str, Any] = {**(attrs or {}), **kwargs}
    parts: list[str] = []
    for raw_key, val in merged.items():
        if val is None or val is False:
            continue
        key = str(raw_key).rstrip("_").replace("_", "-")
        parts.append(f" {escape(key)}" if val is True else f' {escape(key)}="{escape(str(val))}"')
    return "".join(parts)


def _preserve_or_escape(val: str | Markup) -> str:
    return str(val) if isinstance(val, Markup) else str(escape(val or ""))


def hvl_icon_btn(
    icon_name: str,
    label: str = "",
    *,
    title: str = "",
    aria_label: str = "",
    btn_id: str = "",
    css_class: str = "",
    variant: str = "secondary",
    href: str | None = None,
    btn_type: str = "button",
    icon_width: int = 15,
    icon_height: int = 15,
    badge: str | None = None,
    badge_class: str = "badge badge-blue",
    attrs: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Markup:
    """Render a standardized 32x32px `.btn .btn-secondary .btn-sm .btn-icon` button with SVG `<use>` and hidden label `<span>`."""
    icon_id = str(icon_name or "").strip().lstrip("#")
    if icon_id and not icon_id.startswith("icon-"):
        icon_id = f"icon-{icon_id}"

    ver = _resolve_asset_version(kwargs)
    q = f"?v={escape(ver)}" if ver else ""

    cls_tokens = css_class.split() if css_class else []
    has_variant = any(t in ("btn-primary", "btn-secondary", "btn-danger", "btn-ghost") for t in cls_tokens)
    base_classes = ["btn"]
    if not has_variant:
        base_classes.append(f"btn-{variant}" if variant else "btn-secondary")
    for req_cls in ("btn-sm", "btn-icon"):
        if req_cls not in cls_tokens:
            base_classes.append(req_cls)
    full_class = " ".join([*base_classes, *cls_tokens])

    resolved_title = title or label
    resolved_aria = aria_label or resolved_title
    resolved_span = label or title

    id_attr = f' id="{escape(btn_id)}"' if btn_id else ""
    title_attr = f' title="{escape(resolved_title)}"' if resolved_title else ""
    aria_attr = f' aria-label="{escape(resolved_aria)}"' if resolved_aria else ""
    extra_attrs = _format_html_attrs(attrs, kwargs)

    svg_html = (
        f'<svg class="hvl-icon" width="{int(icon_width)}" height="{int(icon_height)}" aria-hidden="true">'
        f'<use href="/common/icons.svg{q}#{escape(icon_id)}"></use></svg>'
    )
    span_html = f"<span>{escape(resolved_span)}</span>" if resolved_span else ""
    badge_html = (
        f'<span class="{escape(badge_class)}">{escape(str(badge))}</span>'
        if badge is not None and str(badge) != ""
        else ""
    )

    if href is not None:
        return Markup(
            f'<a href="{escape(href)}"{id_attr} class="{escape(full_class)}"'
            f"{title_attr}{aria_attr}{extra_attrs}>{svg_html}{span_html}{badge_html}</a>"
        )
    return Markup(
        f'<button type="{escape(btn_type)}"{id_attr} class="{escape(full_class)}"'
        f"{title_attr}{aria_attr}{extra_attrs}>{svg_html}{span_html}{badge_html}</button>"
    )


def hvl_card_header(
    title: str | Markup,
    subtitle: str | Markup = "",
    *,
    heading_tag: str = "h2",
    title_id: str = "",
    subtitle_id: str = "",
    css_class: str = "",
    row_class: str = "",
    actions_html: str | Markup = "",
    actions: Iterable[str | Markup] | None = None,
    badge_html: str | Markup = "",
    eyebrow: str = "",
    icon_name: str = "",
    guide_section: str = "",
    guide_title: str = "How It Works",
    bug_pane: str = "",
    show_bug_btn: bool = False,
    bug_title: str = "Report an issue or calculation discrepancy on this pane",
    attrs: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Markup:
    """Render a canonical `.hvl-card-header .card-header-clean` structure (`Title + Subtitle` on left, `.hvl-card-actions` slot on right)."""
    tag = heading_tag if heading_tag in ("h1", "h2", "h3", "h4") else "h2"
    ver = _resolve_asset_version(kwargs)
    q = f"?v={escape(ver)}" if ver else ""

    header_cls = f"hvl-card-header card-header-clean {css_class}".strip()
    row_cls = f"hvl-card-header-row {row_class}".strip()
    extra_attrs = _format_html_attrs(attrs, kwargs)

    eyebrow_part = f'<span class="micro-label">{escape(eyebrow)}</span>' if eyebrow else ""
    icon_part = ""
    if icon_name:
        iid = str(icon_name).strip().lstrip("#")
        if not iid.startswith("icon-"):
            iid = f"icon-{iid}"
        icon_part = f'<svg class="hvl-icon" width="18" height="18" aria-hidden="true"><use href="/common/icons.svg{q}#{escape(iid)}"></use></svg>'

    title_id_attr = f' id="{escape(title_id)}"' if title_id else ""
    title_inner = _preserve_or_escape(title)
    badge_part = _preserve_or_escape(badge_html) if badge_html else ""
    heading_part = (
        f'<div class="hvl-card-title-row">{icon_part}<{tag}{title_id_attr}>{title_inner}</{tag}>{badge_part}</div>'
        if (badge_part or icon_part)
        else f"<{tag}{title_id_attr}>{title_inner}</{tag}>"
    )
    sub_id_attr = f' id="{escape(subtitle_id)}"' if subtitle_id else ""
    subtitle_part = (
        f'<p{sub_id_attr} class="text-muted hvl-card-subtitle">{_preserve_or_escape(subtitle)}</p>'
        if subtitle
        else ""
    )

    action_parts: list[str] = [str(actions_html)] if actions_html else []
    if actions:
        action_parts.extend(str(item) for item in actions if item)
    if guide_section:
        action_parts.append(
            str(hvl_icon_btn("shared-help", "How It Works", title=guide_title, css_class="btn-guide-trigger", data_section=guide_section, version=ver))
        )
    if bug_pane and show_bug_btn:
        action_parts.append(
            str(hvl_icon_btn("shared-bug", "Report Issue", title=bug_title, css_class="btn-bug-report-trigger", data_pane=bug_pane, version=ver))
        )

    return Markup(
        f'<div class="{escape(header_cls)}"{extra_attrs}>'
        f'<div class="{escape(row_cls)}">'
        f'<div class="hvl-card-title-group">{eyebrow_part}{heading_part}{subtitle_part}</div>'
        f'<div class="hvl-card-actions">{"".join(action_parts)}</div>'
        "</div></div>"
    )


def hvl_subcard(
    body_html: str | Markup = "",
    *,
    title: str = "",
    micro_label: str = "",
    badge_html: str | Markup = "",
    variant: str = "",
    card_id: str = "",
    css_class: str = "",
    attrs: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Markup:
    """Render a canonical `.hvl-subcard` / `.hvl-callout` inset surface."""
    classes = ["hvl-subcard"]
    if variant:
        classes.append(f"hvl-callout-{variant}" if not variant.startswith("hvl-") else variant)
    if css_class:
        classes.append(css_class)
    id_attr = f' id="{escape(card_id)}"' if card_id else ""
    extra_attrs = _format_html_attrs(attrs, kwargs)

    top_html = ""
    if micro_label or title or badge_html:
        left = f'<span class="micro-label" style="margin-bottom:0;">{escape(micro_label)}</span>' if micro_label else f'<strong class="hvl-subcard-title">{escape(title)}</strong>'
        right = _preserve_or_escape(badge_html) if badge_html else ""
        top_html = f'<div class="hvl-subcard-header">{left}{right}</div>'

    return Markup(f'<div{id_attr} class="{escape(" ".join(classes))}"{extra_attrs}>{top_html}{_preserve_or_escape(body_html)}</div>')


__all__ = ["hvl_card_header", "hvl_icon_btn", "hvl_subcard"]
