"""
One-time moves of values out of encrypted blobs into the columns and tables alembic 0008 added.

- `forecast_scenarios.spending_guardrail_mode` was a key inside the encrypted `payload_enc`; it moves to its own
  column and leaves the payload. A row with no mode there gets "inherit", so no NULL is left to look at again.
- `philanthropy_budgets` held the ledger's settings JSON in `budget_amount_enc` on a fake `tax_year = -1` row; it
  moves to `philanthropy_settings` and the row is deleted. Only the previous release writes that row, so where both
  exist (the two releases ran side by side during a deploy) it is the newer one and replaces the settings row.

Both sources are encrypted, so the move needs the household key. `backfill_columns` runs from `security.init_db`, so
a database is moved the first time a process opens it. A household whose vault is locked (Support Access off) is
skipped; the next process start tries again.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from hvl_common.db import get_db_connection
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from db.models import ForecastScenario, PhilanthropyBudget, PhilanthropySettings
from db.philanthropy import LEGACY_SETTINGS_YEAR, legacy_settings_meta
from db.scenarios import GUARDRAIL_INHERIT
from db.session import get_orm_session

logger = logging.getLogger(__name__)

_GUARDRAIL_KEY = "spending_guardrail_mode"
_GUARDRAIL_MODES = ("off", "moderate", "aggressive")


def _households_to_move(db_path: Path) -> list[int]:
    """Households with a scenario whose mode may still be in its payload, or a legacy philanthropy settings row."""
    with get_db_connection(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        # A global directory DB has neither domain table, so there is nothing to move.
        if not {"philanthropy_settings", "philanthropy_budgets", "forecast_scenarios"} <= tables:
            return []
        found = {
            int(r[0])
            for r in conn.execute(
                "SELECT DISTINCT family_id FROM philanthropy_budgets WHERE tax_year = ?", (LEGACY_SETTINGS_YEAR,)
            ).fetchall()
        }
        found.update(
            int(r[0])
            for r in conn.execute(
                "SELECT DISTINCT family_id FROM forecast_scenarios WHERE spending_guardrail_mode IS NULL"
            ).fetchall()
        )
    return sorted(fid for fid in found if fid > 0)


def _move_household(db_path: Path, family_id: int) -> int:
    moved = 0
    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        # Take the write lock before the first read: pysqlite would only begin at the first write, so a save another
        # process commits between this read and the flush would be overwritten with the older payload and settings.
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        scenarios = session.scalars(
            select(ForecastScenario).where(
                ForecastScenario.family_id == family_id, ForecastScenario.spending_guardrail_mode.is_(None)
            )
        ).all()
        for row in scenarios:
            payload = dict(row.payload_enc) if isinstance(row.payload_enc, dict) else {}
            mode = str(payload.pop(_GUARDRAIL_KEY, None) or "").lower().strip()
            row.spending_guardrail_mode = mode if mode in _GUARDRAIL_MODES else GUARDRAIL_INHERIT
            row.payload_enc = payload
            moved += 1

        legacy = session.get(PhilanthropyBudget, (family_id, LEGACY_SETTINGS_YEAR))
        if legacy is not None:
            meta = legacy_settings_meta(legacy.budget_amount_enc)
            session.merge(PhilanthropySettings(
                family_id=family_id,
                total_lifetime_charity_enc=float(meta.get("total_lifetime_charity") or 0.0),
                lifetime_history_enc=list(meta.get("lifetime_history") or []),
                year_totals_enc=dict(meta.get("year_totals") or {}),
            ))
            session.execute(
                delete(PhilanthropyBudget).where(
                    PhilanthropyBudget.family_id == family_id, PhilanthropyBudget.tax_year == LEGACY_SETTINGS_YEAR
                )
            )
            moved += 1
    return moved


def backfill_columns(db_path: Path) -> int:
    """Moves every legacy guardrail mode and philanthropy settings row of `db_path`; returns the rows moved."""
    path = Path(db_path)
    if not path.exists():
        return 0
    total = 0
    for family_id in _households_to_move(path):
        try:
            total += _move_household(path, family_id)
        except PermissionError:
            logger.info("Household %s vault is locked; its rows move once it unlocks", family_id)
        except (sqlite3.Error, SQLAlchemyError, ValueError):
            # A failed move (a busy database, a row that will not decrypt) must not fail opening the database; the old
            # values still read and the next start retries.
            logger.exception("Moving guardrail and philanthropy rows of household %s failed", family_id)
    if total:
        logger.info("Moved %d guardrail mode and philanthropy settings rows in %s", total, path.name)
    return total
