"""
ssr/plan_year.py: The plan's "now" year for SSR builders.

The forecast stamps its first projection year on the simulation as `start_year`. SSR builders read
it from there so a page never disagrees with its own schedule about which year is the present.
"""

from __future__ import annotations
from datetime import date
from typing import Any, Dict


def plan_start_year(sim: Dict[str, Any]) -> int:
    """First projection year of `sim`; the current calendar year for a sim that predates the field."""
    raw = (sim or {}).get("start_year")
    return int(raw) if raw else date.today().year
