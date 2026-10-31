"""
forecast/dollar_basis.py: Names the dollars a schedule's amounts are expressed in.

Schedule rows are in the saved view's dollars: "real" view shows today's dollars, any other view
shows nominal (future) dollars (forecast/waterfall.py). Anything that hands such an amount to a
reader who cannot see the toggle (the advisor, an exported report) states this label with it.
Each schedule row's `to_todays_dollars` converts that row to today's dollars in either view.
"""

from __future__ import annotations
from typing import Any, Dict

DOLLAR_BASIS_TODAYS = "todays_dollars"
DOLLAR_BASIS_FUTURE = "future_dollars"

DOLLAR_BASIS_LABELS: Dict[str, str] = {
    DOLLAR_BASIS_TODAYS: "today's dollars",
    DOLLAR_BASIS_FUTURE: "future dollars",
}


def dollar_basis_for_view(view_mode: Any) -> str:
    """The dollar basis of a schedule built in `view_mode` (the waterfall deflates only for "real")."""
    return DOLLAR_BASIS_TODAYS if view_mode == "real" else DOLLAR_BASIS_FUTURE


def dollar_basis_label(basis: str) -> str:
    return DOLLAR_BASIS_LABELS[basis]
