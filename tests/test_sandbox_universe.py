"""
Automated Verification for Sandbox Mode Universe Routing, Ephemeral Lifecycle,
Rate Limits, Single-Browser De-scoping, and Multi-Universe Telemetry.
"""

from __future__ import annotations

import io
import json
import sqlite3
import time
from pathlib import Path

import pytest
from app import app
import config
import security
from db.telemetry import (
    record_portal_telemetry_event,
    get_portal_telemetry_summary,
)
from services import sandbox_service


@pytest.fixture(autouse=True)
def _reset_security_caches():
    security._clear_security_caches()
    yield
    security._clear_security_caches()


def test_sandbox_service_lifecycle(tmp_path, monkeypatch):
    """Verifies creation, lease inspection, 7-day extension, reaping, and instant wipe in sandbox_service."""
    monkeypatch.setattr(config, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_global_db_path", lambda universe="public": tmp_path / (config.normalize_universe(universe) if hasattr(config, "normalize_universe") else universe) / "global.db")
    monkeypatch.setattr(config, "get_family_db_path", lambda fid, universe="public": tmp_path / (config.normalize_universe(universe) if hasattr(config, "normalize_universe") else universe) / "families" / f"{fid}.db")

    # 1. Create fresh sandbox
    fid, raw_fek, expires_at = sandbox_service.create_sandbox_session(seed_mode="fresh")
    assert fid > 0
    assert len(raw_fek) > 10
    assert expires_at > int(time.time())

    fam_db = config.get_family_db_path(fid, universe="sandbox")
    assert fam_db.exists()

    # Zero Data Retained Invariant: encryption_key_enc MUST be NULL on disk
    with sqlite3.connect(fam_db) as conn:
        row = conn.execute("SELECT encryption_key_enc, support_access_enabled FROM families WHERE family_id = ?", (fid,)).fetchone()
        assert row is not None
        assert row[0] is None
        assert row[1] == 0

    # 2. Inspect Lease
    lease = sandbox_service.get_sandbox_lease_info(fid)
    assert lease is not None
    assert lease["family_id"] == fid
    assert lease["extended_7d"] is False
    assert lease["remaining_seconds"] > 86000

    # 3. Extend Lease to 7 days
    ext_lease = sandbox_service.extend_sandbox_lease_7d(fid)
    assert ext_lease is not None
    assert ext_lease["extended_7d"] is True
    assert ext_lease["remaining_seconds"] > (6 * 86400)

    # 4. Wipe Immediately
    wiped = sandbox_service.wipe_sandbox_immediately(fid)
    assert wiped is True
    assert not fam_db.exists()
    assert sandbox_service.get_sandbox_lease_info(fid) is None


def test_sandbox_service_reaper(tmp_path, monkeypatch):
    """Verifies that expired sandboxes are purged by reap_expired_sandboxes."""
    monkeypatch.setattr(config, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_global_db_path", lambda universe="public": tmp_path / (config.normalize_universe(universe) if hasattr(config, "normalize_universe") else universe) / "global.db")
    monkeypatch.setattr(config, "get_family_db_path", lambda fid, universe="public": tmp_path / (config.normalize_universe(universe) if hasattr(config, "normalize_universe") else universe) / "families" / f"{fid}.db")

    fid, raw_fek, expires_at = sandbox_service.create_sandbox_session(seed_mode="fresh")
    fam_db = config.get_family_db_path(fid, universe="sandbox")
    assert fam_db.exists()

    # Artificially expire the sandbox in global.db (sandbox_leases table)
    gdb = config.get_global_db_path("sandbox")
    with sqlite3.connect(gdb) as conn:
        conn.execute("UPDATE sandbox_leases SET expires_at = ? WHERE family_id = ?", (int(time.time()) - 3600, fid))
        conn.commit()

    reaped = sandbox_service.reap_expired_sandboxes()
    assert reaped >= 1
    assert not fam_db.exists()


def test_sandbox_http_flow():
    """Verifies launching, status inspection, extension, mutation, and wipe via HTTP."""
    app.config["TESTING"] = True
    client = app.test_client()

    # 1. Launch Sandbox
    launch_res = client.post("/api/sandbox/launch", json={"seed_mode": "fresh"})
    assert launch_res.status_code == 200
    launch_data = launch_res.get_json()
    assert launch_data["success"] is True
    assert launch_data["family_id"] > 0
    assert "redirect" in launch_data

    # Vault cookie should be set
    cookie_header = launch_res.headers.get("Set-Cookie", "")
    assert "vault_fek=" in cookie_header

    # 2. Inspect Status
    status_res = client.get("/api/sandbox/status")
    assert status_res.status_code == 200
    status_data = status_res.get_json()
    assert status_data["is_sandbox"] is True
    assert status_data["lease"] is not None
    assert status_data["lease"]["remaining_seconds"] > 0

    # 3. Extend Lease
    extend_res = client.post("/api/sandbox/extend")
    assert extend_res.status_code == 200
    extend_data = extend_res.get_json()
    assert extend_data["success"] is True
    assert extend_data["extended_7d"] is True

    # 4. De-scoping Restrictions: Invites and Support Access must return 403
    invite_res = client.post("/api/family/invites", json={"email": "guest@test.local", "role": "editor"})
    assert invite_res.status_code == 403
    assert "Not available in single-browser Sandbox Mode" in invite_res.get_json().get("error", "")

    support_res = client.post("/api/family/support-access", json={"enabled": True})
    assert support_res.status_code == 403
    assert "Not available in single-browser Sandbox Mode" in support_res.get_json().get("error", "")

    # 5. Wipe Sandbox
    wipe_res = client.post("/api/sandbox/wipe")
    assert wipe_res.status_code == 200
    wipe_data = wipe_res.get_json()
    assert wipe_data["success"] is True


def test_sandbox_vault_roundtrip():
    """Verifies that downloading and restoring a vault (.fovault) in sandbox mode works smoothly."""
    app.config["TESTING"] = True
    client = app.test_client()

    # Launch Sandbox
    launch_res = client.post("/api/sandbox/launch", json={"seed_mode": "fresh"})
    assert launch_res.status_code == 200
    fid = launch_res.get_json()["family_id"]

    # Backup vault (.fovault)
    backup_res = client.get("/api/sandbox/download-vault")
    assert backup_res.status_code == 200
    vault_bytes = backup_res.data
    assert len(vault_bytes) > 100
    assert vault_bytes.startswith(b"SQLite format 3\x00")

    # Restore vault
    data = {"file": (io.BytesIO(vault_bytes), "vault.fovault")}
    restore_res = client.post("/api/desktop/restore", data=data, content_type="multipart/form-data")
    assert restore_res.status_code == 200
    assert restore_res.get_json()["success"] is True

    # Ensure encryption_key_enc is still NULL on disk (Zero Data Retained)
    fam_db = config.get_family_db_path(fid, universe="sandbox")
    with sqlite3.connect(fam_db) as conn:
        row = conn.execute("SELECT encryption_key_enc FROM families WHERE family_id = ?", (fid,)).fetchone()
        assert row is not None
        assert row[0] is None


def test_sandbox_monte_carlo_trials_clamping(monkeypatch):
    """Verifies that Monte Carlo simulation trials are clamped to 1000 in sandbox mode."""
    from routes import helpers
    from forecast import monte_carlo
    monkeypatch.setattr(helpers, "is_sandbox_session", lambda: True)

    fake_sim_base = {
        "success": True,
        "scenarios": [{"id": "scen_baseline", "weight_us_equity": 0.6, "weight_intl_equity": 0.2, "weight_bonds": 0.2}],
        "active_scenario_id": "scen_baseline",
        "active_schedule": [
            {"year": 2026, "age": 40, "total_net_worth": 1000000.0, "total_liquid_assets": 800000.0, "living_expenses": 50000.0, "tax_liability": 10000.0, "earned_income": 120000.0}
        ],
        "scorecard": [{"id": "scen_baseline", "portfolio_balance": 1000000.0}],
    }
    res = monte_carlo.run_monte_carlo_simulation(family_id=1, trials=3000, precomputed_sim=fake_sim_base)
    assert res["success"] is True
    assert res["trials"] == 1000


def test_sandbox_local_mode_guards(monkeypatch):
    """Verifies that sandbox endpoints return 404 in Local Desktop Mode."""
    monkeypatch.setattr(config, "is_local_mode", lambda: True)

    app.config["TESTING"] = True
    client = app.test_client()

    res = client.get("/sandbox")
    assert res.status_code == 404

    res2 = client.post("/api/sandbox/launch", json={"seed_mode": "fresh"})
    assert res2.status_code == 404

    res3 = client.get("/api/sandbox/status")
    assert res3.status_code == 404


def test_portal_telemetry_recording(tmp_path, monkeypatch):
    """Verifies multi-universe telemetry recording and summarization."""
    t_db = tmp_path / "telemetry_test.db"

    # Record some events across universes
    record_portal_telemetry_event(universe="sandbox", event_type="sandbox_started", db_path=t_db)
    record_portal_telemetry_event(universe="sandbox", event_type="fovault_downloaded", db_path=t_db)
    record_portal_telemetry_event(universe="sandbox", event_type="tab_visit", feature_key="scenarios", tab="scenarios", db_path=t_db)
    record_portal_telemetry_event(universe="public", event_type="monarch_sync", db_path=t_db, meta={"accounts": 5})
    record_portal_telemetry_event(universe="public", event_type="ai_shared_call", db_path=t_db, meta={"model": "gemini-2.5-flash"})
    record_portal_telemetry_event(universe="demo", event_type="demo_view", db_path=t_db)

    summary = get_portal_telemetry_summary(db_path=t_db, days=1)
    assert "by_universe" in summary
    assert "sandbox" in summary["by_universe"]
    assert summary["sandbox_lifecycle"]["started"] >= 1
    assert summary["sandbox_lifecycle"]["fovault_downloaded"] >= 1
    assert summary["ai_usage"]["shared_calls"] >= 1

    import sqlite3
    with sqlite3.connect(str(t_db)) as conn:
        row = conn.execute("SELECT universe, event_type, tab, feature_key FROM portal_telemetry_events WHERE tab = 'scenarios'").fetchone()
        assert row is not None
        assert row[0] == "sandbox"
        assert row[1] == "tab_visit"
        assert row[2] == "scenarios"


def test_api_telemetry_action_endpoint(tmp_path, monkeypatch):
    from wsgi import app
    client = app.test_client()
    t_db = tmp_path / "global.db"
    monkeypatch.setattr("config.get_global_db_path", lambda u="public": t_db)

    resp = client.post("/api/telemetry/action?sandbox=1", json={
        "action": "run_monte_carlo",
        "tab": "scenarios",
        "modal": "add_scenario",
        "feature_key": "monte_carlo",
    })
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    import sqlite3
    with sqlite3.connect(str(t_db)) as conn:
        row = conn.execute("SELECT universe, event_type, action, tab, modal FROM portal_telemetry_events WHERE action = 'run_monte_carlo'").fetchone()
        assert row is not None
        assert row[0] == "sandbox"
        assert row[1] == "action"
        assert row[2] == "run_monte_carlo"
        assert row[3] == "scenarios"
        assert row[4] == "add_scenario"



def test_fovault_cross_table_remapping_and_cloud_desktop_portability(tmp_path, monkeypatch):
    """
    Verifies that a .fovault exported with one family_id (and a different server KEK)
    can be restored into a Sandbox session with a completely different family_id AND
    into Local Desktop Mode (family_id=1), preserving and decrypting all domain tables.
    """
    from cryptography.fernet import Fernet

    # 1. Create a sandbox household and populate encrypted domain tables
    app.config["TESTING"] = True
    client = app.test_client()
    launch_res = client.post("/api/sandbox/launch", json={"template": "miller"})
    assert launch_res.status_code == 200
    src_fid = launch_res.get_json()["family_id"]

    backup_res = client.get("/api/sandbox/download-vault")
    assert backup_res.status_code == 200
    vault_bytes = backup_res.data
    assert vault_bytes.startswith(b"SQLite format 3\x00")

    # 2. Simulate restoring that .fovault on a DIFFERENT machine (different root KEK!) into a new sandbox
    different_kek = Fernet.generate_key()
    monkeypatch.setattr(security, "get_or_create_key", lambda: different_kek)

    new_fid, restored_fek, _ = sandbox_service.restore_sandbox_from_fovault_bytes(vault_bytes)
    assert new_fid != src_fid
    assert restored_fek is not None

    restored_db = config.get_family_db_path(new_fid, universe="sandbox")
    with sqlite3.connect(restored_db) as conn:
        # All domain rows must be remapped to new_fid (zero rows left with src_fid or 1)
        acct_count = conn.execute("SELECT COUNT(*) FROM monarch_accounts WHERE family_id = ?", (new_fid,)).fetchone()[0]
        old_acct_count = conn.execute("SELECT COUNT(*) FROM monarch_accounts WHERE family_id != ?", (new_fid,)).fetchone()[0]
        assert acct_count > 0
        assert old_acct_count == 0

        # Ensure encryption_key_enc and _portable_vault_fek_b64 are scrubbed on disk in sandbox DB
        fam_row = conn.execute("SELECT name, encryption_key_enc, settings FROM families WHERE family_id = ?", (new_fid,)).fetchone()
        assert fam_row[1] is None
        assert sandbox_service.PORTABLE_VAULT_FEK_KEY not in (fam_row[2] or "")

        # Verify restored_fek actually decrypts the household name and account names
        dec_name = security.decrypt_field(fam_row[0], default="", key=restored_fek)
        assert "Miller" in dec_name

    # 3. Verify sample_data/sample_family_vault.fovault restores cleanly via /api/sandbox/restore_async
    sample_vault = Path(__file__).resolve().parent.parent / "sample_data" / "sample_family_vault.fovault"
    assert sample_vault.exists()
    sample_bytes = sample_vault.read_bytes()

    restore_http = client.post(
        "/api/sandbox/restore_async",
        data={"backup_file": (io.BytesIO(sample_bytes), "sample_family_vault.fovault")},
        content_type="multipart/form-data",
    )
    assert restore_http.status_code == 200
    r_json = restore_http.get_json()
    assert r_json["success"] is True
    assert "summary" in r_json
    assert r_json["summary"]["accounts"] == 7
    assert r_json["summary"]["members"] == 2
    assert r_json["summary"]["scenarios"] == 4
    assert "7 financial accounts" in r_json["summary"]["summary_text"]

    # Cleanup test sandboxes
    sandbox_service.wipe_sandbox_immediately(src_fid)
    sandbox_service.wipe_sandbox_immediately(new_fid)


def test_untouched_sandbox_reaper_eviction(tmp_path, monkeypatch):
    """Verifies that untouched (empty) sandboxes older than SANDBOX_UNTOUCHED_TTL_SECONDS are reaped automatically."""
    monkeypatch.setattr(config, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_global_db_path", lambda universe="public": tmp_path / (config.normalize_universe(universe) if hasattr(config, "normalize_universe") else universe) / "global.db")
    monkeypatch.setattr(config, "get_family_db_path", lambda fid, universe="public": tmp_path / (config.normalize_universe(universe) if hasattr(config, "normalize_universe") else universe) / "families" / f"{fid}.db")

    fid, _, _ = sandbox_service.create_sandbox_session(seed_mode="blank")
    assert sandbox_service.has_sandbox_user_data(fid) is False

    # Backdate created_at by 3 hours (while expires_at is still +21 hours in the future)
    gdb = config.get_global_db_path("sandbox")
    now_ts = int(time.time())
    with sqlite3.connect(gdb) as conn:
        conn.execute(
            "UPDATE sandbox_leases SET created_at = ?, expires_at = ? WHERE family_id = ?",
            (now_ts - (3 * 3600), now_ts + (21 * 3600), fid),
        )
        conn.commit()

    reaped = sandbox_service.reap_expired_sandboxes()
    assert reaped == 1
    assert not config.get_family_db_path(fid, universe="sandbox").exists()


def test_sandbox_to_cloud_vault_migration_and_restore(tmp_path, monkeypatch):
    """Verifies direct in-session Sandbox -> Cloud Vault upgrade and Cloud Vault .fovault restore re-encrypt under the Cloud FEK and preserve Google auth."""
    from db.household_activity import provision_self_serve_household
    from services.fovault_service import apply_fovault_restore_to_db, build_fovault_backup_bytes, migrate_active_sandbox_to_cloud_vault

    monkeypatch.setattr(config, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_global_db_path", lambda universe="public": tmp_path / (config.normalize_universe(universe) if hasattr(config, "normalize_universe") else universe) / "global.db")
    monkeypatch.setattr(config, "get_family_db_path", lambda fid, universe="public": tmp_path / (config.normalize_universe(universe) if hasattr(config, "normalize_universe") else universe) / "families" / f"{fid}.db")

    sb_fid, sb_fek, _ = sandbox_service.create_sandbox_session(seed_mode="miller")
    sb_db = config.get_family_db_path(sb_fid, "sandbox")
    security._FAMILY_KEY_CACHE[(str(sb_db.resolve()), sb_fid)] = sb_fek
    portable_bytes, _ = build_fovault_backup_bytes(sb_db, sb_fid, is_sandbox=True, is_local=False)

    global_db = config.get_global_db_path("public")
    security.init_db(global_db)
    user_info = provision_self_serve_household(global_db, user_email="cloud.migrator@example.com", user_name="Cloud Migrator")
    cloud_fid = int(user_info["family_id"])
    cloud_db = config.get_family_db_path(cloud_fid, "public")
    cloud_fek = security._get_fernet(security.get_or_create_key()).decrypt(str(user_info["pending_fek_enc"]).encode("utf-8"))

    assert migrate_active_sandbox_to_cloud_vault(sb_fid, sb_fek, cloud_fid, cloud_fek, force_overwrite=True) is True
    assert not sb_db.exists()

    with sqlite3.connect(cloud_db) as conn:
        fam_name_enc = conn.execute("SELECT name FROM families WHERE family_id = ?", (cloud_fid,)).fetchone()[0]
        assert "Miller" in security.decrypt_field(fam_name_enc, default="", key=cloud_fek)
        assert conn.execute("SELECT COUNT(*) FROM monarch_accounts WHERE family_id = ?", (cloud_fid,)).fetchone()[0] > 0
        u_row = conn.execute("SELECT email_hash, role FROM users WHERE family_id = ? AND relationship = 'primary'", (cloud_fid,)).fetchone()
        assert u_row[0] == security.hash_email("cloud.migrator@example.com")

    security._FAMILY_KEY_CACHE[(str(cloud_db.resolve()), cloud_fid)] = cloud_fek
    ok, err, active_fek = apply_fovault_restore_to_db(portable_bytes, cloud_db, cloud_fid, is_sandbox=False, is_local=False, universe="public")
    assert ok is True and err == "" and active_fek == cloud_fek


def test_sandbox_simplefin_connect_and_async_sync_with_cookie_only_fek(monkeypatch):
    """
    Verifies that connecting a SimpleFIN Setup Token (and running background SimpleFIN sync jobs)
    in Sandbox Mode resolves the household's cookie-only FEK cleanly without raising
    `PermissionError: Household <id> vault is cryptographically locked`, while preserving
    `encryption_key_enc IS NULL` on disk.
    """
    import base64
    import requests

    fake_payload = {
        "errors": [],
        "accounts": [
            {
                "id": "ACT-SANDBOX-SFIN-1",
                "name": "Sandbox SimpleFIN Checking",
                "currency": "USD",
                "balance": "42500.00",
                "balance-date": 1775000000,
                "org": {"name": "SimpleFIN Sandbox Bank", "domain": "simplefin.org"},
                "holdings": [],
            }
        ],
    }

    class _DummyResp:
        def __init__(self, status_code: int, text: str = "", json_data=None):
            self.status_code = status_code
            self.text = text
            self._json_data = json_data

        def json(self):
            return self._json_data

    access_url = "https://user:pass@beta-bridge.simplefin.org/simplefin"
    monkeypatch.setattr(requests, "post", lambda url, **kw: _DummyResp(200, text=access_url))
    monkeypatch.setattr(requests, "get", lambda url, **kw: _DummyResp(200, json_data=fake_payload))

    app.config["TESTING"] = True
    client = app.test_client()
    launch_res = client.post("/api/sandbox/launch", json={"template": "blank"})
    assert launch_res.status_code == 200
    fid = launch_res.get_json()["family_id"]

    setup_token = base64.b64encode(b"https://beta-bridge.simplefin.org/simplefin/claim/SANDBOX-TOKEN").decode("utf-8")

    # 1. Synchronous connect + sync in Sandbox Mode
    res = client.post("/api/settings/simplefin_connect", json={"setup_token": setup_token})
    assert res.status_code == 200, res.get_json()
    data = res.get_json()
    assert data["success"] is True
    assert data["accounts_count"] == 1

    # 2. Asynchronous background job connect + sync in Sandbox Mode (verifying background FEK propagation)
    import hvl_common.web.jobs as web_jobs
    monkeypatch.setattr(web_jobs, "should_run_synchronously", lambda: False)
    res_async = client.post("/api/settings/simplefin_connect", json={"setup_token": setup_token, "async": True})
    assert res_async.status_code == 200, res_async.get_json()
    async_data = res_async.get_json()
    assert async_data["status"] == "processing"
    job_id = async_data.get("job_id") or async_data.get("sync_job_id")
    assert job_id

    job_done = None
    for _ in range(40):
        poll_res = client.get(f"/api/jobs/{job_id}")
        assert poll_res.status_code == 200
        pj = poll_res.get_json()
        if pj.get("status") in ("completed", "failed"):
            job_done = pj
            break
        time.sleep(0.05)

    assert job_done is not None and job_done["status"] == "completed", job_done

    # 3. Verify Zero Data Retained invariant holds on disk (encryption_key_enc is still NULL)
    fam_db = config.get_family_db_path(fid, universe="sandbox")
    with sqlite3.connect(fam_db) as conn:
        row = conn.execute(
            "SELECT encryption_key_enc, support_access_enabled FROM families WHERE family_id = ?",
            (fid,),
        ).fetchone()
        assert row is not None
        assert row[0] is None
        assert row[1] == 0

    sandbox_service.wipe_sandbox_immediately(fid)


