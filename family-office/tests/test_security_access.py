"""
Security and Access Control Test Suite
Validates that:
1. Unauthorized users cannot view any data or bypass authentication.
2. Unauthenticated /api/auth/status returns null role and false.
3. OWASP security headers (CSP, X-Frame-Options, X-Content-Type-Options) are emitted.
4. Multi-tenant IDOR scoping protects records between families.
"""

from __future__ import annotations
import os
import io
import pytest
from wsgi import app
import security
from services.request_context import DB_PATH


def test_unauthenticated_api_endpoints_denied():
    """Confirms that unauthenticated visitors cannot access sensitive API endpoints."""
    client = app.test_client()
    endpoints = [
        "/api/dashboard",
        "/api/compensation",
        "/api/gifting",
        "/api/education",
        "/api/scenarios",
        "/api/holdings/policy",
        "/api/estate",
        "/api/philanthropy",
        "/api/family",
    ]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 401, f"Endpoint {ep} allowed unauthenticated access!"
        data = resp.get_json()
        assert data.get("error") == "Unauthorized"
        assert data.get("login_required") is True


def test_auth_status_unauthenticated():
    """Confirms /api/auth/status leaks no role or user info when unauthenticated."""
    client = app.test_client()
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["authenticated"] is False
    assert data["user"] is None
    assert data["role"] is None
    assert data["family_id"] is None


def test_owasp_security_headers_emitted():
    """Confirms all OWASP defensive security headers are emitted on HTTP responses."""
    client = app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200

    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in resp.headers


def test_multi_tenant_idor_member_deletion():
    """Confirms Family A cannot delete or modify family members belonging to Family B."""
    import config

    security.init_db(config.get_global_db_path())
    security.init_db(config.get_family_db_path(2))
    # Create test member in Family 2
    user_b_id = security.add_family_member(
        db_path=DB_PATH,
        family_id=2,
        name="Family B Member",
        email="b_member@example.com",
        relationship="child",
        role="viewer"
    )

    client = app.test_client()
    # Log in as Family 1 Editor
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Family A Editor"
        sess["role"] = "editor"
        sess["family_id"] = 1

    # Attempt to delete Family B's member
    resp_del = client.delete(f"/api/family/members/{user_b_id}")
    assert resp_del.status_code in (200, 400, 404)

    # Verify user_b still exists in Family 2
    members_fam2 = security.get_family_members(DB_PATH, family_id=2)
    member_ids_fam2 = [m["user_id"] for m in members_fam2]
    assert user_b_id in member_ids_fam2, "IDOR Vulnerability: Family 1 was able to delete Family 2's member!"

    # Clean up Family B member using Family 2 scope
    security.delete_family_member(DB_PATH, family_id=2, user_id=user_b_id)


