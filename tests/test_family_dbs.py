"""
Unit tests for Database-Per-Family Architecture & Path Resolution.
Verifies:
1. config.get_global_db_path and config.get_family_db_path resolution.
2. routes.helpers.get_current_db_path and _DbPathProxy context resolution.
3. db.session.resolve_db_path resolution with family_id support.
4. Strict cross-family database isolation and remote multi-db sync.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import pytest

import config
from routes.helpers import (
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


def test_sync_db_from_remote_multi_db(tmp_path: Path, monkeypatch):
    """Verifies sync_db_from_remote atomically extracts and integrity-checks global.db and families/*.db."""
    import tarfile
    import sync_db_from_remote as sync_mod

    fake_data_dir = tmp_path / "local_data"
    fake_backup_dir = tmp_path / "external_backups"
    remote_stage_src = tmp_path / "remote_stage_src"
    (remote_stage_src / "families").mkdir(parents=True, exist_ok=True)

    # Create valid remote SQLite files in remote_stage_src
    for rel in ("global.db", "families/1.db", "families/2.db"):
        db_p = remote_stage_src / rel
        with sqlite3.connect(str(db_p)) as c:
            c.execute("CREATE TABLE sync_probe (val TEXT)")
            c.execute("INSERT INTO sync_probe (val) VALUES (?)", (rel,))
            c.commit()

    monkeypatch.setattr(sync_mod, "DATA_DIR", fake_data_dir)
    monkeypatch.setattr(sync_mod, "LOCAL_BACKUP_DIR", fake_backup_dir)

    executed_cmds: list[str] = []

    class DummyCompleted:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(cmd: str, *args, **kwargs):
        executed_cmds.append(cmd)
        if cmd.startswith("scp "):
            dest_tar = Path(cmd.split()[-1])
            with tarfile.open(dest_tar, "w:gz") as tar:
                tar.add(remote_stage_src / "global.db", arcname="global.db")
                tar.add(remote_stage_src / "families" / "1.db", arcname="families/1.db")
                tar.add(remote_stage_src / "families" / "2.db", arcname="families/2.db")
        return DummyCompleted()

    monkeypatch.setattr(sync_mod.subprocess, "run", fake_run)

    assert sync_mod.sync_db_from_remote(verbose=False) is True
    assert (fake_data_dir / "global.db").exists()
    assert (fake_data_dir / "families" / "1.db").exists()
    assert (fake_data_dir / "families" / "2.db").exists()

    # Verify single family_id mode builds targeted sqlite3 .backup command
    executed_cmds.clear()
    assert sync_mod.sync_db_from_remote(verbose=False, family_id=1) is True
    ssh_snapshot_cmd = executed_cmds[0]
    assert "families/1.db '.backup" in ssh_snapshot_cmd
    # Pre-sync backup was written to external backup dir (never inside DATA_DIR)
    assert (fake_backup_dir / "global.db").exists()
    assert (fake_backup_dir / "families" / "1.db").exists()
    assert list(fake_data_dir.rglob("*.local_bak")) == []


def test_peer_family_sync_never_cascade_deletes_users_or_account_roles(tmp_path: Path):
    """
    Regression test: mutating Family.settings on families/1.db must upsert into global.db
    via ON CONFLICT DO UPDATE (never INSERT OR REPLACE, which triggers ON DELETE CASCADE
    on users and account_roles when PRAGMA foreign_keys = ON). Also verifies self-healing
    lookup via get_user_by_email_hash if global.db users rows are missing.
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

    # Mutate Family.settings ONLY (e.g. save_household_widget_ids)
    with get_orm_session(fam1_db, family_id=1, commit=True) as session:
        fam = session.get(Family, 1)
        assert fam is not None
        fam.settings = '{"primary_state": "WA", "overview_widgets": ["ov_kpi_grid"]}'

    # Verify global.db users and account_roles were NOT cascade-deleted
    with get_db_connection(global_db) as gconn:
        assert gconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()[0] == 1
        assert gconn.execute("SELECT COUNT(*) FROM account_roles WHERE family_id = 1").fetchone()[0] == 1

    # Simulate missing users row in global.db and verify get_user_by_email_hash self-heals global.db
    with get_db_connection(global_db) as gconn:
        gconn.execute("DELETE FROM users WHERE family_id = 1")
        gconn.commit()
        assert gconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()[0] == 0

    em_hash = security.hash_email("owner@example.com")
    recovered = get_user_by_email_hash(global_db, em_hash)
    assert recovered is not None
    assert int(recovered["user_id"]) == uid
    assert int(recovered["family_id"]) == 1

    with get_db_connection(global_db) as gconn:
        assert gconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()[0] == 1



