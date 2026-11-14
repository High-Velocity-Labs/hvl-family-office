"""
Unit tests for auth_google.py
Verifies whitelist parsing, self-serve Google OAuth household provisioning,
last_login_at activity tracking, and Google Drive appDataFolder escrow.
"""

from unittest.mock import patch, MagicMock
import pytest
from flask import Flask, session
from services import auth_google, auth_vault_fek
from services.auth_google import auth_google_bp


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


def test_env_email_list_no_longer_grants_whitelist_access(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "wl_vault"))
    monkeypatch.setenv("FAMILY_CHILDREN_EMAILS", "child1@example.com:ChildOne, child2@example.com:ChildTwo")
    whitelist = auth_google.get_family_whitelist()
    assert "child1@example.com" not in whitelist and "child2@example.com" not in whitelist


def test_authenticate_family_email_success(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "auth_ok_vault"))
    with patch("services.auth_google.get_family_whitelist", return_value=_MOCK_MEMBERS):
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
    monkeypatch.setattr(auth_vault_fek, "write_google_appdata_json", lambda token, payload, **kw: True)

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
    security.db_save_encrypted(test_db, "secret_ledger", "vault", {"net_worth": 4100000}, family_id=1)
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
    monkeypatch.setattr(auth_vault_fek, "write_google_appdata_json", fake_write_appdata)

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
        assert ledger == {"net_worth": 4100000}
        assert security.get_family_key(test_db, 1) == original_fek
        security.set_family_support_access(test_db, family_id=1, enabled=True)

    security._clear_security_caches()
    assert security.get_family_key(test_db, 1) == original_fek
    assert security.db_load_encrypted(test_db, "secret_ledger", family_id=1) == {"net_worth": 4100000}

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
        conn.execute("UPDATE families SET support_access_enabled = 1 WHERE family_id = 1")
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
    monkeypatch.setattr(auth_vault_fek, "write_google_appdata_json", fail_or_track_write)

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
    from services import background_jobs
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

    monkeypatch.setattr(auth_vault_fek, "write_google_appdata_json", track_write)
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
    assert fn is auth_vault_fek._sync_fek_to_google_and_db
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


