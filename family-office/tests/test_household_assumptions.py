"""
Planning assumptions as one encrypted row per section (`db/household_assumptions.py`) and the deletion quarantine as
plain `families` columns (alembic 0009): a save writes only its own section, values are never stored in plain text,
legacy `assumptions_json` moves to rows, and the quarantine keys move out of `families.settings`.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

import security
from db import household_assumptions as ha
from db.estate import get_estate_planning_assumptions, merge_estate_planning_assumptions
from hvl_common.db import get_db_connection

FID = 1


@pytest.fixture
def family_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "family_1.db"
    security.init_db(db_file)
    with get_db_connection(db_file) as conn:
        with conn:
            conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (?, 'Test Family')", (FID,))
    return db_file


def _raw_sections(db_file: Path) -> dict:
    with get_db_connection(db_file) as conn:
        rows = conn.execute(
            "SELECT section_key, value_enc FROM household_assumption_sections WHERE family_id = ?", (FID,)
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def test_each_section_is_its_own_encrypted_row(family_db: Path):
    ha.set_section(FID, "investment_policy", {"anchor_preset": "glidepath_60_40"}, db_path=family_db)
    ha.set_section(FID, "annual_spend", 84_000.0, db_path=family_db)
    ha.set_section(FID, "investment_policy", {"anchor_preset": "boglehead_80_20"}, db_path=family_db)

    raw = _raw_sections(family_db)
    assert set(raw) == {"investment_policy", "annual_spend"}
    assert all("boglehead" not in str(v) and "84000" not in str(v) for v in raw.values())
    assert ha.get_assumptions(FID, db_path=family_db) == {
        "investment_policy": {"anchor_preset": "boglehead_80_20"},
        "annual_spend": 84_000.0,
    }
    assert ha.get_dict_section(FID, "annual_spend", db_path=family_db) == {}
    assert ha.get_assumptions(0, db_path=family_db) == {}


def test_estate_planning_merge_keeps_other_keys_and_sections(family_db: Path):
    ha.set_section(FID, "pension", {"primary": {"annual_amount": 1.0}}, db_path=family_db)
    merge_estate_planning_assumptions(FID, {"apply_tcja_sunset": True}, db_path=family_db)
    merged = merge_estate_planning_assumptions(FID, {"charitable_pct": 0.1}, db_path=family_db)

    assert merged == {"apply_tcja_sunset": True, "charitable_pct": 0.1}
    assert get_estate_planning_assumptions(FID, db_path=family_db) == merged
    assert ha.get_section(FID, "pension", db_path=family_db) == {"primary": {"annual_amount": 1.0}}


def test_legacy_assumptions_json_moves_to_rows_once(family_db: Path):
    ha.set_section(FID, "annual_spend", 90_000.0, db_path=family_db)
    legacy = {"estate_planning": {"charitable_pct": 0.2}, "annual_spend": 1.0}
    with get_db_connection(family_db) as conn:
        with conn:
            conn.execute(
                "INSERT INTO household_profile (family_id, state, filing_status, assumptions_json) "
                "VALUES (?, 'WA', 'MFJ', ?)",
                (FID, json.dumps(legacy)),
            )

    assert ha.move_legacy_assumptions(family_db) == 2
    assert ha.get_assumptions(FID, db_path=family_db) == {
        "estate_planning": {"charitable_pct": 0.2},
        "annual_spend": 90_000.0,  # the row saved after the legacy copy wins
    }
    with get_db_connection(family_db) as conn:
        row = conn.execute("SELECT assumptions_json FROM household_profile WHERE family_id = ?", (FID,)).fetchone()
    assert row[0] is None
    assert ha.move_legacy_assumptions(family_db) == 0


def test_legacy_sections_move_on_first_read_or_save_after_a_skipped_open(family_db: Path):
    # init_db already ran in this process (as when the vault was locked then), so only a read or save moves them.
    security.get_family_key(family_db, FID)  # the household key exists before its data, as in a real database
    legacy = {"pension": {"primary": {"annual_amount": 2.0}}, "annual_spend": 1.0}
    with get_db_connection(family_db) as conn:
        with conn:
            conn.execute(
                "INSERT INTO household_profile (family_id, state, filing_status, assumptions_json) "
                "VALUES (?, 'WA', 'MFJ', ?)",
                (FID, json.dumps(legacy)),
            )

    merge_estate_planning_assumptions(FID, {"charitable_pct": 0.1}, db_path=family_db)
    assert set(_raw_sections(family_db)) == {"pension", "annual_spend", "estate_planning"}
    assert ha.get_section(FID, "pension", db_path=family_db) == {"primary": {"annual_amount": 2.0}}
    with get_db_connection(family_db) as conn:
        row = conn.execute("SELECT assumptions_json FROM household_profile WHERE family_id = ?", (FID,)).fetchone()
    assert row[0] is None


def _run_0009_upgrade(db_file: Path) -> None:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0009_household_assumption_sections.py"
    spec = importlib.util.spec_from_file_location("migration_0009", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
    finally:
        engine.dispose()


def test_migration_moves_deletion_keys_out_of_settings(family_db: Path):
    settings = {
        "primary_state": "WA",
        "deletion_scheduled_at": "2026-11-01T00:00:00+00:00",
        "deletion_purge_after": "2026-12-01T00:00:00+00:00",
        "deletion_requested_by": "Editor",
    }
    with get_db_connection(family_db) as conn:
        with conn:
            conn.execute("UPDATE families SET settings = ? WHERE family_id = ?", (json.dumps(settings), FID))
            conn.execute("INSERT INTO families (family_id, name, settings) VALUES (2, 'Other', 'not json')")

    _run_0009_upgrade(family_db)

    with get_db_connection(family_db) as conn:
        rows = conn.execute(
            "SELECT family_id, settings, deletion_scheduled_at, deletion_purge_after, deletion_requested_by "
            "FROM families ORDER BY family_id"
        ).fetchall()
    assert json.loads(rows[0][1]) == {"primary_state": "WA"}
    assert tuple(rows[0][2:]) == ("2026-11-01T00:00:00+00:00", "2026-12-01T00:00:00+00:00", "Editor")
    assert tuple(rows[1][1:]) == ("not json", None, None, None)


def test_deletion_status_reads_and_clears_the_columns(family_db: Path):
    from db.security_repo import fetch_family_deletion_quarantine, write_family_deletion_quarantine

    assert security.get_family_deletion_status(family_db, family_id=FID) is None
    assert write_family_deletion_quarantine(family_db, FID, ("2026-11-01T00:00:00+00:00", "2999-01-01", "Ed"))
    status = security.get_family_deletion_status(family_db, family_id=FID)
    assert status is not None and status["requested_by"] == "Ed" and not status["is_expired"]

    security.cancel_family_deletion(family_db, family_id=FID)
    assert fetch_family_deletion_quarantine(family_db, FID) == (None, None, None)
    assert not write_family_deletion_quarantine(family_db, 99, (None, None, None))
