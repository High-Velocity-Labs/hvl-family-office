"""
View-models for the static chrome around the forecasting charts (mode toggles, legend badges, captions).
These carry no plan data, only the selected sub-mode, so the browser asks for them instead of building markup.
"""

from __future__ import annotations

from typing import Any

CASHFLOW_MODES = (("sankey", "Single-Year Sankey"), ("timeline", "Timeline Bars"))
MONTE_CARLO_MODES = (("stochastic", "Stochastic (1,000 Trials)"), ("historical", "1928–2025 Backtest (98 Cohorts)"))

CASHFLOW_LEGEND = (
    ("Salary Savings", "rgba(5, 150, 105, 0.14)", "#059669"),
    ("Social Security", "rgba(13, 148, 136, 0.14)", "#0D9488"),
    ("Core Living", "rgba(29, 78, 216, 0.14)", "#1D4ED8"),
    ("Travel Go-Go", "rgba(217, 119, 6, 0.14)", "#D97706"),
    ("Family Gifting", "rgba(192, 108, 38, 0.14)", "#C06C26"),
    ("Event Spikes", "rgba(199, 93, 110, 0.15)", "#C75D6E"),
    ("Mortgage Debt", "rgba(2, 132, 199, 0.14)", "#0284C7"),
)

LONGEVITY_LEGEND = (
    (
        "badge-green",
        "Growing (Wealth > Starting)",
        "Trials where real net worth exceeds initial starting purchasing power",
    ),
    ("badge-orange", "Preserved (Wealth > $0)", "Trials where capital remains above $0 but below starting value"),
    ("badge-red", "Broke (Depleted $0)", "Trials where liquid portfolio depleted in adverse market sequences"),
    ("", "Both Deceased (SSA Joint Mortality)", "Actuarial probability both spouses have passed away"),
)

_TOGGLE_LENSES = {"cashflow": ("sankey", CASHFLOW_MODES), "montecarlo": ("stochastic", MONTE_CARLO_MODES)}


def _resolve_mode(lens: str, mode: str | None) -> str:
    default, modes = _TOGGLE_LENSES[lens]
    return mode if mode in dict(modes) else default


def build_chart_toggles(lens: str, mode: str | None) -> dict[str, Any] | None:
    """Returns the toggle-strip view-model for `lens`, or None for an unknown lens."""
    if lens == "longevity":
        return {"lens": lens, "legend": LONGEVITY_LEGEND}
    if lens not in _TOGGLE_LENSES:
        return None
    selected = _resolve_mode(lens, mode)
    ctx: dict[str, Any] = {"lens": lens, "mode": selected, "modes": _TOGGLE_LENSES[lens][1]}
    if lens == "cashflow" and selected == "timeline":
        ctx["legend"] = CASHFLOW_LEGEND
    return ctx


def build_chart_caption(lens: str, mode: str | None) -> dict[str, Any] | None:
    """Returns the caption view-model for the Monte Carlo lens, or None for lenses whose caption is plain text."""
    if lens != "montecarlo":
        return None
    return {"historical": _resolve_mode(lens, mode) == "historical"}
