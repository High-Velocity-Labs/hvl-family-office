"""The forecast guardrail mode lives in its own column and the philanthropy ledger settings in their own table;
`db.column_backfill` moves rows written the old way (mode inside `payload_enc`, settings JSON on a `tax_year = -1`
budget row) once, and reads match before and after."""

from __future__ import annotations

import json
import sqlite3

import pytest

from db import philanthropy, scenarios
from db.column_backfill import backfill_columns
from db.models import ForecastScenario, PhilanthropyBudget
from db.session import get_orm_session, resolve_db_path

FID = 1


@pytest.fixture
def db_path():
    path = resolve_db_path(None, family_id=FID)
    saved_scen = scenarios.get_scenario_state(family_id=FID, db_path=path)
    saved_phil = philanthropy.get_philanthropy_payload(family_id=FID, db_path=path)
    yield path
    if saved_scen:
        scenarios.save_scenario_state(family_id=FID, state=saved_scen, db_path=path)
    philanthropy.save_philanthropy_payload(family_id=FID, payload=saved_phil or {}, db_path=path)


def _raw(path, sql, params=()):
    with sqlite3.connect(path) as conn:
        return conn.execute(sql, params).fetchall()


def _state():
    return {
        "active_scenario_id": "scen_baseline",
        "scenarios": [
            {"id": "scen_baseline", "name": "Base", "is_baseline": True, "spending_guardrail_mode": "moderate"},
            {"id": "scen_child", "name": "Child", "parent_id": "scen_baseline"},
        ],
        "events": [],
    }


def test_guardrail_mode_is_a_column_not_in_the_payload(db_path):
    scenarios.save_scenario_state(family_id=FID, state=_state(), db_path=db_path)
    cols = dict(_raw(
        db_path, "SELECT scenario_id, spending_guardrail_mode FROM forecast_scenarios WHERE family_id = ?", (FID,)
    ))
    assert cols == {"scen_baseline": "moderate", "scen_child": "inherit"}
    with get_orm_session(db_path, family_id=FID) as session:
        payloads = [r.payload_enc for r in session.query(ForecastScenario).filter_by(family_id=FID)]
    assert all("spending_guardrail_mode" not in p for p in payloads)

    loaded = {s["id"]: s for s in scenarios.get_scenario_state(family_id=FID, db_path=db_path)["scenarios"]}
    assert loaded["scen_baseline"]["spending_guardrail_mode"] == "moderate"
    assert loaded["scen_child"].get("spending_guardrail_mode") is None


def test_backfill_moves_a_mode_left_in_the_payload(db_path):
    scenarios.save_scenario_state(family_id=FID, state=_state(), db_path=db_path)
    with get_orm_session(db_path, family_id=FID, commit=True) as session:
        row = session.get(ForecastScenario, (FID, "scen_baseline"))
        row.payload_enc = {**row.payload_enc, "spending_guardrail_mode": "aggressive"}
        row.spending_guardrail_mode = None
        session.get(ForecastScenario, (FID, "scen_child")).spending_guardrail_mode = None

    assert backfill_columns(db_path) == 2
    cols = dict(_raw(
        db_path, "SELECT scenario_id, spending_guardrail_mode FROM forecast_scenarios WHERE family_id = ?", (FID,)
    ))
    assert cols == {"scen_baseline": "aggressive", "scen_child": "inherit"}
    with get_orm_session(db_path, family_id=FID) as session:
        assert "spending_guardrail_mode" not in session.get(ForecastScenario, (FID, "scen_baseline")).payload_enc
    assert backfill_columns(db_path) == 0  # no NULL left: the next process start does no work
    assert _raw(db_path, "SELECT COUNT(*) FROM forecast_scenarios WHERE spending_guardrail_mode IS NULL") == [(0,)]


