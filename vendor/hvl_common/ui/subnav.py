"""
Canonical Scrollable Subnav Ribbon & Settings Header Primitives (hvl_common.ui.subnav).
Provides `hvl_subnav_bar`, `hvl_settings_subnav`, and `hvl_settings_header`.
"""

from __future__ import annotations

from typing import Any, Iterable
from markupsafe import Markup, escape
from hvl_common.ui.blueprint import render_icon

_PREV_ARROW_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">'
    '<polyline points="15 18 9 12 15 6"></polyline></svg>'
)
_NEXT_ARROW_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">'
    '<polyline points="9 18 15 12 9 6"></polyline></svg>'
)


def _normalize_subnav_item(item: tuple[Any, ...] | dict[str, Any]) -> dict[str, Any]:
    """Normalize a 2-tuple, 3-tuple, or dict into a canonical subnav item dictionary."""
    if isinstance(item, dict):
        return item
    if len(item) >= 3 and isinstance(item[2], dict):
        merged = dict(item[2])
        merged.setdefault("id", item[0])
        merged.setdefault("href", item[0])
        merged.setdefault("label", item[1])
        return merged
    return {"id": item[0], "href": item[0], "label": item[1]}


def hvl_subnav_bar(
    items: Iterable[tuple[Any, ...] | dict[str, Any]],
    *,
    mode: str = "tabs",
    active_tab: str = "",
    strip: bool = False,
    strip_class: str = "hvl-subnav-strip features-subnav-strip",
    container_id: str = "",
    container_class: str = "hvl-subnav-container",
    container_style: str | None = None,
    inner_id: str = "hvl-subnav-inner",
    inner_class: str = "hvl-subnav-inner",
    list_id: str = "",
    list_class: str = "hvl-subnav-links",
    item_class: str = "hvl-subnav-link",
    prev_btn_id: str = "btn-subnav-prev",
    next_btn_id: str = "btn-subnav-next",
) -> Markup:
    """Emit canonical horizontal scrollable subnav bar (`mode='tabs'` or `mode='links'`)."""
    is_links = (mode or "tabs").strip().lower() == "links"
    active_norm = (active_tab or "").strip()
    list_id_attr = f' id="{escape(list_id)}"' if list_id else ""

    if is_links:
        c_cls = f"{container_class} features-subnav-container".strip() if "features-subnav-container" not in container_class else container_class
        i_cls = f"{inner_class} features-subnav-inner".strip() if "features-subnav-inner" not in inner_class else inner_class
        l_cls = f"{list_class} features-nav-links".strip() if "features-nav-links" not in list_class else list_class
        li_parts: list[str] = []
        for raw_item in items:
            norm = _normalize_subnav_item(raw_item)
            href = str(norm.get("href") or norm.get("id") or "").strip()
            label = str(norm.get("label") or href).strip()
            extra_cls = str(norm.get("class") or "").strip()
            target = str(norm.get("target") or "").strip()
            a_cls = f"hvl-subnav-link features-nav-link {escape(extra_cls)}".strip()
            target_attr = f' target="{escape(target)}"' if target else ""
            li_parts.append(f'<li><a href="{escape(href)}" class="{a_cls}"{target_attr}>{escape(label)}</a></li>')
        list_html = f'<ul class="{escape(l_cls)}"{list_id_attr}>{"".join(li_parts)}</ul>'
        prev_aria, next_aria = "Scroll navigation left", "Scroll navigation right"
        c_style = container_style if container_style is not None else ""
    else:
        c_cls = container_class or "hvl-subnav-container"
        i_cls = inner_class or "hvl-subnav-inner"
        l_cls = list_class or "hvl-subnav-links"
        btn_cls_base = "hvl-subnav-link settings-tab-btn" if item_class == "hvl-subnav-link" else (item_class or "hvl-subnav-link settings-tab-btn")
        btn_parts: list[str] = []
        for raw_item in items:
            norm = _normalize_subnav_item(raw_item)
            tid = str(norm.get("id") or "").strip()
            label = str(norm.get("label") or tid).strip()
            aliases = set(norm.get("aliases") or [])
            is_active = bool(active_norm) and ((active_norm == tid) or (active_norm in aliases))
            act_cls = " active" if is_active else ""
            pressed = "true" if is_active else "false"
            btn_parts.append(
                f'<button type="button" id="tab-btn-{escape(tid)}" data-tab="{escape(tid)}" '
                f'class="{escape(btn_cls_base)}{act_cls}" aria-pressed="{pressed}">{escape(label)}</button>'
            )
        list_html = f'<div class="{escape(l_cls)}"{list_id_attr}>{"".join(btn_parts)}</div>'
        prev_aria, next_aria = "Scroll tabs left", "Scroll tabs right"
        c_style = "margin-top: 8px; padding: 0; max-width: none;" if container_style is None else container_style

    cid_attr = f' id="{escape(container_id)}"' if container_id else ""
    cstyle_attr = f' style="{escape(c_style)}"' if c_style else ""
    iid_attr = f' id="{escape(inner_id)}"' if inner_id else ""
    prev_id_attr = f' id="{escape(prev_btn_id)}"' if prev_btn_id else ""
    next_id_attr = f' id="{escape(next_btn_id)}"' if next_btn_id else ""

    container_html = (
        f'<div class="{escape(c_cls)}"{cid_attr}{cstyle_attr}>'
        f'<button type="button"{prev_id_attr} class="subnav-arrow-btn prev" aria-label="{prev_aria}" title="Scroll Left" style="display: none;">{_PREV_ARROW_SVG}</button>'
        f'<div class="{escape(i_cls)}"{iid_attr}>{list_html}</div>'
        f'<button type="button"{next_id_attr} class="subnav-arrow-btn next" aria-label="{next_aria}" title="Scroll Right" style="display: none;">{_NEXT_ARROW_SVG}</button>'
        "</div>"
    )
    if strip:
        return Markup(f'<div class="{escape(strip_class)}">{container_html}</div>')
    return Markup(container_html)


