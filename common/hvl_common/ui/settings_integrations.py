"""
Shared Device Push Notifications & Siri / Apple Shortcuts Settings Cards
(`hvl_common.ui.settings_integrations`).

Provides reusable Jinja SSR macros `hvl_push_notifications_card` and `hvl_siri_shortcuts_card`
paired with `/common/device-integrations.js`.
"""

from __future__ import annotations

from markupsafe import Markup, escape


def hvl_push_notifications_card(
    *,
    app_name: str = "HVL",
    enable_btn_id: str = "hvl-enable-push-btn",
    test_btn_id: str = "hvl-test-push-btn",
    status_id: str = "hvl-push-status",
    card_class: str = "hvl-settings-card",
) -> Markup:
    """Emit canonical Device Push Notifications card with Enable, Test Push, and iOS Home Screen instructions."""
    clean_app = escape(app_name or "HVL")
    return Markup(
        f'<div class="{escape(card_class)} hvl-settings-card-flush">'
        '<div class="hvl-settings-card-header">'
        '<span class="micro-label micro-label-flush">DEVICE PUSH NOTIFICATIONS</span>'
        f'<span class="badge badge-blue hvl-settings-badge-sm">{clean_app} PWA</span>'
        "</div>"
        '<p class="text-muted hvl-settings-card-desc">'
        f"Receive real-time lock-screen alerts from {clean_app} on iOS/iPadOS Home Screen PWAs and desktop browsers."
        "</p>"
        '<div class="hvl-settings-actions-row">'
        f'<button class="btn btn-secondary btn-sm" type="button" id="{escape(enable_btn_id)}" data-action="hvl-enable-push" data-status-target="#{escape(status_id)}">'
        "Enable Push on This Device"
        "</button>"
        f'<button class="btn btn-secondary btn-sm" type="button" id="{escape(test_btn_id)}" data-action="hvl-test-push" data-status-target="#{escape(status_id)}">'
        "Send Test Push"
        "</button>"
        f'<span id="{escape(status_id)}" class="hvl-settings-status"></span>'
        "</div>"
        '<div class="hvl-settings-note-box">'
        "<strong>iPhone / iPad Setup:</strong> Apple requires installing as a Home Screen web app before enabling push. "
        "In Safari or Chrome, tap <strong>Share -&gt; Add to Home Screen</strong>, open the installed app from your Home Screen, then tap <strong>Enable Push on This Device</strong>."
        "</div>"
        "</div>"
    )


def hvl_siri_shortcuts_card(
    *,
    app_name: str = "HVL",
    endpoint_url: str = "/api/siri",
    mint_btn_id: str = "hvl-mint-siri-btn",
    revoke_btn_id: str = "hvl-revoke-siri-btn",
    display_id: str = "siri-token-display",
    example_prompt: str = "Ask a question...",
    card_class: str = "hvl-settings-card",
) -> Markup:
    """Emit canonical Siri & Apple Shortcuts card with Mint, Revoke, Copy, and setup instructions."""
    clean_app = escape(app_name or "HVL")
    clean_endpoint = escape(endpoint_url or "/api/siri")
    clean_prompt = escape(example_prompt or "Ask a question...")
    return Markup(
        f'<div class="{escape(card_class)} hvl-settings-card-flush">'
        '<div class="hvl-settings-card-header">'
        '<span class="micro-label micro-label-flush">SIRI &amp; APPLE SHORTCUTS</span>'
        '<span class="badge badge-blue hvl-settings-badge-sm">Voice &amp; Action Button</span>'
        "</div>"
        '<p class="text-muted hvl-settings-card-desc">'
        f"Mint a personal bearer key for hands-free Siri voice queries and iPhone Action Button shortcuts to {clean_app}."
        "</p>"
        '<div class="hvl-settings-actions-row">'
        f'<button class="btn btn-secondary btn-sm" type="button" id="{escape(mint_btn_id)}" data-action="hvl-mint-siri" data-display-target="#{escape(display_id)}">'
        "Generate Siri Shortcut Key"
        "</button>"
        f'<button class="btn btn-secondary btn-sm" type="button" id="{escape(revoke_btn_id)}" data-action="hvl-revoke-siri" data-display-target="#{escape(display_id)}">'
        "Revoke Key"
        "</button>"
        f'<button class="btn btn-secondary btn-sm" type="button" data-action="hvl-copy-siri" data-display-target="#{escape(display_id)}">'
        "Copy Key"
        "</button>"
        "</div>"
        f'<div id="{escape(display_id)}" class="hvl-endpoint-box hvl-settings-siri-token"></div>'
        '<div class="hvl-settings-note-box">'
        f"<strong>Apple Shortcuts Setup:</strong> Add <em>Ask for Input</em> (e.g. &ldquo;{clean_prompt}&rdquo;) -&gt; "
        f'<em>Get Contents of URL</em> (<code class="hvl-endpoint-box">POST {clean_endpoint}</code>, '
        'header <code class="hvl-endpoint-box">Authorization: Bearer &lt;token&gt;</code>, '
        'JSON body <code class="hvl-endpoint-box">{"text": "&lt;Provided Input&gt;"}</code>) -&gt; '
        "<em>Get Dictionary Value</em> (<code>reply</code>) -&gt; <em>Speak Text</em>."
        "</div>"
        "</div>"
    )


__all__ = [
    "hvl_push_notifications_card",
    "hvl_siri_shortcuts_card",
]
