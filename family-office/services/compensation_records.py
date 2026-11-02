"""
Compensation history loader: relational compensation rows joined to household adults.
Pure service layer; callers (routes, SSR view-models) pass the database path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import db
import security
from services import equity_engine


def load_compensation_adults(family_id: int, db_path: Path) -> tuple[list[dict], dict[Any, str]]:
    adults: list[dict] = [{"user_id": None, "name": "Combined Household", "relationship": "combined"}]
    user_id_to_name: dict[Any, str] = {}
    if db_path.exists():
        for m in security.get_family_members(db_path, family_id=family_id):
            rel = str(m.get("relationship") or "").lower()
            if rel in ("primary", "spouse", "relative", "parent", "adult"):
                uid = m.get("user_id")
                name = m.get("name") or f"Member #{uid}"
                user_id_to_name[uid] = name
                adults.append({"user_id": uid, "name": name, "relationship": rel})
    if len(adults) == 1 and db_path.exists():
        tdata = db.transcripts.get_transcripts_payload(family_id=family_id, db_path=db_path) or {}
        next_uid = 1
        for ta in tdata.get("adults", []):
            if ta != "Combined Household" and not any(a.get("name") == ta for a in adults):
                adults.append({"user_id": next_uid, "name": ta, "relationship": "adult"})
                next_uid += 1
    return adults, user_id_to_name


def load_compensation_records(family_id: int, db_path: Path, user_id: Optional[int] = None):
    """Loads compensation history from SQLite table or falls back to encrypted store."""
    history = []
    primary_comp = equity_engine.get_primary_company_name(family_id=family_id)
    adults, user_id_to_name = load_compensation_adults(family_id, db_path)

    if db_path.exists():
        records = db.compensation.list_compensation_records(family_id=family_id, user_id=user_id, db_path=db_path)
        for r in records:
            uid = r["user_id"]
            r["taxpayer"] = user_id_to_name.get(uid, f"Member #{uid}")
            history.append(r)

    primary_years = [
        int(h["year"]) for h in history
        if primary_comp and primary_comp.lower() in str(h.get("company", "")).lower()
    ]
    return history, primary_years, primary_comp, adults