def hvl_settings_subnav(
    tabs: Iterable[tuple[str, str] | dict[str, Any]],
    active_tab: str = "members",
    *,
    container_id: str = "settings-subnav-container",
    inner_id: str = "settings-subnav-inner",
    prev_btn_id: str = "btn-settings-subnav-prev",
    next_btn_id: str = "btn-settings-subnav-next",
) -> Markup:
    """Emit canonical horizontal scrollable Settings tab bar (.hvl-subnav-container)."""
    return hvl_subnav_bar(
        tabs,
        mode="tabs",
        active_tab=active_tab or "members",
        container_id=container_id,
        inner_id=inner_id,
        prev_btn_id=prev_btn_id,
        next_btn_id=next_btn_id,
    )


def hvl_settings_header(
    title: str = "Household & Portal Settings",
    subtitle: str = "Manage household access, theme appearance, data connections, and security.",
    *,
    title_id: str = "",
    icon_name: str = "settings",
    actions_html: str = "",
    close_btn_id: str = "btn-close-settings-modal",
    close_action: str = "",
    close_onclick: str = "",
    header_style: str = "",
) -> Markup:
    """Emit canonical Settings modal/pane header with 36x36 brand icon box, actions, and close button."""
    icon_svg = render_icon(icon_name, width=20, height=20)
    close_html = ""
    if close_btn_id or close_action or close_onclick:
        cid_attr = f' id="{escape(close_btn_id)}"' if close_btn_id else ""
        act_attr = f' data-action="{escape(close_action)}"' if close_action else ""
        onc_attr = f' onclick="{escape(close_onclick)}"' if close_onclick else ""
        close_svg = render_icon("close", width=18, height=18)
        close_html = (
            f'<button type="button"{cid_attr} class="custom-modal-close-btn modal-close-btn"'
            f'{act_attr}{onc_attr} title="Close Settings (Esc)" aria-label="Close Settings">{close_svg}</button>'
        )
    tid_attr = f' id="{escape(title_id)}"' if title_id else ""
    style_attr = f' style="{escape(header_style)}"' if header_style else ""
    return Markup(
        f'<div class="hvl-settings-header"{style_attr}>'
        '<div class="hvl-settings-header-title-group">'
        f'<div class="hvl-settings-icon-box">{icon_svg}</div>'
        '<div style="min-width: 0;">'
        f'<h2{tid_attr} style="font-size: 1.125rem; font-weight: 700; margin: 0;">{escape(title)}</h2>'
        f'<p class="text-muted" style="font-size: 0.75rem; margin: 2px 0 0 0;">{escape(subtitle)}</p>'
        "</div></div>"
        f'<div class="hvl-card-actions">{actions_html}{close_html}</div></div>'
    )


__all__ = ["hvl_settings_header", "hvl_settings_subnav", "hvl_subnav_bar"]