# Magic invite tokens, household invite API endpoints, download redirect tracking, and beta instance gate.
def test_magic_invite_tokens_new_household_join_household_and_oauth_redemption(tmp_path, monkeypatch):
    """
    Verifies Magic Invite (`invite_tokens`) creation, validation, revocation, expiration,
    `/invite/<code>` redirect + login banner, and Google OAuth auto-provisioning for both
    `new_household` (isolated FEK + `is_new_household=True`) and `join_household` (shared FEK).
    """
    import security
    from app import create_app

    import routes.auth as auth_routes
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "invite_vault_dir"))
    test_db = tmp_path / "invite_oauth_test.db"
    monkeypatch.setattr(auth_google, "DB_PATH", test_db)
    monkeypatch.setattr(auth_routes, "DB_PATH", test_db)
    security._clear_security_caches()
    security.init_db(test_db)

    monkeypatch.setattr(auth_google, "read_google_appdata_json", lambda token, **kw: None)
    monkeypatch.setattr(auth_vault_fek, "write_google_appdata_json", lambda token, payload, **kw: True)

    # 1. Create a `new_household` invite (max_uses=1) and a `join_household` invite (target_role="editor")
    inv_new = security.create_invite_token(
        test_db,
        family_id=1,
        created_by_email="admin@example.com",
        invite_type="new_household",
        target_role="editor",
        label="Beta Friend Household",
        max_uses=1,
        expires_days=7,
    )
    assert inv_new["code"].startswith("FO-")
    assert inv_new["invite_type"] == "new_household"

    inv_join = security.create_invite_token(
        test_db,
        family_id=1,
        created_by_email="admin@example.com",
        invite_type="join_household",
        target_role="viewer",
        label="Partner Join Link",
        max_uses=2,
        expires_days=7,
    )
    assert inv_join["code"].startswith("FO-")
    assert inv_join["invite_type"] == "join_household"

    # 2. Verify GET /invite/<code> stores pending_invite_code in session and renders banner on /login
    full_app = create_app()
    full_app.config["TESTING"] = True
    client = full_app.test_client()

    r_inv = client.get(f"/invite/{inv_new['code']}")
    assert r_inv.status_code == 302
    assert f"/login?invite={inv_new['code']}" in r_inv.headers["Location"]

    r_login = client.get(r_inv.headers["Location"])
    assert r_login.status_code == 200
    login_html = r_login.get_data(as_text=True)
    assert "invite-active-banner" in login_html
    assert inv_new["code"] in login_html

    # 3. Redeem `new_household` invite via Google OAuth callback -> creates isolated family_id != 1
    fam1_fek = security.get_family_key(test_db, 1)
    with full_app.test_request_context("/auth/google/callback"):
        session["pending_invite_code"] = inv_new["code"]
        ok_new, member_new, _ = auth_google.authenticate_family_email(
            "newfriend@example.com",
            {"name": "New Friend", "_oauth_tokens": {"access_token": "tok_new_1"}},
        )
        assert ok_new is True
        assert member_new["is_new_household"] is True
        new_fid = int(member_new["family_id"])
        assert new_fid > 1
        assert member_new["role"] in ("admin", "editor")
        new_fek = security.get_family_key(test_db, new_fid)
        assert new_fek != fam1_fek
        assert "pending_invite_code" not in session

    # Single-use `new_household` invite is now exhausted
    assert security.validate_invite_token(test_db, inv_new["code"]) is None

    # 4. Redeem `join_household` invite via Google OAuth -> joins family_id=1 with shared FEK
    with full_app.test_request_context("/auth/google/callback"):
        session["pending_invite_code"] = inv_join["code"]
        ok_join, member_join, _ = auth_google.authenticate_family_email(
            "partner.join@example.com",
            {"name": "Partner Join", "_oauth_tokens": {"access_token": "tok_join_1"}},
        )
        assert ok_join is True
        assert not member_join.get("is_new_household")
        assert int(member_join["family_id"]) == 1
        assert member_join["role"] == "viewer"
        security.set_family_support_access(test_db, family_id=1, enabled=True)

    # 5. Revoke `join_household` invite and verify it can no longer be validated
    assert security.revoke_invite_token(test_db, family_id=1, code=inv_join["code"]) is True
    assert security.validate_invite_token(test_db, inv_join["code"]) is None

    # 6. Multi-use token redemption (`max_uses=2` stays valid after 1st use, then exhausts on 2nd use)
    inv_multi = security.create_invite_token(
        test_db,
        family_id=1,
        created_by_email="admin@example.com",
        invite_type="join_household",
        target_role="editor",
        label="Multi Use Household Invite",
        max_uses=2,
        expires_days=7,
    )
    red1 = security.redeem_invite_token(test_db, inv_multi["code"], "multi1@example.com", "Multi One")
    assert red1 is not None
    assert int(red1["family_id"]) == 1
    still_valid = security.validate_invite_token(test_db, inv_multi["code"])
    assert still_valid is not None
    assert int(still_valid["uses_count"]) == 1
    assert int(still_valid["max_uses"]) == 2

    red2 = security.redeem_invite_token(test_db, inv_multi["code"], "multi2@example.com", "Multi Two")
    assert red2 is not None
    assert int(red2["family_id"]) == 1
    assert security.validate_invite_token(test_db, inv_multi["code"]) is None
    assert security.redeem_invite_token(test_db, inv_multi["code"], "multi3@example.com", "Multi Three") is None

    # 7. Expired token (`expires_at` in the past) returns None on validate_invite_token and renders invite_error banner on /login
    import sqlite3
    inv_exp = security.create_invite_token(
        test_db,
        family_id=1,
        created_by_email="admin@example.com",
        invite_type="join_household",
        target_role="viewer",
        label="Expired Invite",
        max_uses=1,
        expires_days=1,
    )
    for cand_db in security._invite_candidate_dbs(test_db, 1):
        if cand_db.exists():
            with sqlite3.connect(str(cand_db)) as conn:
                conn.execute(
                    "UPDATE invite_tokens SET expires_at = '2020-01-01T00:00:00+00:00' WHERE code = ?",
                    (inv_exp["code"],),
                )
                conn.commit()

    assert security.validate_invite_token(test_db, inv_exp["code"]) is None
    r_exp = client.get(f"/invite/{inv_exp['code']}")
    assert r_exp.status_code == 302
    assert "/login?invite_error=1" in r_exp.headers["Location"]
    r_exp_login = client.get(r_exp.headers["Location"])
    assert r_exp_login.status_code == 200
    exp_html = r_exp_login.get_data(as_text=True)
    assert "invalid, expired, or has already been redeemed" in exp_html


