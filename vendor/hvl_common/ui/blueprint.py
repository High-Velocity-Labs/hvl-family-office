import re
import sys
from pathlib import Path
from flask import Blueprint, send_from_directory
from markupsafe import Markup, escape


def _resolve_static_dir() -> Path:
    candidates = [Path(__file__).resolve().parent / "static"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        mp = Path(meipass)
        candidates.append(mp / "hvl_common" / "ui" / "static")
        candidates.append(mp / "vendor" / "hvl_common" / "ui" / "static")
    for parent in Path(__file__).resolve().parents:
        cand = parent / "vendor" / "hvl_common" / "ui" / "static"
        if cand not in candidates:
            candidates.append(cand)
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


STATIC_DIR = _resolve_static_dir()

ui_bp = Blueprint(
    "hvl_common_ui",
    __name__,
    static_folder=str(STATIC_DIR),
    static_url_path="/common",
)

_ICON_SYMBOLS: dict[str, tuple[str, str]] = {}


def _load_icon_symbols() -> None:
    svg_path = STATIC_DIR / "icons.svg"
    if not svg_path.exists():
        return
    raw = svg_path.read_text(encoding="utf-8")
    for m in re.finditer(r'<symbol\s+id="([^"]+)"([^>]*)>(.*?)</symbol>', raw, re.DOTALL):
        sym_id, attrs, inner = m.group(1), m.group(2).strip(), m.group(3).strip()
        _ICON_SYMBOLS[sym_id] = (attrs, inner)


_load_icon_symbols()


def render_icon(name: str, css_class: str = "", width=None, height=None, **kwargs) -> Markup:
    """Renders an inline SVG icon resolved from the canonical HVL icon sprite (zero-flash SSR)."""
    icon_id = name.lstrip("#")
    if not icon_id.startswith("icon-"):
        icon_id = f"icon-{icon_id}"

    classes = f"hvl-icon {css_class}".strip()
    size_attrs = ""
    if width is not None:
        size_attrs += f' width="{width}"'
    if height is not None:
        size_attrs += f' height="{height}"'

    ver = kwargs.pop("version", None) or kwargs.pop("v", None)
    extra_attrs = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in kwargs.items())
    if extra_attrs:
        extra_attrs = " " + extra_attrs

    sym = _ICON_SYMBOLS.get(icon_id) or _ICON_SYMBOLS.get(name.lstrip("#"))
    if sym:
        sym_attrs, inner_svg = sym
        sym_attrs_str = f" {sym_attrs}" if sym_attrs else ""
        return Markup(
            f'<svg class="{classes}" aria-hidden="true"{size_attrs}{sym_attrs_str}{extra_attrs}>'
            f'{inner_svg}'
            f'</svg>'
        )

    if not ver:
        try:
            from flask import current_app, g
            ver = getattr(g, "asset_version", None) or current_app.config.get("ASSET_VERSION") or current_app.config.get("APP_VERSION") or ""
        except Exception:
            ver = ""
    q = f"?v={ver}" if ver else ""

    return Markup(
        f'<svg class="{classes}" aria-hidden="true"{size_attrs}{extra_attrs}>'
        f'<use href="/common/icons.svg{q}#{icon_id}"></use>'
        f'</svg>'
    )


@ui_bp.app_template_global("render_icon")
def _app_render_icon(name: str, css_class: str = "", width=None, height=None, **kwargs):
    return render_icon(name, css_class, width=width, height=height, **kwargs)


@ui_bp.app_template_global("icon")
def _app_icon(name: str, css_class: str = "", width=None, height=None, **kwargs):
    return render_icon(name, css_class, width=width, height=height, **kwargs)


from hvl_common.ui.formatting import (  # noqa: E402
    fmt_currency,
    fmt_short_currency,
    fmt_pct,
    render_chat_markdown,
)


def hvl_theme_init_script() -> Markup:
    """Emit zero-FOUC color-scheme meta and inline script applying saved/OS theme before first paint."""
    return Markup(
        '<meta name="color-scheme" content="light dark">\n  '
        "<script>(function(){try{var ks=['hvl_theme','asst_theme','fo_theme','ff_theme'],s=null;"
        "for(var i=0;i<ks.length;i++){var v=localStorage.getItem(ks[i]);if(v==='light'||v==='dark'||v==='system'){s=v;break;}}"
        "var d=s==='dark'||((!s||s==='system')&&window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches);"
        "document.documentElement.setAttribute('data-theme',d?'dark':'light');"
        "var m=document.querySelector('meta[name=\"color-scheme\"]');if(m)m.content=(!s||s==='system')?'light dark':(d?'dark':'light');"
        "}catch(_){}})();</script>"
    )


def hvl_theme_toggle_btn(btn_id: str = "btn-theme-toggle", css_class: str = "theme-btn-compact") -> Markup:
    """Emit canonical compact sun/moon theme toggle button wired to hvl_common utils.js."""
    return Markup(
        f'<button type="button" id="{btn_id}" class="{css_class}" data-action="toggle-theme" '
        'title="Toggle Dark / Light Mode" aria-label="Toggle Theme">'
        '<svg class="theme-icon-sun" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line>'
        '<line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>'
        '<line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line>'
        '<line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>'
        '<svg class="theme-icon-moon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>'
        "</button>"
    )


def hvl_common_styles(
    version: str = "",
    *,
    modal: bool = True,
    chat: bool = True,
    notifications: bool = True,
    theme_init: bool = True,
) -> Markup:
    """Emit canonical HVL shared stylesheet links in deterministic order (with optional FOUC theme init)."""
    q = f"?v={version}" if version else ""
    files = ["theme.css", "components.css"]
    if modal:
        files.append("modal-dialog.css")
    if chat:
        files.append("chat-drawer.css")
    if notifications:
        files.append("notifications-drawer.css")
    tags = ([str(hvl_theme_init_script())] if theme_init else []) + [
        f'<link rel="stylesheet" href="/common/{f}{q}">' for f in files
    ]
    return Markup("\n  ".join(tags))


