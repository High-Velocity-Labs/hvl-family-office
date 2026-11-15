import re
import sys
from pathlib import Path
from typing import Iterable
from flask import Blueprint, Response, request, send_from_directory
from markupsafe import Markup, escape

from hvl_common.ui.bundler import (
    HVL_CSS_SCOPES,
    HVL_JS_SCOPES,
    _parse_scope_names,
    resolve_hvl_css_files,
    resolve_hvl_js_files,
)


def _resolve_static_dir() -> Path:
    candidates = [Path(__file__).resolve().parent / "static"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "hvl_common" / "ui" / "static")
    return next((c for c in candidates if c.exists()), candidates[0])


STATIC_DIR = _resolve_static_dir()
ui_bp = Blueprint("hvl_common_ui", __name__, static_folder=str(STATIC_DIR), static_url_path="/common")
_ICON_SYMBOLS: dict[str, tuple[str, str]] = {}


def _load_icon_symbols() -> None:
    svg_path = STATIC_DIR / "icons.svg"
    if not svg_path.exists():
        return
    raw = svg_path.read_text(encoding="utf-8")
    for m in re.finditer(r'<symbol\s+id="([^"]+)"([^>]*)>(.*?)</symbol>', raw, re.DOTALL):
        _ICON_SYMBOLS[m.group(1)] = (m.group(2).strip(), m.group(3).strip())


_load_icon_symbols()


def render_icon(name: str, css_class: str = "", width=None, height=None, **kwargs) -> Markup:
    """Renders an inline SVG icon resolved from the canonical HVL icon sprite (zero-flash SSR)."""
    icon_id = name.lstrip("#")
    if not icon_id.startswith("icon-"):
        icon_id = f"icon-{icon_id}"

    classes = f"hvl-icon {css_class}".strip()
    size_attrs = (f' width="{width}"' if width is not None else "") + (f' height="{height}"' if height is not None else "")
    ver = kwargs.pop("version", None) or kwargs.pop("v", None)
    extra_attrs = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in kwargs.items())
    if extra_attrs:
        extra_attrs = " " + extra_attrs

    sym = _ICON_SYMBOLS.get(icon_id) or _ICON_SYMBOLS.get(name.lstrip("#"))
    if sym:
        sym_attrs, inner_svg = sym
        sym_attrs_str = f" {sym_attrs}" if sym_attrs else ""
        return Markup(f'<svg class="{classes}" aria-hidden="true"{size_attrs}{sym_attrs_str}{extra_attrs}>{inner_svg}</svg>')

    if not ver:
        from flask import current_app, g, has_app_context

        ver = ""
        if has_app_context():
            cfg = current_app.config
            ver = getattr(g, "asset_version", None) or cfg.get("ASSET_VERSION") or cfg.get("APP_VERSION") or ""
    q = f"?v={ver}" if ver else ""
    return Markup(f'<svg class="{classes}" aria-hidden="true"{size_attrs}{extra_attrs}><use href="/common/icons.svg{q}#{icon_id}"></use></svg>')


from hvl_common.ui.chat_markdown import render_chat_markdown  # noqa: E402
from hvl_common.ui.formatting import (  # noqa: E402
    fmt_currency,
    fmt_short_currency,
    fmt_pct,
)


def hvl_theme_init_script() -> Markup:
    """Emit zero-FOUC color-scheme meta and inline script applying saved/OS theme and minimum-scale=1.0 viewport floor."""
    return Markup(
        '<meta name="color-scheme" content="light dark">\n  '
        "<script>(function(){try{var ks=['hvl_theme'],s=null;"
        "for(var i=0;i<ks.length;i++){var v=localStorage.getItem(ks[i]);if(v==='light'||v==='dark'||v==='system'){s=v;break;}}"
        "var d=s==='dark'||((!s||s==='system')&&window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches);"
        "document.documentElement.setAttribute('data-theme',d?'dark':'light');"
        "var m=document.querySelector('meta[name=\"color-scheme\"]');if(m)m.content=(!s||s==='system')?'light dark':(d?'dark':'light');"
        "var vp=document.querySelector('meta[name=\"viewport\"]');"
        "if(vp&&vp.content&&vp.content.indexOf('minimum-scale')===-1)vp.content+=', minimum-scale=1.0';"
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
        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg></button>'
    )