def test_philanthropy_settings_have_their_own_table(db_path):
    payload = {
        "total_lifetime_charity": 4200.0,
        "lifetime_history": [{"year": "2019", "total": 4200.0, "grant_count": 0}],
        "donations_by_year": {"2019": {"total": 4200.0, "donations": [], "budget": 5000.0}},
    }
    philanthropy.save_philanthropy_payload(family_id=FID, payload=payload, db_path=db_path)
    years = [r[0] for r in _raw(db_path, "SELECT tax_year FROM philanthropy_budgets WHERE family_id = ?", (FID,))]
    assert years == [2019]
    assert _raw(db_path, "SELECT COUNT(*) FROM philanthropy_settings WHERE family_id = ?", (FID,)) == [(1,)]

    out = philanthropy.get_philanthropy_payload(family_id=FID, db_path=db_path)
    assert out["total_lifetime_charity"] == 4200.0
    assert out["donations_by_year"]["2019"]["total"] == 4200.0
    assert out["lifetime_history"][0]["budget"] == 5000.0


def test_backfill_moves_the_legacy_settings_row(db_path):
    philanthropy.save_philanthropy_payload(family_id=FID, payload={}, db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM philanthropy_settings WHERE family_id = ?", (FID,))
    meta = {"total_lifetime_charity": 900.0, "lifetime_history": [], "year_totals": {"2018": 900.0}}
    with get_orm_session(db_path, family_id=FID, commit=True) as session:
        session.add(PhilanthropyBudget(family_id=FID, tax_year=-1, budget_amount_enc=json.dumps(meta)))
    # Read before the move (a locked vault skipped it) still shows the legacy totals.
    assert philanthropy.get_philanthropy_payload(family_id=FID, db_path=db_path)["total_lifetime_charity"] == 900.0

    assert backfill_columns(db_path) == 1
    legacy = _raw(db_path, "SELECT COUNT(*) FROM philanthropy_budgets WHERE family_id = ? AND tax_year = -1", (FID,))
    assert legacy == [(0,)]
    out = philanthropy.get_philanthropy_payload(family_id=FID, db_path=db_path)
    assert out["total_lifetime_charity"] == 900.0
    assert out["donations_by_year"]["2018"]["total"] == 900.0


def test_backfill_holds_the_write_lock_from_its_first_read(db_path, monkeypatch):
    # A save another process commits between the move's read and its write would be overwritten with the older values,
    # so the move holds the write lock while it reads: a writer arriving mid-move waits instead of slipping in.
    philanthropy.save_philanthropy_payload(family_id=FID, payload={}, db_path=db_path)
    meta = {"total_lifetime_charity": 900.0, "lifetime_history": [], "year_totals": {}}
    with get_orm_session(db_path, family_id=FID, commit=True) as session:
        session.add(PhilanthropyBudget(family_id=FID, tax_year=-1, budget_amount_enc=json.dumps(meta)))
    # A scenario left to move would flush (and lock) before the settings read, passing this test without the fix.
    assert _raw(db_path, "SELECT COUNT(*) FROM forecast_scenarios WHERE spending_guardrail_mode IS NULL") == [(0,)]

    import db.column_backfill as column_backfill

    blocked = []
    real_meta = column_backfill.legacy_settings_meta

    def meta_while_another_writer_tries(raw):
        conn = sqlite3.connect(db_path, timeout=0)
        try:
            conn.execute("DELETE FROM philanthropy_settings WHERE family_id = ?", (FID,))
        except sqlite3.OperationalError as exc:
            blocked.append(str(exc))
        finally:
            conn.close()
        return real_meta(raw)

    monkeypatch.setattr(column_backfill, "legacy_settings_meta", meta_while_another_writer_tries)
    assert backfill_columns(db_path) == 1
    assert blocked and "locked" in blocked[0]


def test_global_db_without_domain_tables_migrates_and_skips_backfill(tmp_path):
    # Prod's global directory DB sits at 0007 with no forecast_scenarios or philanthropy tables.
    from db.schema_migrations import alembic_head_revision, upgrade_to_head

    path = tmp_path / "global.db"
    upgrade_to_head(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE forecast_scenarios")
        conn.execute("DROP TABLE philanthropy_budgets")
        conn.execute("DROP TABLE philanthropy_settings")
        conn.execute("UPDATE alembic_version SET version_num = '0007_account_balance_snapshots'")
    upgrade_to_head(path)
    assert _raw(path, "SELECT version_num FROM alembic_version") == [(alembic_head_revision(),)]
    assert backfill_columns(path) == 0
