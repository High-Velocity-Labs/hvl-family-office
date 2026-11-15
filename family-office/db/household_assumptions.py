"""
db/household_assumptions.py: The household's planning assumptions, one encrypted row per section
(`household_assumption_sections`: `estate_planning`, `investment_policy`, `pension`, `mortgage`, `social_security`,
`annual_spend`, ...). A save writes only its own section, whole, so two saves of different sections never overwrite
each other. Reads go through `db.store` (L1 `TwoTierCache`, stamped with the table's domains).

The sections used to live in `household_profile.assumptions_json`, one plain-text JSON object rewritten on every save.
`move_legacy_assumptions` moves what is still there into rows the first time a process opens the database
(`security.init_db`). A household whose vault is locked then is skipped; its sections move on its first read or save
of them, which holds the household key (`_move_legacy_household`).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from hvl_common.db import get_db_connection
from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.models import HouseholdAssumptionSection
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)

R = TypeVar("R")


def _read_all_sections(family_id: int, path: Path) -> Dict[str, Any]:
    legacy = _move_legacy_household(path, family_id)
    with get_orm_session(path, family_id=family_id) as session:
        rows = session.execute(
            select(HouseholdAssumptionSection.section_key, HouseholdAssumptionSection.value_enc).where(
                HouseholdAssumptionSection.family_id == family_id
            )
        ).all()
    # Rows win; the legacy sections only show through when moving them failed.
    return {**legacy, **{str(key): value for key, value in rows}}


def get_assumptions(family_id: int = 0, db_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Every stored section as `{section_key: value}`, a copy the caller may change ({} for no household)."""
    if not family_id or family_id <= 0:
        return {}
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return {}
    from db import store as db_store

    return db_store.get_or_load_entity(
        family_id, "household_assumptions", lambda p: _read_all_sections(family_id, p), db_path=path, clone=True
    )


def get_section(family_id: int = 0, section_key: str = "", db_path: Optional[Union[str, Path]] = None) -> Any:
    """The stored value of one section, or None when it was never saved."""
    return get_assumptions(family_id=family_id, db_path=db_path).get(section_key)


def get_dict_section(
    family_id: int = 0, section_key: str = "", db_path: Optional[Union[str, Path]] = None
) -> Dict[str, Any]:
    """One section that holds an object; {} when it was never saved or holds something else."""
    value = get_section(family_id=family_id, section_key=section_key, db_path=db_path)
    return value if isinstance(value, dict) else {}


def _upsert(session: Session, family_id: int, section_key: str, value: Any) -> None:
    stmt = sqlite_insert(HouseholdAssumptionSection).values(
        family_id=family_id, section_key=section_key, value_enc=value
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["family_id", "section_key"],
            set_={"value_enc": stmt.excluded.value_enc, "updated_at": text("CURRENT_TIMESTAMP")},
        )
    )


def set_section(
    family_id: int = 0, section_key: str = "", value: Any = None, db_path: Optional[Union[str, Path]] = None
) -> None:
    """Replaces one section with `value`, leaving every other section as it is."""
    if not family_id or not section_key:
        return
    path = resolve_db_path(db_path, family_id=family_id)
    _move_legacy_household(path, family_id)

    def _write() -> Any:
        with get_orm_session(path, family_id=family_id, commit=True) as session:
            _upsert(session, family_id, section_key, value)
            return _stored_value(session, family_id, section_key)

    _write_section(family_id, path, section_key, _write)


