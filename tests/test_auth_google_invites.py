"""
Unit tests for Magic Invite tokens, household invite API endpoints,
download redirect tracking, and beta instance gate.
"""

from unittest.mock import MagicMock
import pytest
from flask import session
import auth_google


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
    monkeypatch.setattr(auth_google, "write_google_appdata_json", lambda token, payload, **kw: True)

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
    import routes.helpers as helpers_mod
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
    """Verifies that finances-beta blocks public traffic without the Site Admin gate cookie, and unlocks with it."""
    from app import create_app
    from hvl_common.security import ADMIN_GATE_COOKIE_NAME, wrap_admin_gate_token

    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "beta_gate_data"))
    monkeypatch.setenv("ADMIN_EMAIL", "siteadmin@example.com")
    monkeypatch.setenv("HVL_BETA_INSTANCE", "1")
    monkeypatch.setenv("HVL_ADMIN_GATE_SECRET", "test-shared-gate-secret-key-12345")

    beta_app = create_app()
    beta_app.config["TESTING"] = False

    with beta_app.test_client() as client:
        r_health = client.get("/health", environ_base={"REMOTE_ADDR": "203.0.113.50"})
        assert r_health.status_code == 200
        assert r_health.get_json()["service"] == "finances-beta"

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
