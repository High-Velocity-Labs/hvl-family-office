"""
db/benefit_inputs.py: Per-person Social Security inputs, stored in the `social_security` key of
`household_profile.assumptions_json`.
The user-entered annual PIA (benefit at full retirement age, today's dollars, from the person's SSA statement)
overrides the earnings-based estimate in the forecast.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Union

from db.families import update_household_assumptions_key
from db.household import get_household_profile

SECTION_KEY = "social_security"
PERSONS = ("primary", "spouse")


def get_social_security_pia_overrides(
    family_id: int = 0, db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, float]:
    """Entered annual PIA by person ("primary"/"spouse"); absent persons have no override."""
    prof = get_household_profile(family_id=family_id, db_path=db_path)
    if not prof or not prof.get("assumptions_json"):
        return {}
    try:
        section = (json.loads(prof["assumptions_json"]) or {}).get(SECTION_KEY) or {}
    except (ValueError, TypeError):
        return {}
    return {p: float(section[f"{p}_annual_pia"]) for p in PERSONS if section.get(f"{p}_annual_pia") is not None}


def set_social_security_pia_override(
    family_id: int, person: str, annual_pia: Optional[float], db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Saves (or clears with None) one person's annual PIA override."""
    if person not in PERSONS:
        raise ValueError(f"person must be one of {PERSONS}")
    if annual_pia is not None and annual_pia < 0:
        raise ValueError("annual_pia must not be negative")
    current = get_social_security_pia_overrides(family_id=family_id, db_path=db_path)
    if annual_pia is None:
        current.pop(person, None)
    else:
        current[person] = float(annual_pia)
    update_household_assumptions_key(
        family_id=family_id, section_key=SECTION_KEY,
        section_value={f"{p}_annual_pia": v for p, v in current.items()}, db_path=db_path,
    )
