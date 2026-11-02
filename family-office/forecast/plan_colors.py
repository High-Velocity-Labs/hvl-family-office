"""
forecast/plan_colors.py: Stored Plan Color Palette & Legacy Hex Normalization.
Plan colors are stored user data (hex strings saved by the plan editor and drawn by canvas charts).
Consolidates all Velvet Gemstone plan-color definitions and legacy database color aliases.
"""

from __future__ import annotations

from typing import Any

PLAN_COLORS: dict[str, str] = {
    "sapphire": "#1D4ED8",
    "emerald": "#059669",
    "cerulean": "#0284C7",
    "amber": "#D97706",
    "teal": "#0D9488",
    "rose": "#C75D6E",
    "slate": "#64748B",
    "slate_light": "#94A3B8",
}

COLOR_PALETTE: tuple[str, ...] = tuple(
    PLAN_COLORS[name]
    for name in ("sapphire", "emerald", "cerulean", "amber", "teal", "rose", "slate")
)

DEFAULT_PLAN_COLOR: str = PLAN_COLORS["sapphire"]

_LEGACY_COLOR_ALIASES: dict[str, str] = {
    "#3B82F6": PLAN_COLORS["sapphire"],
    "#2563EB": PLAN_COLORS["sapphire"],
    "#0265E8": PLAN_COLORS["sapphire"],
    "#10B981": PLAN_COLORS["emerald"],
    "#22C55E": PLAN_COLORS["emerald"],
    "#047857": PLAN_COLORS["emerald"],
    "#E11D48": PLAN_COLORS["emerald"],
    "#06B6D4": PLAN_COLORS["cerulean"],
    "#0EA5E9": PLAN_COLORS["cerulean"],
    "#38BDF8": PLAN_COLORS["cerulean"],
    "#7C3AED": PLAN_COLORS["cerulean"],
    "#8B5CF6": PLAN_COLORS["cerulean"],
    "#F59E0B": PLAN_COLORS["amber"],
    "#FB923C": PLAN_COLORS["amber"],
    "#FACC15": PLAN_COLORS["amber"],
    "#C06C26": PLAN_COLORS["amber"],
    "#F97316": PLAN_COLORS["amber"],
    "#A855F7": PLAN_COLORS["teal"],
    "#14B8A6": PLAN_COLORS["teal"],
    "#EC4899": PLAN_COLORS["teal"],
    "#EF4444": PLAN_COLORS["rose"],
    "#F43F5E": PLAN_COLORS["rose"],
    "#F472B6": PLAN_COLORS["rose"],
    "#DC2626": PLAN_COLORS["rose"],
}


def normalize_plan_color(color: str | None, fallback: str = DEFAULT_PLAN_COLOR) -> str:
    """Normalizes a plan hex color (mapping legacy hexes to Velvet Gemstone swatches)."""
    raw = str(color or "").strip().upper()
    if not raw:
        return fallback
    return _LEGACY_COLOR_ALIASES.get(raw, raw)


normalize_scenario_color = normalize_plan_color


def pick_distinct_color(scenarios: list[dict[str, Any]]) -> str:
    """Returns the first theme preset color not yet used by existing scenarios."""
    used_colors: set[str] = set()
    for s in scenarios or []:
        raw = str(s.get("color") or "").strip().upper()
        if raw:
            used_colors.add(_LEGACY_COLOR_ALIASES.get(raw, raw))
    for color in COLOR_PALETTE:
        if color not in used_colors:
            return color
    return COLOR_PALETTE[len(scenarios or []) % len(COLOR_PALETTE)]


pick_unused_scenario_color = pick_distinct_color