def test_family_invites_endpoints_admin_guard_member_cap_and_local_mode(tmp_path, monkeypatch):
    """
    Verifies `/api/family/invites` (`GET`, `POST`, `DELETE`), site-admin guard for `new_household`,
    `MAX_HOUSEHOLD_MEMBERS` cap, and `LOCAL_MODE=1` returning `403` / hiding `#magic-invites-section` in settings SSR.
    """
    import config
    import security
    import routes.dashboard as dashboard_routes
    import routes.family as family_routes
    import services.request_context as helpers_mod
    import ssr.settings as ssr_settings_mod
    from app import create_app

    vault_dir = tmp_path / "invites_api_vault"
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    monkeypatch.setenv("LOCAL_MODE", "0")
    monkeypatch.delenv("STANDALONE_MODE", raising=False)
    monkeypatch.setenv("ADMIN_EMAIL", "siteadmin@example.com")

    test_db = config.get_global_db_path("public")
    fam_db = config.get_family_db_path(1, "public")
    security._clear_security_caches()
    security.init_db(test_db)
    security.init_db(fam_db)

    monkeypatch.setattr(helpers_mod, "DB_PATH", test_db)
    monkeypatch.setattr(family_routes, "DB_PATH", test_db)
    monkeypatch.setattr(dashboard_routes, "DB_PATH", test_db)
    monkeypatch.setattr(ssr_settings_mod, "DB_PATH", test_db)

    full_app = create_app()
    full_app.config["TESTING"] = True

    with full_app.test_client() as client:
        # 1. Non-site-admin editor in Family 2 cannot create `new_household` invite (403), but CAN create `join_household`
        security.init_db(config.get_family_db_path(2, "public"))
        security.add_family_member(test_db, family_id=2, name="Regular Owner", email="regular@example.com", relationship="primary", role="editor")
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["family_id"] = 2
            sess["user_family_id"] = 2
            sess["user"] = "Regular"
            sess["user_email"] = "regular@example.com"
            sess["role"] = "editor"
            sess["user_role"] = "editor"
            sess["universe"] = "public"
            sess["is_demo"] = False

        r_forbid = client.post(
            "/api/family/invites",
            json={"invite_type": "new_household", "label": "Unauthorized New Vault"},
        )
        assert r_forbid.status_code == 403
        assert "site administrator" in r_forbid.get_json()["error"]

        r_join_ok = client.post(
            "/api/family/invites",
            json={"invite_type": "join_household", "target_role": "viewer", "label": "Spouse Invite", "max_uses": 2},
        )
        assert r_join_ok.status_code == 200
        join_code = r_join_ok.get_json()["invite"]["code"]

        # GET /api/family/invites returns the created invite with invite_url
        r_list = client.get("/api/family/invites")
        assert r_list.status_code == 200
        invites = r_list.get_json()["invites"]
        assert any(i["code"] == join_code and f"/invite/{join_code}" in i["invite_url"] for i in invites)

        # DELETE /api/family/invites/<code> revokes the invite
        r_del = client.delete(f"/api/family/invites/{join_code}")
        assert r_del.status_code == 200
        assert r_del.get_json()["revoked"] is True
        assert security.validate_invite_token(test_db, join_code) is None

        # 2. Site admin CAN create `new_household` invite
        with client.session_transaction() as sess:
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["user"] = "SiteAdmin"
            sess["user_email"] = "siteadmin@example.com"
            sess["role"] = "admin"
            sess["user_role"] = "admin"

        r_admin_new = client.post(
            "/api/family/invites",
            json={"invite_type": "new_household", "label": "VIP Friend Vault"},
        )
        assert r_admin_new.status_code == 200
        assert r_admin_new.get_json()["invite"]["invite_type"] == "new_household"

        # 3. MAX_HOUSEHOLD_MEMBERS cap blocks creating `join_household` invites when household is full
        security.add_family_member(test_db, family_id=1, name="Admin Primary", email="siteadmin@example.com", relationship="primary", role="admin")
        monkeypatch.setattr(config, "MAX_HOUSEHOLD_MEMBERS", 1)
        r_cap = client.post(
            "/api/family/invites",
            json={"invite_type": "join_household", "target_role": "editor"},
        )
        assert r_cap.status_code == 400
        assert "Maximum of 1 household members reached" in r_cap.get_json()["error"]
        monkeypatch.setattr(config, "MAX_HOUSEHOLD_MEMBERS", 20)

        # 4. Cloud mode (`LOCAL_MODE=0`) renders `#magic-invites-section` in Settings SSR
        r_ssr_cloud = client.get("/fragments/settings?tab=members")
        assert r_ssr_cloud.status_code == 200
        assert 'id="magic-invites-section"' in r_ssr_cloud.get_data(as_text=True)

        # 5. Local mode (`LOCAL_MODE=1`) returns 403 on POST /api/family/invites, empty list on GET, and hides `#magic-invites-section` in Settings SSR
        monkeypatch.setenv("LOCAL_MODE", "1")
        r_local_post = client.post("/api/family/invites", json={"invite_type": "join_household"})
        assert r_local_post.status_code == 403

        r_local_get = client.get("/api/family/invites")
        assert r_local_get.status_code == 200
        assert r_local_get.get_json()["invites"] == []
        assert r_local_get.get_json()["standalone_mode"] is True

        r_ssr_local = client.get("/fragments/settings?tab=members")
        assert r_ssr_local.status_code == 200
        assert 'id="magic-invites-section"' not in r_ssr_local.get_data(as_text=True)


