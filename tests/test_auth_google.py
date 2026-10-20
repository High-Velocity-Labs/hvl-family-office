"""
Unit tests for auth_google.py
Verifies whitelist parsing, self-serve Google OAuth household provisioning,
last_login_at activity tracking, and Google Drive appDataFolder escrow.
"""

from unittest.mock import patch, MagicMock
import pytest
from flask import Flask, session
import auth_google
from auth_google import auth_google_bp


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.secret_key = "test-secret-key-123"
    test_app.register_blueprint(auth_google_bp)
    return test_app


_MOCK_MEMBERS = {
    "test_user@example.com": {"user_id": 1, "family_id": 1, "name": "Alice", "display_name": "Alice Smith", "role": "admin", "permissions": ["all"]},
    "test_spouse@example.com": {"user_id": 2, "family_id": 1, "name": "Bob", "display_name": "Bob Smith", "role": "admin", "permissions": ["all"]},
}


def test_children_family_whitelist_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "wl_vault"))
    monkeypatch.setenv("FAMILY_CHILDREN_EMAILS", "child1@example.com:ChildOne, child2@example.com:ChildTwo")
    whitelist = auth_google.get_family_whitelist()
    assert whitelist["child1@example.com"]["name"] == "ChildOne"
    assert whitelist["child1@example.com"]["role"] == "family_member"
    assert whitelist["child2@example.com"]["name"] == "ChildTwo"


def test_authenticate_family_email_success(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "auth_ok_vault"))
    with patch("auth_google.get_family_whitelist", return_value=_MOCK_MEMBERS):
        with app.test_request_context():
            ok, member, _ = auth_google.authenticate_family_email("test_user@example.com")
            assert ok is True and member["name"] == "Alice" and session["authenticated"] is True
            assert session["user"] == "Alice" and session["user_email"] == "test_user@example.com"

            ok, member, _ = auth_google.authenticate_family_email("test_spouse@example.com")
            assert ok is True and member["name"] == "Bob"
            assert session["user"] == "Bob" and session["user_email"] == "test_spouse@example.com"


def test_authenticate_unauthorized_email_rejection(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "auth_reject_vault"))
    monkeypatch.setenv("PUBLIC_GOOGLE_SIGNUP_ENABLED", "0")
    with app.test_request_context():
        ok, member, msg = auth_google.authenticate_family_email("stranger@example.com")
        assert ok is False and member is None and "Access denied" in msg
        assert session.get("authenticated") is not True


def test_self_serve_google_oauth_provisioning_and_activity_tracking(tmp_path, monkeypatch):
    """
    Verifies that in Cloud Mode (`PUBLIC_GOOGLE_SIGNUP_ENABLED=1` default):
    1. Any new Google OAuth email auto-provisions an isolated per-family vault (`family_id >= 2`, `support_access_enabled = 0`).
    2. `record_family_login` updates `last_login_at` and `login_count` in both `global.db` and `families/{fid}.db`.
    3. `get_active_families_summary` reports active families in the past 30 days and 365 days without scheduled deletion tasks.
    4. `/login` renders the 365-day cloud retention disclaimer in Cloud Mode (`LOCAL_MODE=0`), and omits it in Standalone Mode (`LOCAL_MODE=1`).
    """
    import config
    import security
    from app import create_app
    from db.household_activity import get_active_families_summary

    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "self_serve_vault"))
    monkeypatch.setenv("LOCAL_MODE", "0")
    monkeypatch.delenv("STANDALONE_MODE", raising=False)
    monkeypatch.setenv("PUBLIC_GOOGLE_SIGNUP_ENABLED", "1")

    test_db = config.get_global_db_path("public")
    monkeypatch.setattr(auth_google, "DB_PATH", test_db)
    security._clear_security_caches()
    security.init_db(test_db)

    monkeypatch.setattr(auth_google, "read_google_appdata_json", lambda token, **kw: None)
    monkeypatch.setattr(auth_google, "write_google_appdata_json", lambda token, payload, **kw: True)

    full_app = create_app()
    full_app.config["TESTING"] = True

    with full_app.test_request_context("/auth/google/callback"):
        ok, member, _ = auth_google.authenticate_family_email(
            "boglehead.visitor@example.com",
            {"name": "Boglehead Visitor", "_oauth_tokens": {"access_token": "tok_bh_1"}},
        )
        assert ok is True
        assert member["is_new_household"] is True
        new_fid = int(member["family_id"])
        assert new_fid >= 2
        assert session["authenticated"] is True
        assert session["family_id"] == new_fid

    summary = get_active_families_summary(test_db)
    assert summary["active_30d"] >= 1
    assert summary["active_365d"] >= 1
    assert summary["inactive_over_365d"] == 0
    matching = [f for f in summary["families"] if f["family_id"] == new_fid]
    assert len(matching) == 1
    assert matching[0]["last_login_at"] is not None
    assert matching[0]["login_count"] >= 1
    assert matching[0]["active_30d"] is True
    assert matching[0]["active_365d"] is True

    with full_app.test_client() as client:
        r_cloud_login = client.get("/login")
        assert r_cloud_login.status_code == 200
        cloud_html = r_cloud_login.get_data(as_text=True)
        assert "Cloud Vault Sign In" in cloud_html
        assert "365+ days" in cloud_html
        assert "Launch Anonymous Workspace" in cloud_html
        assert "login-mode-split" in cloud_html

        monkeypatch.setenv("LOCAL_MODE", "1")
        r_local_login = client.get("/login")
        assert r_local_login.status_code == 200
        local_html = r_local_login.get_data(as_text=True)
        assert "Cloud Vault Sign In" not in local_html
        assert "365+ days" not in local_html
        assert "Launch Anonymous Workspace" not in local_html