def test_site_admin_rejects_unverified_heuristics_and_gates_universe_switch():
    """Verifies P0-6, F2, F8, F17 & S11: site-admin rejects family_id==1 heuristics and gates universe switch."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.clear()
        sess["authenticated"] = True
        sess["user"] = "Spoofed Tenant"
        sess["user_email"] = "not_an_admin@example.com"
        sess["family_id"] = 1
        sess["user_family_id"] = 1
        sess["role"] = "admin"
        sess["user_role"] = "admin"
        sess["universe"] = "public"

    assert client.get("/admin/bugs").status_code == 403
    assert client.get("/admin/release-review").status_code == 403
    res_switch = client.post(
        "/api/admin/switch_universe",
        json={"universe": "demo", "family_id": 1},
    )
    assert res_switch.status_code == 403


def test_beta_gate_rejects_spoofed_benchmark_headers_without_secret(monkeypatch):
    """Verifies S5: X-HVL-Benchmark: 1 and User-Agent: HVL-Benchmark cannot bypass beta gate in non-testing mode."""
    monkeypatch.setenv("HVL_BETA_INSTANCE", "1")
    monkeypatch.setenv("HVL_BENCHMARK_SECRET", "top_secret_benchmark_token_123")
    prev_testing = app.config.get("TESTING", True)
    app.config["TESTING"] = False
    try:
        client = app.test_client()
        r_spoof = client.get(
            "/features",
            headers={"X-HVL-Benchmark": "1", "User-Agent": "HVL-Benchmark/1.0"},
        )
        assert r_spoof.status_code == 302
        assert "/beta-gate" in r_spoof.headers.get("Location", "")

        r_api_spoof = client.get(
            "/api/auth/status",
            headers={"X-HVL-Benchmark": "1", "User-Agent": "HVL-Benchmark/1.0"},
        )
        assert r_api_spoof.status_code == 403

        r_valid = client.get(
            "/features",
            headers={"X-HVL-Benchmark-Secret": "top_secret_benchmark_token_123"},
        )
        assert r_valid.status_code == 200
    finally:
        app.config["TESTING"] = prev_testing


def test_zero_seed_on_init_db_and_pure_read_load_scenario_state(tmp_path):
    """Verifies FO-F1 & FO-F6: init_db does not seed family_id=1 ($350k), load_scenario_state does not mutate DB on read, and TaxProfile defaults to 0.0."""
    import sqlite3
    from forecast import storage as forecast_storage
    from services.tax_engine import TaxProfile
    from db.household_activity import provision_self_serve_household

    empty_db = tmp_path / "fresh_unseeded.db"
    security.init_db(empty_db)
    with sqlite3.connect(str(empty_db)) as conn:
        fam_count = conn.execute("SELECT COUNT(*) FROM families").fetchone()[0]
        comp_count = conn.execute("SELECT COUNT(*) FROM compensation").fetchone()[0]
    assert fam_count == 0
    assert comp_count == 0

    forecast_storage.DB_PATH.set_override(empty_db)
    try:
        state = forecast_storage.load_scenario_state(family_id=77)
    finally:
        forecast_storage.DB_PATH.set_override(None)
    assert isinstance(state, dict)
    with sqlite3.connect(str(empty_db)) as conn:
        scen_count = conn.execute("SELECT COUNT(*) FROM forecast_scenarios WHERE family_id = 77").fetchone()[0]
        evt_count = conn.execute("SELECT COUNT(*) FROM forecast_events WHERE family_id = 77").fetchone()[0]
    assert scen_count == 0, "Pure read load_scenario_state must not persist default scenarios to DB!"
    assert evt_count == 0, "Pure read load_scenario_state must not persist default events to DB!"

    tp = TaxProfile()
    assert tp.w2_base_salary == 0.0
    assert tp.w2_bonus == 0.0

    prov = provision_self_serve_household(empty_db, "zero_defaults@example.com", "Zero Defaults User")
    assert prov is not None
    with sqlite3.connect(str(empty_db)) as fconn:
        hp_row = fconn.execute(
            "SELECT annual_spending, annual_savings FROM household_profile WHERE family_id = ?",
            (prov["family_id"],),
        ).fetchone()
    assert hp_row is not None
    assert float(hp_row[0]) == 0.0
    assert float(hp_row[1]) == 0.0


def test_fovault_export_wraps_portable_fek_with_passphrase(tmp_path):
    """Format v2: scrypt + AES-256-GCM envelope with a random per-file salt; no plaintext or server-KEK key in the file."""
    import json
    import sqlite3
    import pytest
    from db.fovault_repo import (
        PORTABLE_VAULT_FEK_KEY,
        copy_sqlite_backup,
        extract_fek_from_backup_snapshot,
        inject_wrapped_fek_into_backup,
    )
    from hvl_common.security import WrongPassphrase

    src_db = tmp_path / "src_vault.db"
    security.init_db(src_db)
    fek = security.get_family_key(src_db, 1)
    backup_db = tmp_path / "exported.fovault"
    copy_sqlite_backup(src_db, backup_db)

    inject_wrapped_fek_into_backup(src_db, backup_db, family_id=1, passphrase="correct-horse-battery-staple")

    with sqlite3.connect(str(backup_db)) as sconn:
        raw_settings, enc_key = sconn.execute("SELECT settings, encryption_key_enc FROM families WHERE family_id = 1").fetchone()
    envelope = json.loads(raw_settings)[PORTABLE_VAULT_FEK_KEY]
    assert envelope["fovault_format"] == 2 and envelope["kdf"]["name"] == "scrypt" and envelope["cipher"] == "aes-256-gcm"
    assert enc_key is None
    assert fek.decode("utf-8") not in raw_settings

    with pytest.raises(WrongPassphrase):
        extract_fek_from_backup_snapshot(backup_db, passphrase="wrong-passphrase")
    assert extract_fek_from_backup_snapshot(backup_db, passphrase="correct-horse-battery-staple") == fek



def _lockable_household_db(tmp_path, fid: int):
    """Creates a per-family DB whose household counts as an initialized vault with support access ON."""
    import sqlite3

    db = tmp_path / "families" / f"{fid}.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    security.init_db(db)
    fek = security.get_family_key(db, fid)
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE families SET support_access_enabled = 1, name = 'gAAAAAplaceholder' WHERE family_id = ?", (fid,)
        )
    return db, fek


def _lock_vault_from_another_worker(db, fid: int) -> None:
    """Locks the vault the way a different gunicorn worker would: only the DB changes, not this process's cache."""
    import sqlite3

    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "UPDATE families SET support_access_enabled = 0, encryption_key_enc = NULL WHERE family_id = ?", (fid,)
        )