def _resolve_active_css_scopes(
    scopes: str | Iterable[str] | None, *, subnav: bool, sidebar: bool, modal: bool, chat: bool, notifications: bool
) -> list[str]:
    if scopes is not None:
        return _parse_scope_names(scopes, HVL_CSS_SCOPES)
    flags = (("core", True), ("subnav", subnav), ("sidebar", sidebar), ("modal", modal), ("chat", chat), ("notifications", notifications))
    return [name for name, enabled in flags if enabled]


def _resolve_active_js_scopes(
    scopes: str | Iterable[str] | None, *, htmx: bool, subnav: bool, modal: bool, chat: bool, notifications: bool, toast: bool, signals: bool
) -> list[str]:
    if scopes is not None:
        return _parse_scope_names(scopes, HVL_JS_SCOPES)
    flags = (("htmx", htmx), ("subnav", subnav), ("core", True), ("modal", modal), ("chat", chat), ("notifications", notifications), ("toast", toast), ("signals", signals))
    return [name for name, enabled in flags if enabled]


def hvl_common_styles(
    version: str = "",
    *,
    scopes: str | Iterable[str] | None = None,
    subnav: bool = True,
    sidebar: bool = True,
    modal: bool = True,
    chat: bool = True,
    notifications: bool = True,
    theme_init: bool = True,
    bundle: bool = False,
) -> Markup:
    """Emit canonical HVL shared stylesheet links in deterministic order (with optional FOUC theme init)."""
    tags: list[str] = [str(hvl_theme_init_script())] if theme_init else []
    if bundle:
        active_scopes = _resolve_active_css_scopes(
            scopes, subnav=subnav, sidebar=sidebar, modal=modal, chat=chat, notifications=notifications
        )
        q = f"?scopes={escape(','.join(active_scopes))}" + (f"&v={escape(version)}" if version else "")
        tags.append(f'<link rel="stylesheet" href="/common/bundle.css{q}">')
        return Markup("\n  ".join(tags))

    q = f"?v={escape(version)}" if version else ""
    files = resolve_hvl_css_files(scopes, subnav=subnav, sidebar=sidebar, modal=modal, chat=chat, notifications=notifications)
    tags.extend(f'<link rel="stylesheet" href="/common/{f}{q}">' for f in files)
    return Markup("\n  ".join(tags))


def hvl_common_scripts(
    version: str = "",
    *,
    scopes: str | Iterable[str] | None = None,
    htmx: bool = True,
    subnav: bool = True,
    modal: bool = True,
    chat: bool = True,
    notifications: bool = True,
    toast: bool = True,
    signals: bool = False,
    defer: bool = False,
    bundle: bool = False,
) -> Markup:
    """Emit canonical HVL shared script tags (including marked.min.js before chat-drawer.js)."""
    d_attr = " defer" if defer else ""
    tags: list[str] = []
    if version:
        tags.append(f'<script>window.__APP_VERSION__ = window.__APP_VERSION__ || "{escape(version)}";</script>')
    if bundle:
        active_scopes = _resolve_active_js_scopes(
            scopes, htmx=htmx, subnav=subnav, modal=modal, chat=chat, notifications=notifications, toast=toast, signals=signals
        )
        q = f"?scopes={escape(','.join(active_scopes))}" + (f"&v={escape(version)}" if version else "")
        tags.append(f'<script src="/common/bundle.js{q}"{d_attr}></script>')
        return Markup("\n  ".join(tags))

    q = f"?v={escape(version)}" if version else ""
    files = resolve_hvl_js_files(scopes, htmx=htmx, subnav=subnav, modal=modal, chat=chat, notifications=notifications, toast=toast, signals=signals)
    tags.extend(f'<script src="/common/{f}{q}"{d_attr}></script>' for f in files)
    return Markup("\n  ".join(tags))


@ui_bp.route("/common/components.css")
def serve_components_css() -> Response:
    """Serves concatenated component CSS modules (or raw components.css when ?raw=1 is passed)."""
    if request.args.get("raw") == "1":
        return send_from_directory(str(STATIC_DIR), "components.css", mimetype="text/css")
    component_files = ("components.css", "cards.css", "forms.css", "subnav.css", "sidebar.css", "settings-modal.css")
    chunks = [(STATIC_DIR / fname).read_text(encoding="utf-8") for fname in component_files if (STATIC_DIR / fname).is_file()]
    return Response("\n".join(chunks), mimetype="text/css")


