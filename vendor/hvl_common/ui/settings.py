"""
Shared Tabbed Settings Subnav & Common Settings Cards (hvl_common.ui.settings).
Provides reusable Jinja helpers for tabbed settings navigation, Appearance & Theme panes,
Household Name cards, Developer & Admin Support Access cards, and BYO vs. Shared AI Quota cards.
"""

from __future__ import annotations

from typing import Any, Iterable
from markupsafe import Markup, escape
from hvl_common.ui.blueprint import render_icon
from hvl_common.ui.settings_integrations import (
    hvl_push_notifications_card,
    hvl_siri_shortcuts_card,
)


def hvl_user_badge(
    user_name: str = "",
    user_role: str = "",
    logout_url: str | None = "/logout",
    logout_title: str = "Sign Out",
    avatar_text: str = "",
    card_id: str = "sidebar-user-card",
) -> Markup:
    """Emit canonical combined user profile badge with sign-out action for sidebars."""
    name_clean = (user_name or "Member").strip()
    initial = (avatar_text or (name_clean[0] if name_clean else "M")).upper()
    role_html = f'<span class="user-role">{escape(user_role)}</span>' if user_role else ""
    tooltip_text = f"Signed in as {escape(name_clean)}"
    if user_role:
        tooltip_text += f" ({escape(user_role)})"
    logout_icon = render_icon("logout", width=15, height=15)
    if logout_url:
        action_html = (
            f'<a href="{escape(logout_url)}" id="btn-logout" class="btn-logout-icon" '
            f'title="{escape(logout_title)}" aria-label="{escape(logout_title)}" data-tooltip="{escape(logout_title)}">'
            f"{logout_icon}"
            "</a>"
        )
    else:
        action_html = (
            f'<button type="button" id="btn-logout" class="btn-logout-icon" '
            f'title="{escape(logout_title)}" aria-label="{escape(logout_title)}" data-tooltip="{escape(logout_title)}">'
            f"{logout_icon}"
            "</button>"
        )
    return Markup(
        f'<div class="user-badge" id="{escape(card_id)}" data-tooltip="{tooltip_text}">'
        f'<div class="user-avatar-pill">{escape(initial)}</div>'
        f'<div class="user-info-col">'
        f'<span class="user-name">{escape(name_clean)}</span>'
        f"{role_html}"
        "</div>"
        f"{action_html}"
        "</div>"
    )


def hvl_theme_choice_cards(radio_name: str = "settings-theme") -> Markup:
    """Emit canonical 3-card Appearance & Theme selector (Light, Dark, System Default)."""
    sun_svg = render_icon("theme", width=18, height=18)
    return Markup(
        '<div class="theme-choice-grid">'
        '<div class="theme-choice-card" data-theme-value="light">'
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">'
        f'<div style="display:flex;align-items:center;gap:8px;">{sun_svg}<strong style="font-size:0.875rem;">Light Mode</strong></div>'
        f'<input type="radio" name="{radio_name}" value="light" aria-label="Light Mode" style="cursor:pointer;"></div>'
        '<p class="text-muted" style="font-size:0.75rem;margin:0;line-height:1.45;">Crisp paper-white canvas with clean slate typography and high-contrast surfaces.</p>'
        "</div>"
        '<div class="theme-choice-card" data-theme-value="dark">'
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">'
        '<div style="display:flex;align-items:center;gap:8px;">'
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>'
        '<strong style="font-size:0.875rem;">Dark Mode</strong></div>'
        f'<input type="radio" name="{radio_name}" value="dark" aria-label="Dark Mode" style="cursor:pointer;"></div>'
        '<p class="text-muted" style="font-size:0.75rem;margin:0;line-height:1.45;">Deep charcoal &amp; slate palette for reduced eye strain and night-time comfort.</p>'
        "</div>"
        '<div class="theme-choice-card" data-theme-value="system">'
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">'
        '<div style="display:flex;align-items:center;gap:8px;">'
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>'
        '<strong style="font-size:0.875rem;">System Default</strong></div>'
        f'<input type="radio" name="{radio_name}" value="system" aria-label="System Default" style="cursor:pointer;"></div>'
        '<p class="text-muted" style="font-size:0.75rem;margin:0;line-height:1.45;">Automatically aligns with your operating system or phone light/dark schedule.</p>'
        "</div></div>"
    )


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
    active_norm = (active_tab or "members").strip()
    btn_parts: list[str] = []
    for item in tabs:
        if isinstance(item, dict):
            tid = str(item.get("id", "")).strip()
            label = str(item.get("label", tid)).strip()
            aliases = set(item.get("aliases") or [])
        else:
            tid, label = str(item[0]).strip(), str(item[1]).strip()
            aliases = set()
        is_active = (active_norm == tid) or (active_norm in aliases)
        act_cls = " active" if is_active else ""
        pressed = "true" if is_active else "false"
        btn_parts.append(
            f'<button type="button" id="tab-btn-{escape(tid)}" data-tab="{escape(tid)}" '
            f'class="hvl-subnav-link settings-tab-btn{act_cls}" aria-pressed="{pressed}">'
            f"{escape(label)}</button>"
        )

    return Markup(
        f'<div class="hvl-subnav-container" id="{escape(container_id)}" style="margin-top: 8px; padding: 0; max-width: none;">'
        f'<button type="button" id="{escape(prev_btn_id)}" class="subnav-arrow-btn prev" aria-label="Scroll tabs left" title="Scroll Left" style="display: none;">'
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"></polyline></svg>'
        "</button>"
        f'<div class="hvl-subnav-inner" id="{escape(inner_id)}">'
        f'<div class="hvl-subnav-links">{"".join(btn_parts)}</div>'
        "</div>"
        f'<button type="button" id="{escape(next_btn_id)}" class="subnav-arrow-btn next" aria-label="Scroll tabs right" title="Scroll Right" style="display: none;">'
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>'
        "</button></div>"
    )


