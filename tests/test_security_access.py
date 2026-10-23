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
from app import app
import security
from routes.helpers import DB_PATH


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
    from tax_engine import TaxProfile
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
    """Verifies F13: inject_wrapped_fek_into_backup wraps the portable FEK under PBKDF2 passphrase key and never stores plaintext."""
    import json
    import sqlite3
    from db.fovault_repo import (
        PORTABLE_VAULT_FEK_KEY,
        copy_sqlite_backup,
        extract_fek_from_backup_snapshot,
        inject_wrapped_fek_into_backup,
    )

    src_db = tmp_path / "src_vault.db"
    security.init_db(src_db)
    fek = security.get_family_key(src_db, 1)
    backup_db = tmp_path / "exported.fovault"
    copy_sqlite_backup(src_db, backup_db)

    inject_wrapped_fek_into_backup(src_db, backup_db, family_id=1, passphrase="correct-horse-battery-staple")

    with sqlite3.connect(str(backup_db)) as sconn:
        raw_settings = sconn.execute("SELECT settings FROM families WHERE family_id = 1").fetchone()[0]
        sconn.execute("UPDATE families SET encryption_key_enc = NULL WHERE family_id = 1")
        sconn.commit()
    parsed_settings = json.loads(raw_settings)
    wrapped_val = parsed_settings.get(PORTABLE_VAULT_FEK_KEY, "")
    assert wrapped_val.startswith("gAAAAA")
    assert fek.decode("utf-8") not in raw_settings

    assert extract_fek_from_backup_snapshot(backup_db, passphrase="wrong-passphrase") is None
    assert extract_fek_from_backup_snapshot(backup_db, passphrase="correct-horse-battery-staple") == fek