def test_download_redirect_tracking_and_admin_telemetry_view(tmp_path, monkeypatch):
    """
    Verifies:
    1. `/download/<target>` (`macos`, `windows`, `github`, `releases`) logs zero-PII customer click events
       in `global.db` (`download_events`) and redirects (`302`) to GitHub.
    2. Clicks from a logged-in Site Administrator or automated benchmark runner (`X-HVL-Benchmark: 1`)
       still redirect (`302`) to GitHub without inflating customer `download_events` counts.
    3. Household Settings SSR (`/fragments/settings`) does not include backend admin download telemetry.
    """
    import config
    import security
    from app import create_app

    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "dl_telemetry_data"))
    monkeypatch.setenv("ADMIN_EMAIL", "siteadmin@example.com")
    global_db = config.get_global_db_path("public")
    monkeypatch.setattr(auth_google, "DB_PATH", global_db)
    security._clear_security_caches()
    security.init_db(global_db)
    security.init_db(config.get_family_db_path(1, "public"))
    security.init_db(config.get_family_db_path(2, "public"))

    full_app = create_app()
    full_app.config["TESTING"] = True

    with full_app.test_client() as client:
        # 1. Trigger customer download & GitHub redirects
        r_mac = client.get("/download/macos?ref=features", headers={"User-Agent": "Mozilla/5.0 Macintosh"})
        assert r_mac.status_code == 302
        assert "github.com/" in r_mac.headers["Location"] and "/releases" in r_mac.headers["Location"]

        r_win = client.get("/download/windows?ref=help&direct=1", headers={"User-Agent": "Mozilla/5.0 Windows NT 10.0"})
        assert r_win.status_code == 302
        assert "HVL-Family-Office-Windows-Setup.exe" in r_win.headers["Location"]

        r_gh = client.get("/download/github?ref=login", headers={"User-Agent": "Mozilla/5.0"})
        assert r_gh.status_code == 302
        assert r_gh.headers["Location"].endswith(config.GITHUB_REPO_SLUG)

        r_rel = client.get("/download/releases?ref=features", headers={"User-Agent": "Mozilla/5.0"})
        assert r_rel.status_code == 302
        assert r_rel.headers["Location"].endswith("/releases")

        # 2. Benchmark runner & logged-in Site Admin clicks redirect cleanly without polluting customer counts
        r_bench = client.get("/download/macos?ref=bench", headers={"X-HVL-Benchmark": "1"})
        assert r_bench.status_code == 302

        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["user"] = "SiteAdmin"
            sess["user_email"] = "siteadmin@example.com"
            sess["role"] = "admin"
            sess["user_role"] = "admin"
            sess["universe"] = "public"
            sess["is_demo"] = False

        r_admin_click = client.get("/download/windows?ref=admin_test", headers={"User-Agent": "Mozilla/5.0"})
        assert r_admin_click.status_code == 302

        summary = security.get_download_telemetry_summary(global_db, include_github_live=False)
        assert summary["total_events"] == 4
        assert summary["counts_by_target"]["macos"] == 1
        assert summary["counts_by_target"]["windows"] == 1
        assert summary["counts_by_target"]["github"] == 1
        assert summary["counts_by_target"]["releases"] == 1
        assert len(summary["recent_events"]) == 4

        # 3. Household Settings SSR is strictly customer settings (no backend admin telemetry tab)
        r_admin_ssr = client.get("/fragments/settings?tab=members")
        assert r_admin_ssr.status_code == 200
        ssr_html = r_admin_ssr.get_data(as_text=True)
        assert 'id="tab-btn-admin-telemetry"' not in ssr_html
        assert 'id="settings-tab-admin-telemetry"' not in ssr_html


