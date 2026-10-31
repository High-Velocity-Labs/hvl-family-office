"""
High Velocity Labs UI & Design Tokens

Shared client-side primitives & scoped asset bundles in `hvl_common.ui`:
- Scoped CSS modules (`HVL_CSS_SCOPES`, `resolve_hvl_css_files`, `/common/bundle.css?scopes=...`):
  - `core`: `theme.css`, `components.css`, `cards.css`, `forms.css`
  - `subnav`: `subnav.css` (`.hvl-subnav*`, `.subnav-arrow-btn`, `.hvl-dropdown*`)
  - `sidebar`: `sidebar.css` (`.app-wrapper`, `.sidebar*`, `.user-badge*`, `.sidebar-tooltip`)
  - `modal`: `modal-dialog.css`, `settings-modal.css` (`.hvl-settings-modal-dialog`, `.theme-choice-grid`)
  - `chat`: `chat-drawer.css`
  - `notifications`: `notifications-drawer.css`
- Scoped JS modules (`HVL_JS_SCOPES`, `resolve_hvl_js_files`, `/common/bundle.js?scopes=...`):
  - `htmx`: `htmx.min.js`, `idiomorph-ext.min.js`
  - `core`: `utils.js` (`initTheme`, `initSidebar`, `initPinchZoomOutGuard`, `morphFragment`, `hvlForceCacheReset`, `hvlReloadForUpdate`)
  - `subnav`: `subnav.js` (`window.positionDropdownMenu`, `initDropdowns`, `initScrollableRibbon`)
  - `modal`: `modal-dialog.js`, `bug-reporter.js` (`showModalAlert`, `openModal`, `openBugReportModal`)
  - `chat`: `marked.min.js`, `chat-drawer.js`, `chat-attachments.js`
  - `notifications`: `notifications-drawer.js`, `device-integrations.js`
  - `toast`: `toast.js`
  - `signals`: `version_pill.js`, `reactive-signals.js`
- `.hvl-card-header`, `.hvl-card-header-row`, `.hvl-card-title-group`, `.hvl-card-title-row`, `.hvl-card-actions`:
  Canonical card/subcard header layout primitives; `.hvl-card-title-row` renders `<h2|h3|h4|strong>Title</h2|h3|h4|strong><span class="badge">Pill</span>`
  inline to the right on desktop (`>768px`) and automatically stacks `.badge` pills below the heading/name (`flex: 0 0 100%` on heading/`strong`) on `<=768px` mobile.
- Canonical Button Parity Contract (`.btn`, `.custom-modal-btn`):
  All interactive buttons must use base `.btn` + variant (`.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-ghost`) + optional size modifier (`.btn-sm`, `.btn-xs`, `.btn-icon`, `.btn-icon-xs`, `.btn-icon-danger`) or `.custom-modal-btn` (`.custom-modal-btn-cancel`, `.custom-modal-btn-primary`), with zero inline `padding`, `height`, or `font-size` overrides and identical size tier across sibling buttons in any action row.
- Canonical Switch (`.hvl-switch`, `.hvl-switch-sm`, in `forms.css`): a bare
  `<input type="checkbox" class="hvl-switch">` drawn as an on/off switch, no wrapper markup; `.hvl-switch-sm` sits
  inside a `.btn-sm`-height row, and `--hvl-switch-on` recolors the on state.
- Canonical Form Control Contract (`.form-input`, `.form-select`, `.form-textarea`, `.form-input-sm`, `.form-select-sm`, `.form-label`, `.form-grid-2`):
  All text/number/date/email/password/search `<input>`, `<select>`, and `<textarea>` elements use canonical `.form-input`, `.form-select`, `.form-textarea` (plus `.form-input-sm` / `.form-select-sm` compact variants, `.form-label`, and `.form-grid-2` layout helpers in `forms.css` with `box-sizing: border-box`), with zero inline `padding`, `height`, `font-size`, `border`, or `border-radius` overrides.
"""

from hvl_common.ui.blueprint import (
    ui_bp,
    render_icon,
    hvl_common_styles,
    hvl_common_scripts,
    hvl_theme_init_script,
    hvl_theme_toggle_btn,
    hvl_theme_choice_cards,
    hvl_user_badge,
    hvl_subnav_bar,
    hvl_settings_subnav,
    hvl_settings_header,
    hvl_settings_appearance_pane,
    hvl_household_name_card,
    hvl_support_access_card,
    hvl_ai_quota_card,
    hvl_push_notifications_card,
    hvl_siri_shortcuts_card,
    hvl_notification_bell,
    hvl_notification_drawer,
    render_notifications_drawer_items,
)
from hvl_common.ui.cards import (
    hvl_card_header,
    hvl_icon_btn,
    hvl_subcard,
)
from hvl_common.ui.notifications import CATEGORY_ICON_MAP
from hvl_common.ui.formatting import (
    fmt_currency,
    fmt_short_currency,
    fmt_pct,
    render_chat_markdown,
    tokenize_inline_markdown,
    _tokenize_inline_markdown,
    parse_changelog_releases,
)
from hvl_common.ui.bundler import (
    HVL_CSS_SCOPES,
    HVL_JS_SCOPES,
    resolve_hvl_css_files,
    resolve_hvl_js_files,
    build_bundles,
    bundle_css_files,
    bundle_js_files,
)

icon = render_icon

__all__ = [
    "ui_bp",
    "render_icon",
    "icon",
    "hvl_icon_btn",
    "hvl_card_header",
    "hvl_subcard",
    "hvl_common_styles",
    "hvl_common_scripts",
    "hvl_theme_init_script",
    "hvl_theme_toggle_btn",
    "hvl_theme_choice_cards",
    "hvl_user_badge",
    "hvl_subnav_bar",
    "hvl_settings_subnav",
    "hvl_settings_header",
    "hvl_settings_appearance_pane",
    "hvl_household_name_card",
    "hvl_support_access_card",
    "hvl_ai_quota_card",
    "hvl_push_notifications_card",
    "hvl_siri_shortcuts_card",
    "CATEGORY_ICON_MAP",
    "hvl_notification_bell",
    "hvl_notification_drawer",
    "render_notifications_drawer_items",
    "fmt_currency",
    "fmt_short_currency",
    "fmt_pct",
    "render_chat_markdown",
    "tokenize_inline_markdown",
    "_tokenize_inline_markdown",
    "parse_changelog_releases",
    "HVL_CSS_SCOPES",
    "HVL_JS_SCOPES",
    "resolve_hvl_css_files",
    "resolve_hvl_js_files",
    "build_bundles",
    "bundle_css_files",
    "bundle_js_files",
]
