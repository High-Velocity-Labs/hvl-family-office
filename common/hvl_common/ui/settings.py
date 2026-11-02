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
from hvl_common.ui.subnav import (
    hvl_settings_header,
    hvl_settings_subnav,
    hvl_subnav_bar,
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
        '<div class="theme-choice-card-top">'
        f'<div class="theme-choice-card-label">{sun_svg}'
        '<strong class="theme-choice-card-title">Light Mode</strong></div>'
        f'<input type="radio" name="{radio_name}" value="light" '
        'aria-label="Light Mode" class="theme-choice-radio"></div>'
        '<p class="text-muted theme-choice-card-desc">'
        "Crisp paper-white canvas with clean slate typography and high-contrast surfaces.</p>"
        "</div>"
        '<div class="theme-choice-card" data-theme-value="dark">'
        '<div class="theme-choice-card-top">'
        '<div class="theme-choice-card-label">'
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>'
        '<strong class="theme-choice-card-title">Dark Mode</strong></div>'
        f'<input type="radio" name="{radio_name}" value="dark" '
        'aria-label="Dark Mode" class="theme-choice-radio"></div>'
        '<p class="text-muted theme-choice-card-desc">'
        "Deep charcoal &amp; slate palette for reduced eye strain and night-time comfort.</p>"
        "</div>"
        '<div class="theme-choice-card" data-theme-value="system">'
        '<div class="theme-choice-card-top">'
        '<div class="theme-choice-card-label">'
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>'
        '<line x1="8" y1="21" x2="16" y2="21"></line>'
        '<line x1="12" y1="17" x2="12" y2="21"></line></svg>'
        '<strong class="theme-choice-card-title">System Default</strong></div>'
        f'<input type="radio" name="{radio_name}" value="system" '
        'aria-label="System Default" class="theme-choice-radio"></div>'
        '<p class="text-muted theme-choice-card-desc">'
        "Automatically aligns with your operating system or phone light/dark schedule.</p>"
        "</div></div>"
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
    hidden_attr = "" if (active_tab or "") in match_tabs else " hidden"
    cards = hvl_theme_choice_cards(radio_name=radio_name)
    diag_html = (
        '<div class="hvl-settings-card">'
        '<span class="micro-label">OFFLINE CACHE &amp; PWA DIAGNOSTICS</span>'
        '<p class="text-muted hvl-settings-card-desc">'
        "If icons, offline assets, or script bundles become stale on iOS/iPadOS Home Screen PWAs, "
        "force-clear local storage and hard-reload.</p>"
        '<div class="hvl-settings-actions-row">'
        '<button type="button" class="btn btn-secondary btn-sm" '
        'data-action="hvl-cache-reset" data-loading-text="Purging Cache...">'
        "Purge Offline Cache &amp; Reload</button>"
        "</div>"
        "</div>"
        if show_cache_diagnostics
        else ""
    )
    return Markup(
        f'<div id="settings-tab-appearance" class="settings-tab-content"{hidden_attr}>'
        '<div class="hvl-settings-pane-intro">'
        '<h3 class="hvl-settings-pane-title">Appearance &amp; Theme</h3>'
        '<p class="text-muted hvl-settings-pane-desc">'
        f"Customize the visual interface and color theme for your {escape(app_label)}.</p>"
        "</div>"
        '<div class="hvl-settings-card">'
        '<span class="micro-label hvl-settings-section-label">INTERFACE COLOR THEME</span>'
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
    input_id: str = "hvl-family-name-input",
    form_id: str | None = "hvl-family-name-form",
    btn_id: str = "btn-save-family-name",
    status_id: str = "save-family-name-status",
    can_edit: bool = True,
    placeholder: str = "e.g. Household Name",
    input_class: str = "",
    card_class: str = "hvl-settings-card",
) -> Markup:
    """Emit canonical Household / Family Office Name card."""
    dis = "" if can_edit else " disabled"
    btn_type = "submit" if form_id else "button"
    btn_html = (
        f'<button type="{btn_type}" id="{escape(btn_id)}" class="btn btn-primary btn-sm">Save Name</button>'
        if can_edit
        else ""
    )
    cls_tokens = " ".join(
        dict.fromkeys(
            ["form-input", "form-input-sm", "hvl-household-name-input", *input_class.split()]
        )
    )
    inner_row = (
        f'<input type="text" id="{escape(input_id)}" maxlength="100" class="form-input form-input-sm {escape(cls_tokens)}" '
        f'value="{escape(name or "")}" placeholder="{escape(placeholder)}"{dis}>'
        f"{btn_html}"
    )
    wrap = (
        f'<form id="{escape(form_id)}" class="hvl-input-row">{inner_row}</form>'
        if form_id
        else f'<div class="hvl-input-row">{inner_row}</div>'
    )
    return Markup(
        f'<div class="{escape(card_class)} hvl-settings-card-split">'
        '<div class="hvl-household-name-col">'
        f'<span class="micro-label">{escape(label)}</span>'
        f"{wrap}"
        "</div>"
        f'<div id="{escape(status_id)}" class="hvl-settings-status"></div>'
        "</div>"
    )


def hvl_support_access_card(
    enabled: bool = False,
    *,
    toggle_id: str = "hvl-support-access-toggle",
    status_id: str = "hvl-support-access-status",
    checkbox_class: str = "hvl-checkbox",
    card_class: str = "hvl-settings-card",
) -> Markup:
    """Emit canonical Developer & Admin Support Access escrow toggle card."""
    badge_cls = "badge-orange" if enabled else "badge-green"
    badge_txt = "Support Access Enabled" if enabled else "Locked (Private)"
    chk = " checked" if enabled else ""
    return Markup(
        f'<div id="support-access-card" class="{escape(card_class)} hvl-settings-card-split">'
        '<div class="hvl-support-info-col">'
        '<div class="hvl-settings-card-title-row">'
        '<span class="micro-label micro-label-flush">DEVELOPER &amp; ADMIN SUPPORT ACCESS</span>'
        f'<span id="support-access-badge" class="badge {badge_cls} hvl-settings-badge-sm">{badge_txt}</span>'
        "</div>"
        '<p class="text-muted hvl-settings-card-desc-flush">'
        "When disabled (default), your household's encrypted data is strictly locked to your authenticated family members. Enable temporarily to grant HVL developer/admin support access for troubleshooting."
        "</p></div>"
        '<div class="hvl-settings-actions-row">'
        '<label class="form-label hvl-support-toggle-label">'
        f'<input type="checkbox" class="{escape(checkbox_class)}" id="{escape(toggle_id)}"{chk}>'
        "<span>Allow Support Access</span></label>"
        f'<span id="{escape(status_id)}" class="hvl-settings-status"></span>'
        "</div></div>"
    )


def hvl_ai_quota_card(
    ai_key_status: dict[str, Any] | None = None,
    *,
    can_edit: bool = True,
    input_class: str = "",
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

    badge_id = ' id="hvl-ai-key-badge"'
    if has_custom:
        badge_html = (
            f'<span{badge_id} class="badge badge-green hvl-settings-badge-sm">'
            f"BYO Key Active ({masked}) &middot; {byo_lbl}</span>"
        )
    elif has_server:
        badge_html = (
            f'<span{badge_id} class="badge badge-blue hvl-settings-badge-sm">'
            f"Shared Server Key &middot; {shr_lbl}</span>"
        )
    else:
        badge_html = f'<span{badge_id} class="badge badge-orange hvl-settings-badge-sm">Offline Rules Engine</span>'

    ph = (
        f"Configured ({masked}) — enter new key to replace"
        if has_custom
        else "Paste AIzaSy... key from Google AI Studio (or leave blank for shared server key)"
    )
    clear_btn = (
        '<button type="button" id="hvl-ai-key-clear-btn" class="btn btn-secondary btn-sm">Clear Key</button>'
        if has_custom
        else ""
    )
    form_html = (
        '<form id="hvl-ai-key-form" class="hvl-input-row hvl-input-row-flush">'
        f'<input id="hvl-ai-key-input" class="form-input form-input-sm hvl-ai-key-input {escape(input_class)}" '
        f'type="password" maxlength="256" placeholder="{ph}">'
        '<button class="btn btn-primary btn-sm" type="submit" id="hvl-ai-key-save-btn">Save Key</button>'
        f"{clear_btn}</form>"
        '<div id="hvl-ai-key-status" class="hvl-settings-status hvl-settings-status-spaced"></div>'
        if can_edit
        else ""
    )

    return Markup(
        '<div id="hvl-ai-key-section" class="hvl-settings-card">'
        '<div class="hvl-settings-card-header">'
        '<span class="micro-label micro-label-flush">GOOGLE GEMINI API KEY &bull; HOUSEHOLD AI QUOTA</span>'
        f"{badge_html}</div>"
        '<p class="text-muted hvl-settings-card-desc">'
        f"Works out of the box using the <strong>shared server key</strong> (<code>{shr_lbl}</code>, <code>{shr_chars}</code> chars/prompt). "
        f"Supply your own Google AI Studio (<code>GEMINI_API_KEY</code>) encrypted with your household FEK to unlock <strong>BYO-key limits</strong> (<code>{byo_lbl}</code>, <code>{byo_chars}</code> chars/prompt)."
        f"</p>{form_html}</div>"
    )


__all__ = [
    "hvl_ai_quota_card",
    "hvl_household_name_card",
    "hvl_push_notifications_card",
    "hvl_settings_appearance_pane",
    "hvl_settings_header",
    "hvl_settings_subnav",
    "hvl_siri_shortcuts_card",
    "hvl_subnav_bar",
    "hvl_support_access_card",
    "hvl_theme_choice_cards",
    "hvl_user_badge",
]

