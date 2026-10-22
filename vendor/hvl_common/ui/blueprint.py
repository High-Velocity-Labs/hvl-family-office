import re
import sys
from pathlib import Path
from flask import Blueprint, send_from_directory
from markupsafe import Markup


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

    return Markup(
        f'<svg class="{classes}" aria-hidden="true"{size_attrs}{extra_attrs}>'
        f'<use href="/common/icons.svg#{icon_id}"></use>'
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


def hvl_common_styles(
    version: str = "",
    *,
    modal: bool = True,
    chat: bool = True,
) -> Markup:
    """Emit canonical HVL shared stylesheet links in deterministic order."""
    q = f"?v={version}" if version else ""
    files = ["theme.css", "components.css"]
    if modal:
        files.append("modal-dialog.css")
    if chat:
        files.append("chat-drawer.css")
    tags = [f'<link rel="stylesheet" href="/common/{f}{q}">' for f in files]
    return Markup("\n  ".join(tags))


def hvl_common_scripts(
    version: str = "",
    *,
    htmx: bool = True,
    modal: bool = True,
    chat: bool = True,
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
    files.append("utils.js")
    if modal:
        files.append("modal-dialog.js")
    if chat:
        files.append("chat-drawer.js")
    if toast:
        files.append("toast.js")
    tags = [f'<script src="/common/{f}{q}"{d_attr}></script>' for f in files]
    return Markup("\n  ".join(tags))


@ui_bp.app_template_global("hvl_common_styles")
def _app_hvl_common_styles(version: str = "", **kwargs) -> Markup:
    return hvl_common_styles(version, **kwargs)


@ui_bp.app_template_global("hvl_common_scripts")
def _app_hvl_common_scripts(version: str = "", **kwargs) -> Markup:
    return hvl_common_scripts(version, **kwargs)


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