def hvl_settings_appearance_pane(
    active_tab: str = "members",
    *,
    app_label: str = "HVL Portal",
    radio_name: str = "settings-theme",
    footer_html: str = "",
    aliases: Iterable[str] = (),
    show_cache_diagnostics: bool = True,
) -> Markup:
    """Emit canonical Appearance & Theme settings tab pane (#settings-tab-appearance)."""
    match_tabs = {"appearance", *aliases}
    vis = "block" if (active_tab or "") in match_tabs else "none"
    cards = hvl_theme_choice_cards(radio_name=radio_name)
    diag_html = (
        '<div style="background: var(--bg-canvas); border: 1px solid var(--border-subtle); border-radius: 10px; padding: 14px 16px; margin-bottom: 16px;">'
        '<span class="micro-label" style="display: block; margin-bottom: 6px;">OFFLINE CACHE &amp; PWA DIAGNOSTICS</span>'
        '<p class="text-muted" style="font-size: 0.75rem; margin: 0 0 10px 0;">If icons, offline assets, or script bundles become stale on iOS/iPadOS Home Screen PWAs, force-clear local storage and hard-reload.</p>'
        '<div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">'
        '<button type="button" class="btn btn-secondary btn-sm" data-action="hvl-cache-reset" data-loading-text="Purging Cache...">Purge Offline Cache &amp; Reload</button>'
        '</div>'
        '</div>'
        if show_cache_diagnostics
        else ""
    )
    return Markup(
        f'<div id="settings-tab-appearance" class="settings-tab-content" style="display: {vis};">'
        '<div style="margin-bottom: 14px;">'
        '<h3 style="font-size: 0.9375rem; margin: 0 0 4px 0;">Appearance &amp; Theme</h3>'
        f'<p class="text-muted" style="font-size: 0.75rem; margin: 0;">Customize the visual interface and color theme for your {escape(app_label)}.</p>'
        "</div>"
        '<div style="background: var(--bg-canvas); border: 1px solid var(--border-subtle); border-radius: 10px; padding: 16px; margin-bottom: 16px;">'
        '<span class="micro-label" style="display: block; margin-bottom: 10px;">INTERFACE COLOR THEME</span>'
        f"{cards}"
        "</div>"
        f"{diag_html}"
        f"{footer_html}"
        "</div>"
    )


