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
    enable_btn_id: str = "asst-enable-push-btn",
    test_btn_id: str = "hvl-test-push-btn",
    status_id: str = "asst-push-status",
    card_class: str = "asst-subcard",
) -> Markup:
    """Emit canonical Device Push Notifications card with Enable, Test Push, and iOS Home Screen instructions."""
    clean_app = escape(app_name or "HVL")
    return Markup(
        f'<div class="{escape(card_class)}" style="background: var(--bg-canvas); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 14px; margin-bottom: 0; min-width: 0; box-sizing: border-box;">'
        '<div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 6px;">'
        '<span class="micro-label" style="margin-bottom: 0;">DEVICE PUSH NOTIFICATIONS</span>'
        f'<span class="badge badge-blue" style="font-size: 0.6875rem;">{clean_app} PWA</span>'
        "</div>"
        '<p class="text-muted" style="font-size: 0.75rem; margin: 0 0 10px 0; line-height: 1.45;">'
        f"Receive real-time lock-screen alerts from {clean_app} on iOS/iPadOS Home Screen PWAs and desktop browsers."
        "</p>"
        '<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">'
        f'<button class="btn btn-secondary btn-sm" type="button" id="{escape(enable_btn_id)}" data-action="hvl-enable-push" data-status-target="#{escape(status_id)}">'
        "Enable Push on This Device"
        "</button>"
        f'<button class="btn btn-secondary btn-sm" type="button" id="{escape(test_btn_id)}" data-action="hvl-test-push" data-status-target="#{escape(status_id)}">'
        "Send Test Push"
        "</button>"
        f'<span id="{escape(status_id)}" style="font-size: 0.75rem; font-weight: 600; color: var(--brand-primary); line-height: 1.35;"></span>'
        "</div>"
        '<div style="margin-top: 10px; font-size: 0.72rem; color: var(--text-muted); line-height: 1.4; padding: 8px 10px; background: var(--bg-surface-elevated, rgba(0,0,0,0.03)); border-radius: 6px; border: 1px dashed var(--border-subtle); overflow-wrap: anywhere; word-break: break-word;">'
        "<strong>iPhone / iPad Setup:</strong> Apple requires installing as a Home Screen web app before enabling push. "
        "In Safari or Chrome, tap <strong>Share -&gt; Add to Home Screen</strong>, open the installed app from your Home Screen, then tap <strong>Enable Push on This Device</strong>."
        "</div>"
        "</div>"
    )


def hvl_siri_shortcuts_card(
    *,
    app_name: str = "HVL",
    endpoint_url: str = "/api/siri",
    mint_btn_id: str = "asst-mint-siri-btn",
    revoke_btn_id: str = "hvl-revoke-siri-btn",
    display_id: str = "siri-token-display",
    example_prompt: str = "Ask a question...",
    card_class: str = "asst-subcard",
) -> Markup:
    """Emit canonical Siri & Apple Shortcuts card with Mint, Revoke, Copy, and setup instructions."""
    clean_app = escape(app_name or "HVL")
    clean_endpoint = escape(endpoint_url or "/api/siri")
    clean_prompt = escape(example_prompt or "Ask a question...")
    return Markup(
        f'<div class="{escape(card_class)}" style="background: var(--bg-canvas); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 14px; margin-bottom: 0; min-width: 0; box-sizing: border-box;">'
        '<div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 6px;">'
        '<span class="micro-label" style="margin-bottom: 0;">SIRI &amp; APPLE SHORTCUTS</span>'
        '<span class="badge badge-blue" style="font-size: 0.6875rem;">Voice &amp; Action Button</span>'
        "</div>"
        '<p class="text-muted" style="font-size: 0.75rem; margin: 0 0 10px 0; line-height: 1.45;">'
        f"Mint a personal bearer key for hands-free Siri voice queries and iPhone Action Button shortcuts to {clean_app}."
        "</p>"
        '<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">'
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
        f'<div id="{escape(display_id)}" style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--brand-primary); margin-top: 8px; word-break: break-all;"></div>'
        '<div style="margin-top: 10px; font-size: 0.72rem; color: var(--text-muted); line-height: 1.4; padding: 8px 10px; background: var(--bg-surface-elevated, rgba(0,0,0,0.03)); border-radius: 6px; border: 1px dashed var(--border-subtle); overflow-wrap: anywhere; word-break: break-word;">'
        f"<strong>Apple Shortcuts Setup:</strong> Add <em>Ask for Input</em> (e.g. &ldquo;{clean_prompt}&rdquo;) -&gt; "
        f'<em>Get Contents of URL</em> (<code style="word-break: break-all;">POST {clean_endpoint}</code>, header <code style="word-break: break-all;">Authorization: Bearer &lt;token&gt;</code>, '
        'JSON body <code style="word-break: break-all;">{"text": "&lt;Provided Input&gt;", "sync": true}</code>) -&gt; <em>Get Dictionary Value</em> (<code>reply</code>) -&gt; <em>Speak Text</em>.'
        "</div>"
        "</div>"
    )


__all__ = [
    "hvl_push_notifications_card",
    "hvl_siri_shortcuts_card",
]
