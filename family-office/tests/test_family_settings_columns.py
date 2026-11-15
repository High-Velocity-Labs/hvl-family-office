"""
Household settings as plain `families` columns (alembic 0010, `db/family_settings.py`): the migration moves every
key out of the old `families.settings` blob, each writer changes only its own column (so concurrent writers never
lose each other's change), writes reach the peer database, and a backup exported before 0010 still restores.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
from hvl_common.security import wrap_fek_with_passphrase

import security
from db import family_settings, schema_migrations
from db.fovault_repo import extract_fek_from_backup_snapshot
from db.household_activity import record_family_login
from hvl_common.db import get_db_connection

PRE_0010 = "0009_household_assumption_sections"


def _alembic_upto(db_path: Path, revision: str) -> None:
    from alembic import command
    from hvl_common.db import get_engine

    cfg = schema_migrations._alembic_config(db_path)
    with get_engine(db_path).begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def test_migration_moves_every_settings_key_into_its_column(tmp_path):
    db_path = tmp_path / "pre_0010.db"
    _alembic_upto(db_path, PRE_0010)
    blob = {
        "primary_state": "WA",
        "tax_filing_status": "Single",
        "is_demo": True,
        "onboarding_completed": True,
        "onboarding_dismissed": 0,
        "onboarding_wizard_dismissed": 1,
        "overview_widgets": ["ov_kpi_grid", "ov_cash"],
        "collapsed_charts": ["cash_flow"],
        "last_login_at": "2026-11-01T00:00:00+00:00",
        "login_count": 7,
        "root_kek_rekeyed_v1": True,
        "local_passphrase_fek_enc": {"kdf": {"name": "scrypt"}, "ct": "abc"},
        "city": "dropped",
    }
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO families (family_id, name, settings) VALUES (5, 'Full', ?)", (json.dumps(blob),))
        conn.execute("INSERT INTO families (family_id, name, settings) VALUES (6, 'Broken', 'not json')")
        conn.execute("INSERT INTO families (family_id, name, settings) VALUES (7, 'Legacy wrap', ?)",
                     (json.dumps({"local_passphrase_fek_enc": "pbkdf2_sha256$1$aa$bb"}),))

    assert schema_migrations.upgrade_to_head(db_path) is True
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cols = {r[1] for r in conn.execute("PRAGMA table_info(families)").fetchall()}
        rows = {r["family_id"]: dict(r) for r in conn.execute("SELECT * FROM families").fetchall()}
    assert "settings" not in cols
    full = rows[5]
    assert (full["primary_state"], full["tax_filing_status"], full["is_demo"]) == ("WA", "Single", 1)
    flags = (full["onboarding_completed"], full["onboarding_dismissed"], full["onboarding_wizard_dismissed"])
    assert flags == (1, 0, 1)
    assert json.loads(full["overview_widgets"]) == ["ov_kpi_grid", "ov_cash"]
    assert full["scenarios_widgets"] is None and json.loads(full["collapsed_charts"]) == ["cash_flow"]
    assert (full["last_login_at"], full["login_count"], full["root_kek_rekeyed"]) == ("2026-11-01T00:00:00+00:00", 7, 1)
    assert json.loads(full["local_passphrase_fek_enc"]) == blob["local_passphrase_fek_enc"]
    broken = rows[6]
    assert (broken["primary_state"], broken["tax_filing_status"], broken["login_count"]) == ("", "MFJ", 0)
    assert json.loads(rows[7]["local_passphrase_fek_enc"]) == "pbkdf2_sha256$1$aa$bb"


def test_each_writer_keeps_the_others_settings(tmp_path):
    uni_dir = tmp_path / "public"
    (uni_dir / "families").mkdir(parents=True)
    global_db = uni_dir / "global.db"
    fam_db = uni_dir / "families" / "1.db"
    security.init_db(global_db)
    security.init_db(fam_db)
    security.update_family(fam_db, family_id=1, name="Settings Household")

    family_settings.set_onboarding_flags(1, {"onboarding_dismissed": True}, db_path=fam_db)
    family_settings.save_widget_layout(1, "overview_widgets", ["ov_kpi_grid"], db_path=fam_db)
    family_settings.set_chart_collapsed(1, "cash_flow", True, db_path=fam_db)
    family_settings.set_chart_collapsed(1, "monte_carlo", True, db_path=fam_db)
    family_settings.set_chart_collapsed(1, "cash_flow", False, db_path=fam_db)
    assert record_family_login(fam_db, family_id=1)

    stored = family_settings.get_family_settings(1, db_path=fam_db)
    assert stored["onboarding_dismissed"] is True and stored["onboarding_completed"] is False
    assert stored["overview_widgets"] == ["ov_kpi_grid"]
    assert stored["collapsed_charts"] == ["monte_carlo"]
    with get_db_connection(global_db) as conn:
        row = conn.execute(
            "SELECT onboarding_dismissed, overview_widgets, collapsed_charts FROM families WHERE family_id = 1"
        ).fetchone()
    assert row[0] == 1 and json.loads(row[1]) == ["ov_kpi_grid"] and json.loads(row[2]) == ["monte_carlo"]
    with get_db_connection(fam_db) as conn:
        assert conn.execute("SELECT login_count FROM families WHERE family_id = 1").fetchone()[0] == 1


def test_backup_exported_before_0010_still_unwraps(tmp_path):
    snapshot = tmp_path / "old.fovault"
    _alembic_upto(snapshot, PRE_0010)
    fek = Fernet.generate_key()
    envelope = wrap_fek_with_passphrase(fek, "correct-horse-battery-staple")
    with sqlite3.connect(str(snapshot)) as conn:
        conn.execute(
            "INSERT INTO families (family_id, name, settings) VALUES (3, 'Old', ?)",
            (json.dumps({"primary_state": "WA", "_portable_vault_fek_b64": envelope}),),
        )
    assert extract_fek_from_backup_snapshot(snapshot, passphrase="correct-horse-battery-staple") == fek


def test_raw_readers_migrate_a_database_still_at_0009(tmp_path):
    """The login page's passphrase check is the first thing to open a Local Desktop db after an update."""
    from security.vault import has_local_passphrase_configured

    global_db = tmp_path / "global.db"
    _alembic_upto(global_db, PRE_0010)
    wrap = {"kdf": {"name": "scrypt"}, "ct": "abc"}
    with sqlite3.connect(str(global_db)) as conn:
        conn.execute(
            "INSERT INTO families (family_id, name, settings) VALUES (4, 'Local', ?)",
            (json.dumps({"local_passphrase_fek_enc": wrap}),),
        )
    assert has_local_passphrase_configured(global_db, family_id=4) is True


def test_reprovision_resets_every_setting(tmp_path):
    from db.security_repo import upsert_invited_household_metadata

    db_path = tmp_path / "global.db"
    security.init_db(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO families (family_id, name, onboarding_wizard_dismissed, collapsed_charts, login_count, "
            "local_passphrase_fek_enc, portable_vault_fek) VALUES (8, 'Old', 1, '[\"cash_flow\"]', 5, '\"w\"', '\"p\"')"
        )
    upsert_invited_household_metadata(db_path, 8, "New", "dek", state="WA")
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT primary_state, onboarding_wizard_dismissed, collapsed_charts, login_count, "
            "local_passphrase_fek_enc, portable_vault_fek FROM families WHERE family_id = 8"
        ).fetchone()
    assert row == ("WA", 0, None, 0, None, None)