def test_cached_fek_is_dropped_when_another_worker_locks_the_vault(tmp_path):
    """F-SEC-1: a per-process cached FEK must not outlive Support Access being turned OFF by another worker."""
    import sqlite3

    db, fek = _lockable_household_db(tmp_path, 7)
    assert security.get_family_key(db, 7) == fek

    _lock_vault_from_another_worker(db, 7)
    with pytest.raises(PermissionError):
        security.get_family_key(db, 7)
    with sqlite3.connect(str(db)) as conn, pytest.raises(PermissionError):
        security.get_family_key(conn, 7)


def test_locked_vault_and_key_errors_never_fall_back_to_root_kek(tmp_path, monkeypatch):
    """F-SEC-2: column encryption raises on a locked vault, and key-resolution errors propagate instead of returning the root KEK."""
    import sqlite3
    import security.store as store
    from db.types import family_key_ring

    db, fek = _lockable_household_db(tmp_path, 8)
    assert family_key_ring(db, 8).split(b",")[0] == fek

    _lock_vault_from_another_worker(db, 8)
    with pytest.raises(PermissionError):
        family_key_ring(db, 8)

    def _db_unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "resolve_family_key_on_db_path", _db_unavailable)
    security._clear_security_caches()
    with pytest.raises(sqlite3.OperationalError):
        security.get_family_key(tmp_path / "families" / "9.db", 9)


def test_write_session_reads_root_kek_rows_after_the_rekey_pass(tmp_path):
    """C-4/F-SEC-11: the ring is household-only; legacy root-KEK rows read after the one-off re-encryption pass."""
    import sqlite3
    from sqlalchemy import select
    from db.models import AnnualGift, GiftRecipient
    from db.session import get_orm_session

    db, _fek = _lockable_household_db(tmp_path, 12)
    root_amount = security.encrypt_field(1234.5, key=security.get_or_create_key())
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO gift_recipients (recipient_id, family_id, recipient_group_name) VALUES (1, 12, 'Kids')"
        )
        conn.execute(
            "INSERT INTO gifts (family_id, recipient_id, year, amount) VALUES (12, 1, 2026, ?)", (root_amount,)
        )

    from db.vault_rekey import rekey_household_db

    rekey_household_db(db, 12, security._get_fernet(_fek), security._get_fernet(security.get_or_create_key()))
    for commit in (False, True):
        with get_orm_session(db, family_id=12, commit=commit) as session:
            assert session.scalars(select(GiftRecipient)).first() is not None
            assert session.scalars(select(AnnualGift)).one().amount == 1234.5


def test_support_access_peer_sync_mirrors_each_users_escrow(tmp_path):
    """F-SEC-1: peers mirror each member's pending_fek_enc exactly, so members who synced to Drive stay unescrowed."""
    import sqlite3
    from db.vault_support_access import sync_support_access_to_peers

    src = tmp_path / "families" / "11.db"
    peer = tmp_path / "global.db"
    src.parent.mkdir(parents=True, exist_ok=True)
    for path in (src, peer):
        security.init_db(path)
        with sqlite3.connect(str(path)) as conn:
            conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (11, 'h')")
            conn.execute("INSERT INTO users (user_id, family_id, name) VALUES (101, 11, 'a'), (102, 11, 'b')")
    with sqlite3.connect(str(src)) as conn:
        conn.execute("UPDATE users SET pending_fek_enc = 'gAAAAAwrapped' WHERE user_id = 101")
    with sqlite3.connect(str(peer)) as conn:
        conn.execute("UPDATE users SET pending_fek_enc = 'gAAAAAstale' WHERE user_id = 102")

    sync_support_access_to_peers(src, 11, [peer])

    with sqlite3.connect(str(peer)) as conn:
        rows = dict(conn.execute("SELECT user_id, pending_fek_enc FROM users WHERE family_id = 11").fetchall())
    assert rows == {101: "gAAAAAwrapped", 102: None}