def test_beta_instance_gate_and_cross_subdomain_cookie(monkeypatch, tmp_path):
    """Verifies that the beta instance blocks public traffic without the Site Admin gate cookie, and unlocks with it."""
    from app import create_app
    from hvl_common.security import ADMIN_GATE_COOKIE_NAME, wrap_admin_gate_token

    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "beta_gate_data"))
    monkeypatch.setenv("ADMIN_EMAIL", "siteadmin@example.com")
    monkeypatch.setenv("HVL_BETA_INSTANCE", "1")
    monkeypatch.setenv("HVL_SERVICE_NAME", "planner")
    monkeypatch.setenv("HVL_ADMIN_GATE_SECRET", "test-shared-gate-secret-key-12345")

    beta_app = create_app()
    beta_app.config["TESTING"] = False

    with beta_app.test_client() as client:
        r_health = client.get("/health", environ_base={"REMOTE_ADDR": "203.0.113.50"})
        assert r_health.status_code == 200
        assert r_health.get_json()["service"] == "planner-beta"

        r_gate = client.get("/beta-gate", environ_base={"REMOTE_ADDR": "203.0.113.50"})
        assert r_gate.status_code == 403
        assert "Staging &amp; Beta Instance" in r_gate.get_data(as_text=True)

        r_root = client.get("/login", environ_base={"REMOTE_ADDR": "203.0.113.50"})
        assert r_root.status_code == 302
        assert r_root.headers["Location"].endswith("/beta-gate")

        r_api = client.get("/api/auth/status", environ_base={"REMOTE_ADDR": "203.0.113.50"})
        assert r_api.status_code == 403
        assert r_api.get_json()["beta_gate"] is True

        valid_token = wrap_admin_gate_token("siteadmin@example.com", "test-shared-gate-secret-key-12345")
        client.set_cookie(ADMIN_GATE_COOKIE_NAME, valid_token)
        r_unlocked = client.get("/login", environ_base={"REMOTE_ADDR": "203.0.113.50"})
        assert r_unlocked.status_code == 200


def test_login_through_a_global_db_outside_a_universe_dir_never_touches_another_households_db(tmp_path, monkeypatch):
    """A login clears escrow in global.db's own sibling families/{fid}.db only. A DB outside a universe dir has no
    peer; deriving the peer from a universe name used to hit the real data dir's household (it locked household 1
    for later tests)."""
    import sqlite3
    import config
    import security
    from app import create_app

    real_fam_db = config.get_family_db_path(1)
    security.init_db(real_fam_db)
    security.get_family_key(real_fam_db, 1)

    def escrow_state():
        with sqlite3.connect(str(real_fam_db)) as conn:
            return conn.execute(
                "SELECT encryption_key_enc, support_access_enabled FROM families WHERE family_id = 1"
            ).fetchone()

    before = escrow_state()
    test_db = tmp_path / "outside_universe_login.db"
    monkeypatch.setattr(auth_google, "DB_PATH", test_db)
    security._clear_security_caches()
    security.init_db(test_db)
    security.get_family_key(test_db, 1)
    security.add_family_member(
        test_db, family_id=1, name="Outside User", email="outside@example.com", relationship="primary", role="admin"
    )
    monkeypatch.setattr(auth_google, "read_google_appdata_json", lambda token, **kw: None)
    monkeypatch.setattr(auth_vault_fek, "write_google_appdata_json", lambda token, payload, **kw: True)
    with create_app().test_request_context("/auth/google/callback"):
        ok, _member, _ = auth_google.authenticate_family_email(
            "outside@example.com", {"_oauth_tokens": {"access_token": "token_outside"}}
        )
    assert ok is True
    assert escrow_state() == before, "the real household 1's escrow must be untouched"

    assert security.household_auth_peer_dbs(test_db, 1) == []
    glob = tmp_path / "public" / "global.db"
    fam = tmp_path / "public" / "families" / "1.db"
    fam.parent.mkdir(parents=True)
    glob.touch()
    fam.touch()
    assert security.household_auth_peer_dbs(glob, 1) == [fam]
    assert security.household_auth_peer_dbs(fam, 1) == [glob]
