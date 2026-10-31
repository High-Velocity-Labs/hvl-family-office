"""
services/household_income.py: The household's ordinary earned income from its compensation records.
Each earner counts once, at their latest year on file (all of that year's employers); the household's income is the
sum over earners. A household with no records has 0.0, not an assumed income.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def household_income_from_records(rows: List[Dict[str, Any]]) -> float:
    """Sum over earners of salary plus bonus in each earner's latest year."""
    latest: Dict[Any, int] = {}
    for r in rows:
        key = r.get("user_id")
        latest[key] = max(latest.get(key, 0), int(r.get("year") or 0))
    return max(0.0, sum(
        float(r.get("salary") or 0.0) + float(r.get("bonus") or 0.0)
        for r in rows if int(r.get("year") or 0) == latest[r.get("user_id")]
    ))


def household_prior_income(family_id: int, db_path: Optional[Union[str, Path]] = None) -> float:
    """The household's current annual salary and bonus (0.0 without a family or records)."""
    if not family_id:
        return 0.0
    import db

    rows = db.compensation.list_compensation_records(family_id=family_id, db_path=db_path)
    return household_income_from_records(rows)