def test_google_config_endpoint(app, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id-xyz.apps.googleusercontent.com")
    client = app.test_client()
    resp = client.get("/auth/google/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enabled"] is True
    assert data["client_id"] == "test-client-id-xyz.apps.googleusercontent.com"


def test_privacy_and_terms_pages_public():
    from app import create_app
    full_app = create_app()
    client = full_app.test_client()

    resp_privacy = client.get("/privacy")
    assert resp_privacy.status_code == 301
    assert resp_privacy.headers.get("Location") == "https://highvelocitylabs.dev/privacy"

    resp_terms = client.get("/terms")
    assert resp_terms.status_code == 301
    assert resp_terms.headers.get("Location") == "https://highvelocitylabs.dev/terms"


def test_google_appdata_vault_and_cryptographic_escrow_lock(tmp_path, monkeypatch):
    import sqlite3
    import security
    from app import create_app

    test_db = tmp_path / "vault_escrow_test.db"
    monkeypatch.setattr(auth_google, "DB_PATH", test_db)
    security._clear_security_caches()
    security.init_db(test_db)

    original_fek = security.get_family_key(test_db, 1)
    u1_id = security.add_family_member(
        test_db, family_id=1, name="Primary Member", email="primary@example.com", relationship="primary", role="admin"
    )
    u2_id = security.add_family_member(
        test_db, family_id=1, name="Spouse Member", email="spouse@example.com", relationship="spouse", role="editor"
    )
    security.db_save_encrypted(test_db, "secret_ledger", "vault", {"net_worth": 4200000}, family_id=1)
    security.set_family_support_access(test_db, family_id=1, enabled=False)

    with sqlite3.connect(str(test_db)) as conn:
        fam_row = conn.execute("SELECT encryption_key_enc, support_access_enabled FROM families WHERE family_id = 1").fetchone()
        assert fam_row[0] is None
        assert int(fam_row[1]) == 0
        u_rows = conn.execute("SELECT user_id, pending_fek_enc, google_vault_synced FROM users WHERE family_id = 1 ORDER BY user_id").fetchall()
        assert len(u_rows) == 2
        assert u_rows[0][1] is not None and int(u_rows[0][2]) == 0
        assert u_rows[1][1] is not None and int(u_rows[1][2]) == 0

    google_cloud_appdata = {}

    def fake_read_appdata(access_token, filename="hvl_vault_key.json", timeout=8):
        return google_cloud_appdata.get((access_token, filename))

    def fake_write_appdata(access_token, payload, filename="hvl_vault_key.json", timeout=8):
        google_cloud_appdata[(access_token, filename)] = dict(payload)
        return True

    monkeypatch.setattr(auth_google, "read_google_appdata_json", fake_read_appdata)
    monkeypatch.setattr(auth_google, "write_google_appdata_json", fake_write_appdata)

    full_app = create_app()
    full_app.config["TESTING"] = True

    with full_app.test_request_context("/auth/google/callback"):
        ok, member, _ = auth_google.authenticate_family_email(
            "primary@example.com",
            {"_oauth_tokens": {"access_token": "google_token_primary"}},
        )
        assert ok is True
        assert member["name"] == "Primary"
        assert member["display_name"] == "Primary Member"
        assert ("google_token_primary", "hvl_vault_key.json") in google_cloud_appdata

    with sqlite3.connect(str(test_db)) as conn:
        u1_row = conn.execute("SELECT pending_fek_enc, google_vault_synced FROM users WHERE user_id = ?", (u1_id,)).fetchone()
        u2_row = conn.execute("SELECT pending_fek_enc, google_vault_synced FROM users WHERE user_id = ?", (u2_id,)).fetchone()
        assert u1_row[0] is None and int(u1_row[1]) == 1
        assert u2_row[0] is not None and int(u2_row[1]) == 0

    with full_app.test_request_context("/auth/google/callback"):
        ok2, member2, _ = auth_google.authenticate_family_email(
            "spouse@example.com",
            {"_oauth_tokens": {"access_token": "google_token_spouse"}},
        )
        assert ok2 is True
        assert member2["name"] == "Spouse"
        assert member2["display_name"] == "Spouse Member"
        assert ("google_token_spouse", "hvl_vault_key.json") in google_cloud_appdata

    with sqlite3.connect(str(test_db)) as conn:
        fam_enc = conn.execute("SELECT encryption_key_enc FROM families WHERE family_id = 1").fetchone()[0]
        pending_count = conn.execute("SELECT count(*) FROM users WHERE family_id = 1 AND pending_fek_enc IS NOT NULL").fetchone()[0]
        assert fam_enc is None
        assert pending_count == 0

    security._clear_security_caches()
    with pytest.raises(PermissionError):
        security.get_family_key(test_db, 1)
    with pytest.raises(PermissionError):
        security.db_load_encrypted(test_db, "secret_ledger", family_id=1)
    with pytest.raises(PermissionError):
        security.set_family_support_access(test_db, family_id=1, enabled=True)

    with full_app.test_request_context("/auth/google/callback"):
        ok3, member3, _ = auth_google.authenticate_family_email(
            "primary@example.com",
            {"_oauth_tokens": {"access_token": "google_token_primary"}},
        )
        assert ok3 is True
        assert member3["display_name"] == "Primary Member"
        ledger = security.db_load_encrypted(test_db, "secret_ledger", family_id=1)
        assert ledger == {"net_worth": 4200000}
        assert security.get_family_key(test_db, 1) == original_fek
        security.set_family_support_access(test_db, family_id=1, enabled=True)

    security._clear_security_caches()
    assert security.get_family_key(test_db, 1) == original_fek
    assert security.db_load_encrypted(test_db, "secret_ledger", family_id=1) == {"net_worth": 4200000}

    with full_app.test_request_context("/"):
        from flask import session as flask_sess
        flask_sess["authenticated"] = True
        flask_sess["family_id"] = 1
        flask_sess["user_family_id"] = 1
        security.stash_request_vault_fek(1, original_fek)
        security.set_family_support_access(test_db, family_id=1, enabled=False)

    with pytest.raises(PermissionError):
        security.get_family_key(test_db, 1)


def test_repeat_login_when_synced_skips_google_drive_http_calls(tmp_path, monkeypatch):
    import sqlite3
    import security
    from app import create_app

    test_db = tmp_path / "repeat_login_fast_test.db"
    monkeypatch.setattr(auth_google, "DB_PATH", test_db)
    security._clear_security_caches()
    security.init_db(test_db)

    original_fek = security.get_family_key(test_db, 1)
    u1_id = security.add_family_member(
        test_db, family_id=1, name="Fast User", email="fast@example.com", relationship="primary", role="admin"
    )
    with sqlite3.connect(str(test_db)) as conn:
        conn.execute("UPDATE users SET pending_fek_enc = NULL, google_vault_synced = 1 WHERE user_id = ?", (u1_id,))
        conn.commit()

    read_calls = []
    write_calls = []

    def fail_or_track_read(access_token, filename="hvl_vault_key.json", timeout=8):
        read_calls.append(access_token)
        return {"family_id": 1, "fek": original_fek.decode("utf-8")}

    def fail_or_track_write(access_token, payload, filename="hvl_vault_key.json", timeout=8):
        write_calls.append((access_token, payload))
        return True

    monkeypatch.setattr(auth_google, "read_google_appdata_json", fail_or_track_read)
    monkeypatch.setattr(auth_google, "write_google_appdata_json", fail_or_track_write)

    full_app = create_app()
    full_app.config["TESTING"] = True

    with full_app.test_request_context("/auth/google/callback"):
        ok, member, _ = auth_google.authenticate_family_email(
            "fast@example.com",
            {"_oauth_tokens": {"access_token": "token_repeat_1"}},
        )
        assert ok is True
        assert member["display_name"] == "Fast User"
        assert len(read_calls) == 0
        assert len(write_calls) == 0

    security.set_family_support_access(test_db, family_id=1, enabled=False)
    with sqlite3.connect(str(test_db)) as conn:
        conn.execute("UPDATE users SET pending_fek_enc = NULL, google_vault_synced = 1 WHERE user_id = ?", (u1_id,))
        conn.commit()
    security._clear_security_caches()

    with full_app.test_request_context("/auth/google/callback"):
        session["vault_fek"] = security.wrap_cookie_fek(original_fek, security.get_primary_key())
        session["vault_fek_family_id"] = 1
        ok2, member2, _ = auth_google.authenticate_family_email(
            "fast@example.com",
            {"_oauth_tokens": {"access_token": "token_repeat_2"}},
        )
        assert ok2 is True
        assert member2["display_name"] == "Fast User"
        assert len(read_calls) == 0
        assert len(write_calls) == 0


def test_initial_login_offloads_google_drive_write_to_background_when_async(tmp_path, monkeypatch):
    import sqlite3
    import background_jobs
    import security
    from app import create_app

    test_db = tmp_path / "async_login_sync_test.db"
    monkeypatch.setattr(auth_google, "DB_PATH", test_db)
    security._clear_security_caches()
    security.init_db(test_db)

    original_fek = security.get_family_key(test_db, 1)
    u1_id = security.add_family_member(
        test_db, family_id=1, name="Async User", email="async@example.com", relationship="primary", role="admin"
    )

    monkeypatch.setattr(auth_google, "read_google_appdata_json", lambda token, **kw: None)
    written_payloads = []

    def track_write(access_token, payload, filename="hvl_vault_key.json", timeout=8):
        written_payloads.append((access_token, dict(payload)))
        return True

    monkeypatch.setattr(auth_google, "write_google_appdata_json", track_write)
    monkeypatch.setattr(background_jobs, "should_run_synchronously", lambda: False)

    submitted_calls = []

    def fake_submit(fn, *args, **kwargs):
        submitted_calls.append((fn, args, kwargs))
        fn(*args, **kwargs)
        return MagicMock()

    monkeypatch.setattr(background_jobs.EXECUTOR, "submit", fake_submit)

    full_app = create_app()
    with full_app.test_request_context("/auth/google/callback"):
        ok, member, _ = auth_google.authenticate_family_email(
            "async@example.com",
            {"_oauth_tokens": {"access_token": "token_async_prod"}},
        )
        assert ok is True
        assert member["display_name"] == "Async User"

    assert len(submitted_calls) == 1
    fn, args, _ = submitted_calls[0]
    assert fn is auth_google._sync_fek_to_google_and_db
    assert args[0] == "token_async_prod"
    assert args[1] == 1
    assert args[2] == u1_id
    assert args[3] == original_fek
    assert args[5] is True

    assert len(written_payloads) == 1
    assert written_payloads[0] == ("token_async_prod", {"family_id": 1, "fek": original_fek.decode("utf-8")})

    with sqlite3.connect(str(test_db)) as conn:
        u_row = conn.execute("SELECT pending_fek_enc, google_vault_synced FROM users WHERE user_id = ?", (u1_id,)).fetchone()
        assert u_row[0] is None
        assert int(u_row[1]) == 1
