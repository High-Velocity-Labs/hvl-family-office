"""
db/engine_inputs.py: Household forecast inputs stored as assumption sections (`db.household_assumptions`).
`pension` holds each adult's defined-benefit pension; `mortgage` holds the starting mortgage's remaining term and,
when the balance sheet reports none, its rate. The planning meaning of every field lives in forecast/pension.py and
forecast/mortgage_amortization.py; this module only validates and stores.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

from db.benefit_inputs import PERSONS
from db.household_assumptions import get_dict_section, set_section

PENSION_KEY = "pension"
MORTGAGE_KEY = "mortgage"
PENSION_FIELDS = ("annual_amount", "start_age", "cola", "survivor_pct")


def _section(family_id: int, key: str, db_path: Optional[Union[str, Path]]) -> Dict[str, Any]:
    return get_dict_section(family_id=family_id, section_key=key, db_path=db_path)


def get_pension_inputs(
    family_id: int = 0, db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, float]]:
    """Entered pensions by person ("primary"/"spouse"): annual_amount, start_age, cola, survivor_pct (decimals)."""
    section = _section(family_id, PENSION_KEY, db_path)
    return {p: dict(section[p]) for p in PERSONS if isinstance(section.get(p), dict)}


def set_pension_input(
    family_id: int, person: str, pension: Optional[Dict[str, float]], db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Saves one person's pension, or clears it with None. Annual dollars in today's money; rates are decimals."""
    if person not in PERSONS:
        raise ValueError(f"person must be one of {PERSONS}")
    current = get_pension_inputs(family_id=family_id, db_path=db_path)
    if pension is None:
        current.pop(person, None)
    else:
        missing = [f for f in PENSION_FIELDS if pension.get(f) is None]
        if missing:
            raise ValueError(f"pension is missing {', '.join(missing)}")
        from forecast.pension import Pension

        current[person] = {f: float(pension[f]) for f in PENSION_FIELDS}
        Pension(**current[person])  # validates ranges
    set_section(family_id=family_id, section_key=PENSION_KEY, value=current, db_path=db_path)


def get_mortgage_inputs(family_id: int = 0, db_path: Optional[Union[str, Path]] = None) -> Dict[str, float]:
    """Entered `remaining_term_years` and `annual_rate` (decimal) of the starting mortgage; absent keys are unknown."""
    section = _section(family_id, MORTGAGE_KEY, db_path)
    return {k: float(section[k]) for k in ("remaining_term_years", "annual_rate") if section.get(k) is not None}


def set_mortgage_inputs(
    family_id: int, remaining_term_years: Optional[float], annual_rate: Optional[float],
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Saves the starting mortgage's remaining term and rate; None clears that field."""
    if remaining_term_years is not None and not 0 < remaining_term_years <= 50:
        raise ValueError("remaining mortgage term must be between 0 and 50 years")
    if annual_rate is not None and not 0 <= annual_rate <= 0.25:
        raise ValueError("mortgage rate must be between 0% and 25%")
    value = {
        k: float(v) for k, v in (("remaining_term_years", remaining_term_years), ("annual_rate", annual_rate))
        if v is not None
    }
    set_section(family_id=family_id, section_key=MORTGAGE_KEY, value=value, db_path=db_path)