@ui_bp.route("/common/bundle.css")
def serve_bundle_css() -> Response:
    """Serves dynamically concatenated HVL shared CSS for requested ?scopes=..."""
    raw_scopes = request.args.get("scopes")
    files = resolve_hvl_css_files(raw_scopes if raw_scopes else None)
    chunks = [
        f"/* --- Source: {fname} --- */\n" + (STATIC_DIR / fname).read_text(encoding="utf-8")
        for fname in files
        if (STATIC_DIR / fname).is_file()
    ]
    return Response("\n".join(chunks), mimetype="text/css")


@ui_bp.route("/common/bundle.js")
def serve_bundle_js() -> Response:
    """Serves dynamically concatenated HVL shared JS for requested ?scopes=..."""
    raw_scopes = request.args.get("scopes")
    files = resolve_hvl_js_files(raw_scopes if raw_scopes else None)
    chunks = [
        f"/* --- Source: {fname} --- */\n;\n" + (STATIC_DIR / fname).read_text(encoding="utf-8") + "\n;\n"
        for fname in files
        if (STATIC_DIR / fname).is_file()
    ]
    return Response("".join(chunks), mimetype="application/javascript")


from hvl_common.ui.cards import hvl_card_header, hvl_icon_btn, hvl_subcard  # noqa: E402
from hvl_common.ui.notifications import (  # noqa: E402
    hvl_notification_bell,
    hvl_notification_drawer,
    render_notifications_drawer_items,
)
from hvl_common.ui.settings import (  # noqa: E402
    hvl_ai_quota_card,
    hvl_household_name_card,
    hvl_settings_appearance_pane,
    hvl_settings_header,
    hvl_settings_subnav,
    hvl_subnav_bar,
    hvl_support_access_card,
    hvl_theme_choice_cards,
    hvl_user_badge,
)
from hvl_common.ui.settings_integrations import (  # noqa: E402
    hvl_push_notifications_card,
    hvl_siri_shortcuts_card,
)

for _fn_name, _fn in (
    ("render_icon", render_icon),
    ("icon", render_icon),
    ("hvl_common_styles", hvl_common_styles),
    ("hvl_common_scripts", hvl_common_scripts),
    ("hvl_theme_init_script", hvl_theme_init_script),
    ("hvl_theme_toggle_btn", hvl_theme_toggle_btn),
    ("hvl_icon_btn", hvl_icon_btn),
    ("hvl_card_header", hvl_card_header),
    ("hvl_subcard", hvl_subcard),
    ("hvl_theme_choice_cards", hvl_theme_choice_cards),
    ("hvl_user_badge", hvl_user_badge),
    ("hvl_notification_bell", hvl_notification_bell),
    ("hvl_notification_drawer", hvl_notification_drawer),
    ("render_notifications_drawer_items", render_notifications_drawer_items),
    ("hvl_subnav_bar", hvl_subnav_bar),
    ("hvl_settings_subnav", hvl_settings_subnav),
    ("hvl_settings_header", hvl_settings_header),
    ("hvl_settings_appearance_pane", hvl_settings_appearance_pane),
    ("hvl_household_name_card", hvl_household_name_card),
    ("hvl_support_access_card", hvl_support_access_card),
    ("hvl_ai_quota_card", hvl_ai_quota_card),
    ("hvl_push_notifications_card", hvl_push_notifications_card),
    ("hvl_siri_shortcuts_card", hvl_siri_shortcuts_card),
    ("chat_markdown", render_chat_markdown),
    ("fmt_currency", fmt_currency),
    ("fmt_short_currency", fmt_short_currency),
    ("fmt_pct", fmt_pct),
):
    ui_bp.add_app_template_global(_fn, _fn_name)

for _filter_name, _filter_fn in (
    ("chat_markdown", render_chat_markdown),
    ("fmt_currency", fmt_currency),
    ("format_currency", fmt_currency),
    ("fmt_short_currency", fmt_short_currency),
    ("format_short_currency", fmt_short_currency),
    ("fmt_pct", fmt_pct),
    ("format_pct", fmt_pct),
):
    ui_bp.add_app_template_filter(_filter_fn, _filter_name)
