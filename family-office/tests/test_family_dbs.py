"""
Unit tests for Database-Per-Family Architecture & Path Resolution.
Verifies:
1. config.get_global_db_path and config.get_family_db_path resolution.
2. routes.context.get_current_db_path and _DbPathProxy context resolution.
3. db.session.resolve_db_path resolution with family_id support.
4. Strict cross-family database isolation and remote multi-db sync.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import pytest

import config
import db.scenarios
import forecast.storage
import security
from db import balance_snapshots
from db.balance_history import rebuild_historical_net_worth_from_snapshots
from db.session import get_orm_session
from db.data_migration import try_relational_load, try_relational_save
from forecast.storage import load_scenario_state
from hvl_common.db import get_db_connection
from routes.context import (
    DB_PATH,
    _DbPathProxy,
    get_current_db_path,
    get_current_cache_db_path,
    set_background_context,
    reset_background_context,
)
from db.session import resolve_db_path, get_orm_session


def test_universe_db_path_resolvers():
    """Validates global, family, and cache database path resolution across universes."""
    data_dir = config.get_data_dir()

    # Global DB paths
    assert config.get_global_db_path("public") == data_dir / "public" / "global.db"
    assert config.get_global_db_path("demo") == data_dir / "demo" / "global.db"
    assert config.get_global_db_path("beta") == data_dir / "demo" / "global.db"  # beta normalizes to demo
    assert config.get_global_db_path("sandbox") == data_dir / "sandbox" / "global.db"
    assert config.get_global_db_path("test") == data_dir / "test" / "global.db"

    # Family DB paths
    assert config.get_family_db_path(1, "public") == data_dir / "public" / "families" / "1.db"
    assert config.get_family_db_path(2, "demo") == data_dir / "demo" / "families" / "2.db"
    assert config.get_family_db_path(2, "beta") == data_dir / "demo" / "families" / "2.db"  # beta normalizes to demo
    assert config.get_family_db_path(3, "sandbox") == data_dir / "sandbox" / "families" / "3.db"
    assert config.get_family_db_path(4, "test") == data_dir / "test" / "families" / "4.db"

    # Cache DB paths with per-family isolation
    assert config.get_cache_db_path_for_universe("public", family_id=1) == data_dir / "public" / "families" / "1_cache.db"
    assert config.get_cache_db_path_for_universe("demo", family_id=2) == data_dir / "demo" / "families" / "2_cache.db"
    assert config.get_cache_db_path_for_universe("beta", family_id=2) == data_dir / "demo" / "families" / "2_cache.db"
    assert config.get_cache_db_path_for_universe("sandbox", family_id=3) == data_dir / "sandbox" / "families" / "3_cache.db"
    assert config.get_cache_db_path_for_universe("test", family_id=4) == data_dir / "test" / "families" / "4_cache.db"
    assert config.get_cache_db_path_for_universe("test", family_id=0) == data_dir / "test" / "global_cache.db"


test_config_paths = test_universe_db_path_resolvers


def test_routes_helpers_db_path_proxy():
    """Validates that get_current_db_path and _DbPathProxy route to family or global DB based on context."""
    # Outside request/background context in 'test' universe
    assert get_current_db_path() == config.get_global_db_path("test")
    assert Path(str(DB_PATH)) == config.get_global_db_path("test")

    # Explicit family_id argument
    assert get_current_db_path(family_id=42) == config.get_family_db_path(42, "test")

    # With background context set
    tokens = set_background_context(family_id=77, universe="test")
    try:
        assert get_current_db_path() == config.get_family_db_path(77, "test")
        assert Path(str(DB_PATH)) == config.get_family_db_path(77, "test")
        assert get_current_cache_db_path() == config.get_cache_db_path_for_universe("test", family_id=77)
    finally:
        reset_background_context(tokens)

    # After reset, returns back to global test DB
    assert get_current_db_path() == config.get_global_db_path("test")
    assert Path(str(DB_PATH)) == config.get_global_db_path("test")

    # Helper methods on proxy
    assert DB_PATH.for_family(99) == config.get_family_db_path(99, "test")
    assert DB_PATH.global_db() == config.get_global_db_path("test")


def test_resolve_db_path():
    """Validates that db.session.resolve_db_path supports family_id and respects explicit custom paths."""
    # None or DB_PATH with family_id
    assert resolve_db_path(family_id=15) == config.get_family_db_path(15, "test")
    assert resolve_db_path(DB_PATH, family_id=25) == config.get_family_db_path(25, "test")

    # Without family_id (defaults to global DB in test universe)
    assert resolve_db_path(family_id=0) == config.get_global_db_path("test")

    # Explicit custom test DB is preserved as-is
    custom = Path("/tmp/custom_mock_db.sqlite")
    assert resolve_db_path(custom, family_id=15) == custom


def test_peer_family_sync_never_cascade_deletes_users_or_account_roles(tmp_path: Path, monkeypatch):
    """
    Regression test: mutating a Family setting column on families/1.db must upsert into global.db
    via ON CONFLICT DO UPDATE (never INSERT OR REPLACE, which triggers ON DELETE CASCADE
    on users and account_roles when PRAGMA foreign_keys = ON). Also verifies that a missing
    global.db login is re-synced from the household DB only in Local Desktop mode (never in cloud mode).
    """
    import security
    from db.models import AccountRole, Family
    from db.users import get_user_by_email_hash
    from hvl_common.db import get_db_connection

    uni_dir = tmp_path / "public"
    fam_dir = uni_dir / "families"
    fam_dir.mkdir(parents=True, exist_ok=True)
    global_db = uni_dir / "global.db"
    fam1_db = fam_dir / "1.db"

    security.init_db(global_db)
    security.init_db(fam1_db)

    uid = security.add_family_member(
        fam1_db,
        family_id=1,
        name="Primary Owner",
        email="owner@example.com",
        relationship="primary",
        role="editor",
    )
    with get_orm_session(fam1_db, family_id=1, commit=True) as session:
        session.add(AccountRole(family_id=1, monarch_account_id="acc_1", role="brokerage"))

    with get_db_connection(global_db) as gconn:
        assert gconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()[0] == 1
        assert gconn.execute("SELECT COUNT(*) FROM account_roles WHERE family_id = 1").fetchone()[0] == 1

    # Mutate one Family setting column ONLY (e.g. a saved widget layout)
    with get_orm_session(fam1_db, family_id=1, commit=True) as session:
        fam = session.get(Family, 1)
        assert fam is not None
        fam.overview_widgets = '["ov_kpi_grid"]'

    # Verify global.db users and account_roles were NOT cascade-deleted
    with get_db_connection(global_db) as gconn:
        assert gconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()[0] == 1
        assert gconn.execute("SELECT COUNT(*) FROM account_roles WHERE family_id = 1").fetchone()[0] == 1

    # Simulate missing users row in global.db: cloud mode must NOT mint a global login from a household DB scan
    with get_db_connection(global_db) as gconn:
        gconn.execute("DELETE FROM users WHERE family_id = 1")
        gconn.commit()
        assert gconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()[0] == 0

    em_hash = security.hash_email("owner@example.com")
    assert get_user_by_email_hash(global_db, em_hash) is None
    with get_db_connection(global_db) as gconn:
        assert gconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()[0] == 0

    # Local Desktop mode: the one local household re-syncs its own rows into global.db.
    monkeypatch.setattr("config.is_local_mode", lambda: True)
    recovered = get_user_by_email_hash(global_db, em_hash)
    assert recovered is not None
    assert int(recovered["user_id"]) == uid
    assert int(recovered["family_id"]) == 1

    with get_db_connection(global_db) as gconn:
        assert gconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()[0] == 1


@pytest.fixture
def temp_family_db(tmp_path: Path):
    db_file = tmp_path / "family_1.db"
    security.init_db(db_file)
    with get_db_connection(db_file) as conn:
        with conn:
            conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (1, 'Test Family')")
    return db_file


def test_roundtrip_family_gifts(temp_family_db: Path):
    data = {
        "annual_exclusion_limits": {},
        "recipients": [
            {
                "name": "Jane Doe",
                "relationship": "Child",
                "member_count": 1,
                "notes": "College student",
                "gifts": [
                    {"year": 2024, "amount": 18000.0, "notes": "Tuition contribution"},
                    {"year": 2025, "amount": 19000.0, "notes": "Annual exclusion"},
                ],
            }
        ],
    }
    assert try_relational_save(temp_family_db, "family_gifts", data, family_id=1) is True
    handled, loaded = try_relational_load(temp_family_db, "family_gifts", family_id=1)
    assert handled is True
    assert isinstance(loaded, dict)
    assert "recipients" in loaded
    assert len(loaded["recipients"]) == 1
    rec = loaded["recipients"][0]
    assert rec["name"] == "Jane Doe"
    assert rec["relationship"] == "Child"
    assert len(rec["gifts"]) == 2
    assert rec["gifts"][0]["year"] == 2024
    assert rec["gifts"][0]["amount"] == 18000.0
    assert rec["gifts"][1]["amount"] == 19000.0


def test_roundtrip_career_compensation(temp_family_db: Path):
    data = {
        "history": [
            {
                "year": 2025,
                "company": "Apex Dynamics",
                "salary": 275000.0,
                "bonus": 85000.0,
                "notes": "Performance review",
            },
            {
                "year": 2024,
                "company": "Apex Dynamics",
                "salary": 250000.0,
                "bonus": 60000.0,
                "notes": "Annual bonus",
            },
        ]
    }
    assert try_relational_save(temp_family_db, "career_compensation", data, family_id=1) is True
    handled, loaded = try_relational_load(temp_family_db, "career_compensation", family_id=1)
    assert handled is True
    assert isinstance(loaded, list)
    assert len(loaded) == 2
    row_2025 = next(r for r in loaded if r["year"] == 2025)
    assert row_2025["company"] == "Apex Dynamics"
    assert row_2025["salary"] == 275000.0
    assert row_2025["bonus"] == 85000.0


def test_roundtrip_company_equity_grants(temp_family_db: Path):
    data = {
        "equityGrants": [
            {
                "grant_label": "Founder Preferred Grant",
                "grant_type": "iso",
                "strike_price": 4.25,
                "shares_granted": 40000.0,
                "shares_vested": 20000.0,
                "shares_unvested": 20000.0,
                "shares_exercised": 0.0,
                "cost_basis": 4.25,
                "grant_date": "2023-03-01",
                "fully_vested_date": "2027-03-01",
                "vesting_schedule": {"2024": 10000, "2025": 10000, "2026": 10000, "2027": 10000},
            }
        ]
    }
    assert try_relational_save(temp_family_db, "company_equity_grants", data, family_id=1) is True
    handled, loaded = try_relational_load(temp_family_db, "company_equity_grants", family_id=1)
    assert handled is True
    assert isinstance(loaded, list)
    assert len(loaded) == 1
    grant = loaded[0]
    assert grant["grant_label"] == "Founder Preferred Grant"
    assert grant["grant_type"] == "iso"
    assert grant["strike_price"] == 4.25
    assert grant["shares_granted"] == 40000.0
    assert grant["shares_vested"] == 20000.0
    assert grant["vesting_schedule"] == {"2024": 10000, "2025": 10000, "2026": 10000, "2027": 10000}


def test_load_scenario_state_no_sqlite_write_on_pure_read(temp_family_db: Path, monkeypatch: pytest.MonkeyPatch):
    test_state = {
        "scenarios": [
            {"id": "scen_baseline", "name": "Baseline", "color": "#3b82f6", "equity_growth_preset": "moderate"}
        ],
        "events": [{"id": "ev1", "name": "Event 1"}],
        "active_scenario_id": "scen_baseline",
    }
    db.scenarios.save_scenario_state(family_id=1, state=test_state, db_path=temp_family_db)
    monkeypatch.setattr(forecast.storage, "get_db_path", lambda: temp_family_db)

    save_calls = []
    orig_save = db.scenarios.save_scenario_state

    def mock_save(*args, **kwargs):
        save_calls.append((args, kwargs))
        return orig_save(*args, **kwargs)

    monkeypatch.setattr(db.scenarios, "save_scenario_state", mock_save)

    # 1. Default read (persist_repairs=False) must NOT mutate SQLite
    res = load_scenario_state(family_id=1, persist_repairs=False)
    assert len(save_calls) == 0
    assert res["scenarios"][0]["color"] == "#1D4ED8"

    # 2. Explicit repair persistence (persist_repairs=True) saves repairs
    res_persisted = load_scenario_state(family_id=1, persist_repairs=True)
    assert len(save_calls) == 1
    assert res_persisted["scenarios"][0]["color"] == "#1D4ED8"


def test_rebuild_historical_net_worth_persist_flag(temp_family_db: Path, monkeypatch: pytest.MonkeyPatch):
    with get_orm_session(temp_family_db, family_id=1, commit=True) as session:
        balance_snapshots.write_snapshots(session, 1, {"acc_test": {"2025-01-01": 75000.0}})

    encrypted_saves = []
    orig_db_save = security.db_save_encrypted

    def mock_db_save(path, key, *args, **kwargs):
        if key == "historical_net_worth":
            encrypted_saves.append(key)
        return orig_db_save(path, key, *args, **kwargs)

    monkeypatch.setattr(security, "db_save_encrypted", mock_db_save)

    # 1. persist=False: computes series without SQLite write
    series_false = rebuild_historical_net_worth_from_snapshots(
        family_id=1, db_path=temp_family_db, persist=False
    )
    assert len(encrypted_saves) == 0
    assert len(series_false) > 0

    # 2. persist=True: computes series and writes to SQLite
    series_true = rebuild_historical_net_worth_from_snapshots(
        family_id=1, db_path=temp_family_db, persist=True
    )
    assert len(encrypted_saves) == 1
    assert len(series_true) > 0