def merge_dict_section(
    family_id: int = 0,
    section_key: str = "",
    updates: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Merges `updates` into an object section in one transaction and returns the merged section."""
    if not family_id or not section_key:
        return dict(updates or {})
    path = resolve_db_path(db_path, family_id=family_id)
    _move_legacy_household(path, family_id)

    def _write() -> tuple:
        with get_orm_session(path, family_id=family_id, commit=True) as session:
            current = _stored_value(session, family_id, section_key)
            merged = {**(current if isinstance(current, dict) else {}), **(updates or {})}
            _upsert(session, family_id, section_key, merged)
            return merged, _stored_value(session, family_id, section_key)

    merged, _stored = _write_section(family_id, path, section_key, _write, lambda result: result[1])
    return merged


def _stored_value(session: Session, family_id: int, section_key: str) -> Any:
    """The section's value as a read decrypts it (None when it is not stored)."""
    return session.scalar(
        select(HouseholdAssumptionSection.value_enc).where(
            HouseholdAssumptionSection.family_id == family_id,
            HouseholdAssumptionSection.section_key == section_key,
        )
    )


def _write_section(
    family_id: int, path: Path, section_key: str, write_fn: Callable[[], R], stored: Callable[[R], Any] = lambda r: r
) -> R:
    """Runs `write_fn` (one section's save, returning what `stored` turns into the section as read back inside it)
    and sets that section in the kept sections."""
    from db import store as db_store

    def _patch(kept: Dict[str, Any], result: R) -> Dict[str, Any]:
        return {**kept, section_key: stored(result)}

    return db_store.write_through(
        family_id, path, ("household_assumption_sections",), write_fn, {"household_assumptions": _patch}
    )


def _legacy_rows(db_path: Path, family_id: int = 0) -> list[tuple[int, Dict[str, Any]]]:
    """`(family_id, sections)` of each household (or only `family_id`) whose `assumptions_json` still holds sections."""
    out: list[tuple[int, Dict[str, Any]]] = []
    with get_db_connection(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(household_profile)").fetchall()}
        if "assumptions_json" not in cols:
            return out
        if family_id > 0:
            rows = conn.execute(
                "SELECT family_id, assumptions_json FROM household_profile WHERE family_id = ? "
                "AND assumptions_json IS NOT NULL AND assumptions_json NOT IN ('', '{}')",
                (family_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT family_id, assumptions_json FROM household_profile "
                "WHERE assumptions_json IS NOT NULL AND assumptions_json NOT IN ('', '{}')"
            ).fetchall()
    for fid, raw in rows:
        try:
            parsed = json.loads(raw)
        except ValueError:
            logger.warning("household_profile.assumptions_json of household %s is not valid JSON; dropping it", fid)
            parsed = {}
        out.append((int(fid), parsed if isinstance(parsed, dict) else {}))
    return out


def _move_household(db_path: Path, family_id: int, sections: Dict[str, Any]) -> int:
    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        for key, value in sections.items():
            # A section already saved as a row is newer than the legacy copy of it.
            stmt = sqlite_insert(HouseholdAssumptionSection).values(
                family_id=family_id, section_key=str(key), value_enc=value
            )
            session.execute(stmt.on_conflict_do_nothing(index_elements=["family_id", "section_key"]))
        session.execute(
            text("UPDATE household_profile SET assumptions_json = NULL WHERE family_id = :fid"), {"fid": family_id}
        )
    return len(sections)


def _move_legacy_household(path: Path, family_id: int) -> Dict[str, Any]:
    """
    Moves one household's legacy sections into rows before a read or save of them, and returns what was there ({}
    when nothing was). Needs the household key (a locked vault raises PermissionError, as reading the rows would).
    """
    if not path.exists():
        return {}
    legacy = dict(_legacy_rows(path, family_id)).get(family_id, {})
    if legacy:
        try:
            _move_household(path, family_id, legacy)
        except (sqlite3.Error, SQLAlchemyError):
            # The caller still sees the legacy sections (under any saved row); the next read retries the move.
            logger.exception("Moving the assumptions of household %s to encrypted rows failed", family_id)
    return legacy


def move_legacy_assumptions(db_path: Union[str, Path]) -> int:
    """Moves every household's `assumptions_json` sections into encrypted rows; returns the sections moved."""
    path = Path(db_path)
    if not path.exists():
        return 0
    total = 0
    for family_id, sections in _legacy_rows(path):
        if family_id <= 0:
            continue
        try:
            total += _move_household(path, family_id, sections)
        except PermissionError:
            logger.info(
                "Household %s vault is locked; its assumptions move to encrypted rows on its first read", family_id
            )
        except (sqlite3.Error, SQLAlchemyError):
            # Opening the database must not fail on this; the legacy column stays readable and the next start retries.
            logger.exception("Moving the assumptions of household %s to encrypted rows failed", family_id)
    if total:
        logger.info("Moved %d household assumption sections to encrypted rows in %s", total, path.name)
    return total