def hvl_household_name_card(
    name: str,
    *,
    label: str = "HOUSEHOLD NAME",
    input_id: str = "asst-family-name-input",
    form_id: str | None = "asst-family-name-form",
    btn_id: str = "btn-save-family-name",
    status_id: str = "save-family-name-status",
    can_edit: bool = True,
    placeholder: str = "e.g. Household Name",
    input_class: str = "asst-text-input",
    card_class: str = "asst-subcard",
) -> Markup:
    """Emit canonical Household / Family Office Name card."""
    dis = "" if can_edit else " disabled"
    btn_type = "submit" if form_id else "button"
    btn_html = (
        f'<button type="{btn_type}" id="{escape(btn_id)}" class="btn btn-primary btn-sm" '
        'style="padding: 6px 14px; font-size: 0.8125rem; flex-shrink: 0;">Save Name</button>'
        if can_edit
        else ""
    )
    inner_row = (
        f'<input type="text" id="{escape(input_id)}" maxlength="100" class="{escape(input_class)}" '
        f'value="{escape(name or "")}" placeholder="{escape(placeholder)}" '
        f'style="font-size: 0.875rem; padding: 6px 12px; width: 220px; max-width: 100%; flex: 1 1 180px; font-weight: 700;"{dis}>'
        f"{btn_html}"
    )
    wrap = (
        f'<form id="{escape(form_id)}" style="display: flex; gap: 8px; align-items: center; margin-top: 4px; flex-wrap: wrap; width: 100%;">{inner_row}</form>'
        if form_id
        else f'<div style="display: flex; gap: 8px; align-items: center; margin-top: 4px; flex-wrap: wrap; width: 100%;">{inner_row}</div>'
    )
    return Markup(
        f'<div class="{escape(card_class)}" style="background: var(--bg-canvas); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 14px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">'
        '<div style="width: 100%; max-width: 480px;">'
        f'<span class="micro-label">{escape(label)}</span>'
        f"{wrap}"
        "</div>"
        f'<div id="{escape(status_id)}" style="font-size: 0.8125rem; font-weight: 600; color: var(--brand-primary);"></div>'
        "</div>"
    )


def hvl_support_access_card(
    enabled: bool = False,
    *,
    toggle_id: str = "asst-support-access-toggle",
    status_id: str = "asst-support-access-status",
    checkbox_class: str = "asst-checkbox",
    card_class: str = "asst-subcard",
) -> Markup:
    """Emit canonical Developer & Admin Support Access escrow toggle card."""
    badge_cls = "badge-orange" if enabled else "badge-green"
    badge_txt = "Support Access Enabled" if enabled else "Locked (Private)"
    chk = " checked" if enabled else ""
    return Markup(
        f'<div id="support-access-card" class="{escape(card_class)}" style="background: var(--bg-canvas); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 14px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">'
        '<div style="flex: 1 1 260px; min-width: 0; max-width: 100%;">'
        '<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 4px;">'
        '<span class="micro-label" style="margin-bottom: 0;">DEVELOPER &amp; ADMIN SUPPORT ACCESS</span>'
        f'<span id="support-access-badge" class="badge {badge_cls}" style="font-size: 0.6875rem; font-weight: 700;">{badge_txt}</span>'
        "</div>"
        '<p class="text-muted" style="font-size: 0.75rem; margin: 0; line-height: 1.45;">'
        "When disabled (default), your household's encrypted data is strictly locked to your authenticated family members. Enable temporarily to grant HVL developer/admin support access for troubleshooting."
        "</p></div>"
        '<div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; max-width: 100%; min-width: 0;">'
        '<label style="display: inline-flex; align-items: center; gap: 8px; cursor: pointer; font-size: 0.8125rem; font-weight: 600;">'
        f'<input type="checkbox" class="{escape(checkbox_class)}" id="{escape(toggle_id)}"{chk}>'
        "<span>Allow Support Access</span></label>"
        f'<span id="{escape(status_id)}" style="font-size: 0.75rem; font-weight: 600; color: var(--brand-primary);"></span>'
        "</div></div>"
    )