def test_household_job_results_never_encrypt_under_root_kek(tmp_path, monkeypatch):
    """F-SEC-2: background job tickets for a household fail closed when its FEK is unavailable."""
    from services import background_jobs

    db, _ = _lockable_household_db(tmp_path, 12)
    _lock_vault_from_another_worker(db, 12)
    monkeypatch.setattr(background_jobs, "_resolve_job_primary_db_path", lambda universe=None, family_id=0: db)

    with pytest.raises(PermissionError):
        background_jobs._make_job_encrypt_fn(12, "public")(b"advisor reply")
    root_token = security._get_fernet(None).encrypt(b"legacy")
    with pytest.raises(PermissionError):
        background_jobs._make_job_decrypt_fn(12, "public")(root_token)


def test_disabling_support_access_never_escrows_drive_synced_members(tmp_path):
    """§10: turning Support Access OFF escrows only members who have not synced to Drive, using sync flags from either DB."""
    import sqlite3
    from db.vault_support_access import adopt_peer_vault_sync_flags, disable_family_support_access_in_db

    fam_db = tmp_path / "families" / "21.db"
    global_db = tmp_path / "global.db"
    fam_db.parent.mkdir(parents=True, exist_ok=True)
    for path in (fam_db, global_db):
        security.init_db(path)
        with sqlite3.connect(str(path)) as conn:
            conn.execute("INSERT OR IGNORE INTO families (family_id, name, support_access_enabled) VALUES (21, 'h', 1)")
            conn.execute("INSERT INTO users (user_id, family_id, name) VALUES (201, 21, 'a'), (202, 21, 'b'), (203, 21, 'c')")
    with sqlite3.connect(str(fam_db)) as conn:
        conn.execute("UPDATE users SET google_vault_synced = 1 WHERE user_id = 201")
    with sqlite3.connect(str(global_db)) as conn:
        # Synced at login before the family DB learned about it (stale per-family copy)
        conn.execute("UPDATE users SET google_vault_synced = 1 WHERE user_id = 202")

    adopt_peer_vault_sync_flags(fam_db, 21, [global_db])
    disable_family_support_access_in_db(fam_db, 21, "gAAAAAwrapped")

    with sqlite3.connect(str(fam_db)) as conn:
        rows = dict(conn.execute("SELECT user_id, pending_fek_enc FROM users WHERE family_id = 21").fetchall())
        fam = conn.execute("SELECT support_access_enabled, encryption_key_enc FROM families WHERE family_id = 21").fetchone()
    assert rows == {201: None, 202: None, 203: "gAAAAAwrapped"}
    assert fam == (0, None)


def test_household_job_submit_fails_closed_on_locked_vault(tmp_path, monkeypatch):
    """A job for a locked household is refused at submit time instead of running and silently dropping its ticket."""
    from services import background_jobs

    db, _ = _lockable_household_db(tmp_path, 22)
    _lock_vault_from_another_worker(db, 22)
    monkeypatch.setattr(background_jobs, "_resolve_job_primary_db_path", lambda universe=None, family_id=0: db)
    with pytest.raises(PermissionError):
        background_jobs.submit_job(lambda: "never runs", family_id=22, universe="public", job_type="unit_test_job")


def test_locked_vault_reads_return_every_pooled_connection(tmp_path):
    """
    A locked vault raises on every encrypted read. Each failed key resolution must hand its pooled
    connection back even while the exception (and its traceback) is still referenced; otherwise
    24 reads exhaust the household DB's pool and every later query blocks.
    """
    from hvl_common.db.sqlite import get_engine
    from db.types import family_key_ring

    db, _ = _lockable_household_db(tmp_path, 23)
    _lock_vault_from_another_worker(db, 23)
    pool = get_engine(db).pool

    held_errors = []
    for _ in range(40):
        try:
            family_key_ring(db, 23)
        except PermissionError as exc:
            held_errors.append(exc)

    assert len(held_errors) == 40
    assert pool.checkedout() == 0


def test_session_auth_sync_does_not_write_legacy_monolithic(tmp_path: Path):
    from db.models import Family
    from db.session import get_orm_session

    uni_dir = tmp_path / "universe"
    fam_dir = uni_dir / "families"
    fam_dir.mkdir(parents=True)
    src_db = fam_dir / "1.db"
    legacy_db = uni_dir / "family_office.db"
    legacy_db.touch()

    security.init_db(src_db)
    with get_orm_session(src_db, family_id=1, commit=True) as sess:
        fam = sess.get(Family, 1)
        if fam is not None:
            fam.name = "Synced Family"
        else:
            sess.add(Family(family_id=1, name="Synced Family"))

    # Assert global.db was created/synced as expected
    global_db = uni_dir / "global.db"
    assert global_db.exists()

    # Assert legacy family_office.db was NOT mutated/initialized into a peer
    assert legacy_db.stat().st_size == 0
