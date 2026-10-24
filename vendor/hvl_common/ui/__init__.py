"""
High Velocity Labs UI & Design Tokens

Shared client-side primitives in `/common/components.css` & `/common/subnav.js`:
- `.hvl-dropdown-wrap` / `.hvl-dropdown-menu` + `window.positionDropdownMenu(menuEl, opts)` / `initDropdowns()`:
  Viewport-aware dropdown menu container and clamping helper (prevents mobile left/right/center offscreen clipping).
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
    hvl_household_members_section,
    hvl_household_groups_section,
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
    "hvl_household_members_section",
    "hvl_household_groups_section",
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
    "build_bundles",
    "bundle_css_files",
    "bundle_js_files",
]
