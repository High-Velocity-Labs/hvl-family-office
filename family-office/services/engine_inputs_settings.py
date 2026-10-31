"""
services/engine_inputs_settings.py: Settings form fields for the forecast's pension and mortgage inputs.
Form units: dollars per year, ages in years, percentages as 0-100. Storage units (db/engine_inputs.py): decimals.
A blank or null field clears that input; a key absent from the request leaves it as saved.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from db import benefit_inputs, engine_inputs

PENSION_FORM_FIELDS = ("annual", "start_age", "cola_pct", "survivor_pct")


def _number(body: Dict[str, Any], key: str) -> Optional[float]:
    raw = body.get(key)
    return None if raw in (None, "") else float(raw)


def save_engine_inputs(family_id: int, body: Dict[str, Any], db_path: Any) -> None:
    """Saves the pension and mortgage fields present in `body`; raises ValueError on an out-of-range value."""
    for person in benefit_inputs.PERSONS:
        keys = {f: f"pension_{person}_{f}" for f in PENSION_FORM_FIELDS}
        if not any(k in body for k in keys.values()):
            continue
        annual = _number(body, keys["annual"])
        if not annual:
            engine_inputs.set_pension_input(family_id, person, None, db_path=db_path)
            continue
        start_age = _number(body, keys["start_age"])
        if start_age is None:
            raise ValueError("Enter the age the pension starts.")
        engine_inputs.set_pension_input(family_id, person, {
            "annual_amount": annual, "start_age": start_age,
            "cola": (_number(body, keys["cola_pct"]) or 0.0) / 100.0,
            "survivor_pct": (_number(body, keys["survivor_pct"]) or 0.0) / 100.0,
        }, db_path=db_path)
    if "mortgage_remaining_years" in body or "mortgage_rate_pct" in body:
        saved = engine_inputs.get_mortgage_inputs(family_id=family_id, db_path=db_path)
        term = _number(body, "mortgage_remaining_years") if "mortgage_remaining_years" in body else saved.get(
            "remaining_term_years")
        if "mortgage_rate_pct" in body:
            rate_pct = _number(body, "mortgage_rate_pct")
            rate = None if rate_pct is None else rate_pct / 100.0
        else:
            rate = saved.get("annual_rate")
        engine_inputs.set_mortgage_inputs(family_id, term, rate, db_path=db_path)
