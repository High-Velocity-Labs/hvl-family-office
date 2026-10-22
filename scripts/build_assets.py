"""
scripts/build_assets.py: High-performance asset compilation and bundling pipeline.
Concatenates modular source files from static/js/ and static/css/ into static/dist/
without modifying any source files.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
COMMON_DIR = BASE_DIR / "vendor" / "hvl_common" / "ui" / "static"
DIST_DIR = STATIC_DIR / "dist"

CSS_SOURCES = [
    COMMON_DIR / "theme.css",
    COMMON_DIR / "components.css",
    STATIC_DIR / "css" / "theme_layout.css",
    STATIC_DIR / "css" / "theme_utilities.css",
    STATIC_DIR / "css" / "theme.css",
    STATIC_DIR / "css" / "components.css",
    COMMON_DIR / "modal-dialog.css",
    COMMON_DIR / "chat-drawer.css",
    STATIC_DIR / "css" / "ai_advisor.css",
    STATIC_DIR / "css" / "guide.css",
]

JS_CORE_SOURCES = [
    COMMON_DIR / "chart.umd.min.js",
    COMMON_DIR / "utils.js",
    COMMON_DIR / "toast.js",
    STATIC_DIR / "js" / "chart_theme.js",
    COMMON_DIR / "modal-dialog.js",
    STATIC_DIR / "js" / "sandbox_ui.js",
    STATIC_DIR / "js" / "app_sync.js",
    STATIC_DIR / "js" / "app_navigation.js",
    STATIC_DIR / "js" / "app_hydration.js",
    STATIC_DIR / "js" / "app.js",
    STATIC_DIR / "js" / "telemetry.js",
]

JS_MODULE_SOURCES = [
    STATIC_DIR / "js" / "overview_charts.js",
    STATIC_DIR / "js" / "overview.js",
    STATIC_DIR / "js" / "widget_charts.js",
    STATIC_DIR / "js" / "holdings.js",
    STATIC_DIR / "js" / "equity_chart_helpers.js",
    STATIC_DIR / "js" / "equity_chart.js",
    STATIC_DIR / "js" / "equity_simulator.js",
    STATIC_DIR / "js" / "equity_modals.js",
    STATIC_DIR / "js" / "equity.js",
    STATIC_DIR / "js" / "arbitrage.js",
    STATIC_DIR / "js" / "philanthropy_modals.js",
    STATIC_DIR / "js" / "philanthropy.js",
    STATIC_DIR / "js" / "gifting.js",
    STATIC_DIR / "js" / "estate.js",
    STATIC_DIR / "js" / "college.js",
    STATIC_DIR / "js" / "compensation_modals.js",
    STATIC_DIR / "js" / "compensation.js",
    STATIC_DIR / "js" / "accounts.js",
    STATIC_DIR / "js" / "settings_accounts.js",
    STATIC_DIR / "js" / "settings_members.js",
    STATIC_DIR / "js" / "settings_integrations.js",
    STATIC_DIR / "js" / "settings_security.js",
    STATIC_DIR / "js" / "settings_admin.js",
    STATIC_DIR / "js" / "settings.js",
    STATIC_DIR / "js" / "onboarding_steps.js",
    STATIC_DIR / "js" / "onboarding.js",
    STATIC_DIR / "js" / "guide.js",
    STATIC_DIR / "js" / "bug_reporter.js",
    COMMON_DIR / "marked.min.js",
    COMMON_DIR / "chat-drawer.js",
    STATIC_DIR / "js" / "ai_advisor_ui.js",
    STATIC_DIR / "js" / "ai_advisor_threads.js",
    STATIC_DIR / "js" / "ai_advisor_chat.js",
    STATIC_DIR / "js" / "ai_advisor.js",
]


def bundle_css() -> Path:
    out_file = DIST_DIR / "bundle.css"
    parts: list[str] = [f"/* HVL Family Office Consolidated CSS Bundle */\n"]
    for src in CSS_SOURCES:
        if not src.exists():
            raise FileNotFoundError(f"Missing CSS source: {src}")
        content = src.read_text(encoding="utf-8")
        parts.append(f"\n/* --- Source: {src.name} --- */\n")
        parts.append(content)
    out_file.write_text("\n".join(parts), encoding="utf-8")
    return out_file


def bundle_js(name: str, sources: list[Path]) -> Path:
    out_file = DIST_DIR / f"{name}.js"
    parts: list[str] = [f"/* HVL Family Office Consolidated Bundle: {name} */\n"]
    for src in sources:
        if not src.exists():
            raise FileNotFoundError(f"Missing JS source: {src}")
        content = src.read_text(encoding="utf-8")
        parts.append(f"\n/* --- Source: {src.name} --- */\n;\n")
        parts.append(content)
        parts.append("\n;\n")
    out_file.write_text("".join(parts), encoding="utf-8")
    return out_file


def build_all() -> dict[str, int]:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    css_path = bundle_css()
    core_path = bundle_js("bundle-core", JS_CORE_SOURCES)
    mod_path = bundle_js("bundle-modules", JS_MODULE_SOURCES)
    return {
        str(css_path.name): css_path.stat().st_size,
        str(core_path.name): core_path.stat().st_size,
        str(mod_path.name): mod_path.stat().st_size,
    }


if __name__ == "__main__":
    stats = build_all()
    print("[OK] Assets bundled successfully:")
    for name, size in stats.items():
        print(f"  - {name}: {size:,} bytes ({round(size / 1024, 1)} KB)")