def hvl_ai_quota_card(
    ai_key_status: dict[str, Any] | None = None,
    *,
    can_edit: bool = True,
    variant: str = "assistant",
) -> Markup:
    """Emit canonical Google Gemini API Key (Shared vs. BYO AI Quota) card."""
    aks = ai_key_status or {}
    has_custom = bool(aks.get("has_custom_key"))
    has_server = bool(aks.get("has_server_key"))
    masked = escape(str(aks.get("masked_key") or ""))
    byo_lbl = escape(str(aks.get("byo_rate_limit_label") or "30/min · 300/hr"))
    shr_lbl = escape(str(aks.get("shared_rate_limit_label") or "5/min · 30/hr"))
    shr_chars = int(aks.get("shared_max_input_chars") or 2000)
    byo_chars = int(aks.get("byo_max_input_chars") or 8000)

    is_fo = variant == "family-office"
    badge_id = ' id="asst-ai-key-badge"' if not is_fo else ""
    if has_custom:
        badge_html = f'<span{badge_id} class="badge badge-green" style="font-size: 0.6875rem;">BYO Key Active ({masked}) &middot; {byo_lbl}</span>'
    elif has_server:
        badge_html = f'<span{badge_id} class="badge badge-blue" style="font-size: 0.6875rem;">Shared Server Key &middot; {shr_lbl}</span>'
    else:
        badge_html = f'<span{badge_id} class="badge badge-orange" style="font-size: 0.6875rem;">Offline Rules Engine</span>'

    form_id = "form-gemini-key" if is_fo else "asst-ai-key-form"
    input_id = "input-settings-gemini-key" if is_fo else "asst-gemini-key-input"
    input_cls = "portal-input" if is_fo else "asst-text-input"
    save_id = "btn-save-gemini-key" if is_fo else "asst-save-ai-key-btn"
    clear_id = "btn-clear-gemini-key" if is_fo else "asst-clear-ai-key-btn"
    status_id = "gemini-key-status" if is_fo else "asst-ai-key-status"
    ph = (
        f"Configured ({masked}) — enter new key to replace"
        if has_custom
        else "Paste AIzaSy... key from Google AI Studio (or leave blank for shared server key)"
    )
    clear_btn = (
        f'<button type="button" id="{clear_id}" class="btn btn-secondary btn-sm">Clear Key</button>'
        if has_custom
        else ""
    )
    form_html = (
        f'<form id="{form_id}" class="asst-input-row" style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 0;">'
        f'<input id="{input_id}" class="{input_cls}" type="password" maxlength="256" placeholder="{ph}" style="flex: 2 1 220px; min-width: 0; padding: 7px 10px; font-size: 0.8125rem;">'
        f'<button class="btn btn-primary btn-sm" type="submit" id="{save_id}">Save Key</button>'
        f"{clear_btn}</form>"
        f'<div id="{status_id}" style="font-size: 0.75rem; font-weight: 600; color: var(--brand-primary); margin-top: 6px;"></div>'
        if can_edit
        else ""
    )

    return Markup(
        '<div id="asst-ai-key-section" class="asst-subcard" style="background: var(--bg-canvas); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 14px; margin-bottom: 16px;">'
        '<div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 6px;">'
        '<span class="micro-label" style="margin-bottom: 0;">GOOGLE GEMINI API KEY &bull; HOUSEHOLD AI QUOTA</span>'
        f"{badge_html}</div>"
        '<p class="text-muted" style="font-size: 0.75rem; margin: 0 0 10px 0; line-height: 1.45;">'
        f"Works out of the box using the <strong>shared server key</strong> (<code>{shr_lbl}</code>, <code>{shr_chars}</code> chars/prompt). "
        f"Supply your own Google AI Studio (<code>GEMINI_API_KEY</code>) encrypted with your household FEK to unlock <strong>BYO-key limits</strong> (<code>{byo_lbl}</code>, <code>{byo_chars}</code> chars/prompt)."
        f"</p>{form_html}</div>"
    )


__all__ = [
    "hvl_ai_quota_card",
    "hvl_household_name_card",
    "hvl_push_notifications_card",
    "hvl_settings_appearance_pane",
    "hvl_settings_subnav",
    "hvl_siri_shortcuts_card",
    "hvl_support_access_card",
    "hvl_theme_choice_cards",
    "hvl_user_badge",
]