def hvl_common_scripts(
    version: str = "",
    *,
    htmx: bool = True,
    modal: bool = True,
    chat: bool = True,
    notifications: bool = True,
    toast: bool = True,
    defer: bool = False,
) -> Markup:
    """Emit canonical HVL shared script tags (including marked.min.js before chat-drawer.js)."""
    q = f"?v={version}" if version else ""
    d_attr = " defer" if defer else ""
    files: list[str] = []
    if htmx:
        files.extend(["htmx.min.js", "idiomorph-ext.min.js"])
    if chat:
        files.append("marked.min.js")
    files.extend(["subnav.js", "utils.js"])
    if modal:
        files.append("modal-dialog.js")
    if chat:
        files.extend(["chat-drawer.js", "chat-attachments.js"])
    if notifications:
        files.extend(["notifications-drawer.js", "device-integrations.js"])
    if toast:
        files.append("toast.js")
    tags: list[str] = []
    if version:
        tags.append(
            f'<script>window.__APP_VERSION__ = window.__APP_VERSION__ || "{escape(version)}";</script>'
        )
    tags.extend(f'<script src="/common/{f}{q}"{d_attr}></script>' for f in files)
    return Markup("\n  ".join(tags))


@ui_bp.app_template_global("hvl_common_styles")
def _app_hvl_common_styles(version: str = "", **kwargs) -> Markup:
    return hvl_common_styles(version, **kwargs)


@ui_bp.app_template_global("hvl_common_scripts")
def _app_hvl_common_scripts(version: str = "", **kwargs) -> Markup:
    return hvl_common_scripts(version, **kwargs)


@ui_bp.app_template_global("hvl_theme_init_script")
def _app_hvl_theme_init_script() -> Markup:
    return hvl_theme_init_script()


@ui_bp.app_template_global("hvl_theme_toggle_btn")
def _app_hvl_theme_toggle_btn(btn_id: str = "btn-theme-toggle", css_class: str = "theme-btn-compact") -> Markup:
    return hvl_theme_toggle_btn(btn_id=btn_id, css_class=css_class)


from hvl_common.ui.notifications import (  # noqa: E402
    hvl_notification_bell,
    hvl_notification_drawer,
    render_notifications_drawer_items,
)
from hvl_common.ui.settings import (  # noqa: E402
    hvl_ai_quota_card,
    hvl_household_name_card,
    hvl_settings_appearance_pane,
    hvl_settings_subnav,
    hvl_support_access_card,
    hvl_theme_choice_cards,
    hvl_user_badge,
)
from hvl_common.ui.settings_household import (  # noqa: E402
    hvl_household_groups_section,
    hvl_household_members_section,
)
from hvl_common.ui.settings_integrations import (  # noqa: E402
    hvl_push_notifications_card,
    hvl_siri_shortcuts_card,
)

for _fn_name, _fn in (
    ("hvl_theme_choice_cards", hvl_theme_choice_cards),
    ("hvl_user_badge", hvl_user_badge),
    ("hvl_notification_bell", hvl_notification_bell),
    ("hvl_notification_drawer", hvl_notification_drawer),
    ("render_notifications_drawer_items", render_notifications_drawer_items),
    ("hvl_settings_subnav", hvl_settings_subnav),
    ("hvl_settings_appearance_pane", hvl_settings_appearance_pane),
    ("hvl_household_name_card", hvl_household_name_card),
    ("hvl_support_access_card", hvl_support_access_card),
    ("hvl_ai_quota_card", hvl_ai_quota_card),
    ("hvl_household_members_section", hvl_household_members_section),
    ("hvl_household_groups_section", hvl_household_groups_section),
    ("hvl_push_notifications_card", hvl_push_notifications_card),
    ("hvl_siri_shortcuts_card", hvl_siri_shortcuts_card),
):
    ui_bp.add_app_template_global(_fn, _fn_name)


@ui_bp.app_template_filter("chat_markdown")
@ui_bp.app_template_global("chat_markdown")
def _app_chat_markdown(val) -> Markup:
    return render_chat_markdown(val)


@ui_bp.app_template_filter("fmt_currency")
@ui_bp.app_template_filter("format_currency")
@ui_bp.app_template_global("fmt_currency")
def _app_fmt_currency(val, decimals: int = 0) -> str:
    return fmt_currency(val, decimals)


@ui_bp.app_template_filter("fmt_short_currency")
@ui_bp.app_template_filter("format_short_currency")
@ui_bp.app_template_global("fmt_short_currency")
def _app_fmt_short_currency(val) -> str:
    return fmt_short_currency(val)


@ui_bp.app_template_filter("fmt_pct")
@ui_bp.app_template_filter("format_pct")
@ui_bp.app_template_global("fmt_pct")
def _app_fmt_pct(val, decimals: int = 1) -> str:
    return fmt_pct(val, decimals)


@ui_bp.route("/studio")
@ui_bp.route("/studio.html")
def studio():
    """Serves the living design studio portal."""
    return send_from_directory(str(STATIC_DIR), "studio.html")


@ui_bp.route("/icons")
@ui_bp.route("/icons.html")
@ui_bp.route("/catalog")
@ui_bp.route("/icons/catalog")
def icons_catalog():
    """Serves the canonical HVL iconography system catalog."""
    return send_from_directory(str(STATIC_DIR), "icons.html")
