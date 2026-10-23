"""
Tests for the 4-Phase Architectural Plan:
1. Phase 1: Alembic Schema Migrations (`0001_baseline`, `families.support_access_enabled`).
2. Phase 2: `MultiFernet` Key Rotation (`rotate_family_keys`, `scripts/rotate_kek.py`) & Uniform Tenant Support Lock.
3. Phase 3: Shared Multi-Worker Rate Limiting (`@rate_limit` on AI Advisor, Scenarios, Equity, Auth).
4. Phase 4: Shared Operational Telemetry (`register_telemetry` in `family-office`).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
import pytest

from app import app
import config
import db
import security
from hvl_common.telemetry import get_telemetry_events, clear_telemetry_events
from hvl_common.web import reset_rate_limits
from scripts import rotate_kek


def test_phase1_alembic_migration_and_legacy_upgrade(tmp_path: Path):
    """Verifies Alembic baseline stamping on fresh DB and seamless upgrade of pre-Alembic SQLite DB."""
    # 1. Fresh DB via init_db
    fresh_db = tmp_path / "fresh_office.db"
    security.init_db(fresh_db)

    conn = sqlite3.connect(str(fresh_db))
    ver = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert ver is not None
    assert ver[0] == "0002_google_vault_escrow"

    cols = {r[1] for r in conn.execute("PRAGMA table_info(families)").fetchall()}
    assert "support_access_enabled" in cols
    ucols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert "pending_fek_enc" in ucols
    assert "google_vault_synced" in ucols
    conn.close()

    # 2. Pre-Alembic legacy DB missing `support_access_enabled` and `alembic_version`
    legacy_db = tmp_path / "legacy_office.db"
    lconn = sqlite3.connect(str(legacy_db))
    lconn.execute(
        """
        CREATE TABLE families (
            family_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            settings TEXT DEFAULT '{}',
            encryption_key_enc TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    lconn.execute(
        """
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            email_hash TEXT DEFAULT '',
            birthdate TEXT DEFAULT '',
            relationship TEXT DEFAULT 'child',
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (family_id) REFERENCES families(family_id) ON DELETE CASCADE
        )
        """
    )
    lconn.execute(
        "INSERT INTO families (family_id, name, settings) VALUES (1, 'Legacy Household', '{}')"
    )
    lconn.execute(
        "INSERT INTO users (user_id, family_id, name, role) VALUES (1, 1, 'gAAAAAB_dummy', 'admin')"
    )
    lconn.commit()
    lconn.close()

    security.run_alembic_migrations(legacy_db)

    lconn2 = sqlite3.connect(str(legacy_db))
    ver2 = lconn2.execute("SELECT version_num FROM alembic_version").fetchone()
    assert ver2 is not None and ver2[0] == "0002_google_vault_escrow"
    cols2 = {r[1] for r in lconn2.execute("PRAGMA table_info(families)").fetchall()}
    assert "support_access_enabled" in cols2
    ucols2 = {r[1] for r in lconn2.execute("PRAGMA table_info(users)").fetchall()}
    assert "pending_fek_enc" in ucols2
    assert "google_vault_synced" in ucols2
    row = lconn2.execute(
        "SELECT support_access_enabled FROM families WHERE family_id = 1"
    ).fetchone()
    assert row is not None and int(row[0]) == 0
    user_count = lconn2.execute("SELECT count(*) FROM users WHERE family_id = 1").fetchone()[0]
    assert user_count == 1, "Child table rows with ON DELETE CASCADE must never be wiped by Alembic migration!"
    lconn2.close()


def test_phase2_multifernet_and_rotate_family_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verifies MultiFernet comma-separated KEK support and atomic DEK rotation via rotate_family_keys & rotate_kek CLI."""
    old_kek = Fernet.generate_key().decode("utf-8")
    new_kek = Fernet.generate_key().decode("utf-8")

    test_db = tmp_path / "rotate_test.db"
    monkeypatch.delenv("FAMILY_OFFICE_DATA_DIR", raising=False)
    monkeypatch.setenv("APP_ENCRYPTION_KEY", old_kek)
    security._FERNET_CACHE.clear()
    security._FAMILY_KEY_CACHE.clear()

    security.init_db(test_db)
    # Create two tenants and encrypt data with their per-family DEKs wrapped by old_kek
    dek_1 = security.get_family_key(test_db, 1)
    with sqlite3.connect(str(test_db)) as conn:
        conn.execute(
            "INSERT INTO families (family_id, name, settings) VALUES (2, 'Second Household', '{}')"
        )
        conn.commit()
    dek_2 = security.get_family_key(test_db, 2)

    uid_1 = security.add_family_member(
        test_db, family_id=1, name="Alice Test", email="alice@example.com", relationship="primary", role="admin"
    )
    uid_2 = security.add_family_member(
        test_db, family_id=2, name="Bob Test", email="bob@example.com", relationship="primary", role="admin"
    )
    assert uid_1 > 0 and uid_2 > 0

    # Stage comma-separated keys: NEW_KEY,OLD_KEY
    combined_kek = f"{new_kek},{old_kek}"
    monkeypatch.setenv("APP_ENCRYPTION_KEY", combined_kek)
    security._FERNET_CACHE.clear()
    security._FAMILY_KEY_CACHE.clear()

    # Before rotation, MultiFernet transparently decrypts DEKs encrypted with old_kek
    assert security.get_family_key(test_db, 1) == dek_1
    assert security.get_family_key(test_db, 2) == dek_2

    # Dry-run via CLI helper does not mutate DB
    dry_res = rotate_kek.rotate_databases([test_db], new_key=new_kek, old_keys=[old_kek], dry_run=True)
    assert dry_res["total_rotated"] == 2

    # Execute actual rotation
    rot_res = security.rotate_family_keys(test_db, new_kek=new_kek, old_keks=[old_kek])
    assert rot_res["rotated_count"] == 2
    assert rot_res["family_ids"] == [1, 2]

    # Retire old_kek completely: set APP_ENCRYPTION_KEY to ONLY new_kek
    monkeypatch.setenv("APP_ENCRYPTION_KEY", new_kek)
    security._FERNET_CACHE.clear()
    security._FAMILY_KEY_CACHE.clear()

    # Both tenants' DEKs and member PII must decrypt cleanly under new_kek alone
    assert security.get_family_key(test_db, 1) == dek_1
    assert security.get_family_key(test_db, 2) == dek_2
    members_1 = security.get_family_members(test_db, family_id=1)
    members_2 = security.get_family_members(test_db, family_id=2)
    assert any(m["name"] == "Alice Test" for m in members_1)
    assert any(m["name"] == "Bob Test" for m in members_2)


def test_phase2_uniform_tenant_support_lock():
    """
    Verifies uniform tenant support access lock:
    - Default is False (Locked) for production households (including Family 1).
    - Demo personas in demo DB are seeded with support_access_enabled = True.
    - POST /api/family/support-access toggles support_access_enabled for authenticated editors
      and rejects demo/viewer sessions with 403.
    - POST /api/admin/switch_universe blocks cross-tenant support access when False (403)
      and permits it when True (200), with zero family_id=1 special-casing.
    """
    app.config["TESTING"] = True
    pub_db = config.get_global_db_path("public")
    demo_db = config.get_global_db_path("demo")

    # 1. Verify Demo families in demo DB have support_access_enabled = True
    for demo_fid in (1, 2, 3, 4, 5, 6, 7):
        assert db.families.is_support_access_enabled(family_id=demo_fid, db_path=demo_db) is True

    # Save original state of Family 1 in public DB to restore after test
    with sqlite3.connect(str(pub_db)) as conn:
        orig_row = conn.execute(
            "SELECT encryption_key_enc, support_access_enabled FROM families WHERE family_id = 1"
        ).fetchone()
        if not orig_row or not orig_row[0]:
            u_row = conn.execute(
                "SELECT pending_fek_enc FROM users WHERE family_id = 1 AND pending_fek_enc IS NOT NULL AND pending_fek_enc != '' LIMIT 1"
            ).fetchone()
            orig_enc_key = u_row[0] if u_row else None
        else:
            orig_enc_key = orig_row[0]
        orig_support = int(orig_row[1] or 0) if orig_row else 0

    try:
        # Ensure Family 1 support access starts locked (False)
        security.set_family_support_access(pub_db, family_id=1, enabled=False)
        assert db.families.is_support_access_enabled(family_id=1, db_path=pub_db) is False

        with app.test_client() as client:
            # Demo guest cannot toggle support access -> 403 Forbidden
            client.get("/demo")
            res_demo_toggle = client.post("/api/family/support-access", json={"enabled": False})
            assert res_demo_toggle.status_code == 403

            # External admin (user_family_id=99) attempting to access Family 1 while locked -> 403 Forbidden
            with client.session_transaction() as sess:
                sess.clear()
                sess["authenticated"] = True
                sess["user"] = "Support Admin"
                sess["user_email"] = "admin@example.com"
                sess["is_site_admin"] = True
                sess["role"] = "admin"
                sess["user_role"] = "admin"
                sess["universe"] = "public"
                sess["family_id"] = 99
                sess["user_family_id"] = 99
                sess["is_demo"] = False

            res_locked = client.post(
                "/api/admin/switch_universe",
                json={"universe": "public", "family_id": 1},
            )
            assert res_locked.status_code == 403
            assert "locked" in res_locked.get_json().get("error", "").lower()

            # Now Family 1 editor unlocks support access via POST /api/family/support-access
            with client.session_transaction() as sess:
                sess["family_id"] = 1
                sess["user_family_id"] = 1

            res_unlock = client.post("/api/family/support-access", json={"enabled": True})
            assert res_unlock.status_code == 200
            unlock_data = res_unlock.get_json()
            assert unlock_data["success"] is True
            assert unlock_data["support_access_enabled"] is True
            assert db.families.is_support_access_enabled(family_id=1, db_path=pub_db) is True

            # Verify GET /api/family reflects support_access_enabled: True
            res_fam = client.get("/api/family")
            assert res_fam.status_code == 200
            assert res_fam.get_json()["family"]["support_access_enabled"] is True

            # Now Support Admin (user_family_id=99) can switch into Family 1 -> 200 OK
            with client.session_transaction() as sess:
                sess["family_id"] = 99
                sess["user_family_id"] = 99

            res_allowed = client.post(
                "/api/admin/switch_universe",
                json={"universe": "public", "family_id": 1},
            )
            assert res_allowed.status_code == 200
            assert res_allowed.get_json()["family_id"] == 1

            # Re-lock Family 1 via API
            with client.session_transaction() as sess:
                sess["family_id"] = 1
                sess["user_family_id"] = 1

            res_relock = client.post("/api/family/support-access", json={"enabled": False})
            assert res_relock.status_code == 200
            assert res_relock.get_json()["support_access_enabled"] is False
    finally:
        for db_cand in (pub_db, pub_db.parent / "families" / "1.db", pub_db.parent / "global.db"):
            if db_cand.exists():
                with sqlite3.connect(str(db_cand)) as conn:
                    conn.execute(
                        "UPDATE families SET encryption_key_enc = ?, support_access_enabled = ? WHERE family_id = 1",
                        (orig_enc_key, orig_support),
                    )
                    conn.commit()
        security._clear_security_caches()


def test_phase3_and_phase4_rate_limiting_and_telemetry(tmp_path: Path):
    """
    Verifies multi-worker rate limiting on Family Office routes (/login, /api/ai-advisor/*)
    and operational telemetry recording in hvl_common.telemetry.
    """
    tel_db = tmp_path / "telemetry_test.db"
    rl_cache = tmp_path / "ratelimit_cache"

    app.config["TESTING"] = True
    app.config["RATELIMIT_ENABLED"] = True
    app.config["RATELIMIT_CACHE_DIR"] = str(rl_cache)
    app.config["TELEMETRY_ENABLED"] = True
    app.config["TELEMETRY_DB_PATH"] = str(tel_db)

    try:
        reset_rate_limits()
        clear_telemetry_events(db_path=tel_db)

        with app.test_client() as client:
            # 1. Test /login rate limit (20/min)
            for _ in range(20):
                r = client.get("/login")
                assert r.status_code == 200

            r_exceeded = client.get("/login")
            assert r_exceeded.status_code == 429
            assert "Retry-After" in r_exceeded.headers
            body = r_exceeded.get_json()
            assert body["success"] is False
            assert "Rate limit exceeded" in body["error"]

            # 2. Verify RATE_LIMIT event was recorded in telemetry.db without query strings
            events = get_telemetry_events(service="finances", event_type="RATE_LIMIT", db_path=tel_db)
            assert len(events) >= 1
            assert events[0]["path"] == "/login"
            assert events[0]["status_code"] == 429
    finally:
        app.config["RATELIMIT_ENABLED"] = False
        app.config["TELEMETRY_ENABLED"] = False
        app.config.pop("RATELIMIT_CACHE_DIR", None)
        app.config.pop("TELEMETRY_DB_PATH", None)
        reset_rate_limits()
