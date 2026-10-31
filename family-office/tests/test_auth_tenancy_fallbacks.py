"""Regression tests: auth/tenancy paths never fall back to Family 1 (DIRECTIVES section 1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask, session

import config
import security
from services import auth_google, auth_session


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.secret_key = "tenancy-test-secret"
    return test_app


def test_site_admin_requires_admin_email_env_even_for_family_1_editor(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "site_admin"))
    db_path = tmp_path / "site_admin" / "global.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    security.init_db(db_path)
    security.add_family_member(
        db_path, family_id=1, name="Editor One", email="editor1@example.com", relationship="primary", role="editor"
    )
    for var in ("ADMIN_EMAIL", "HVL_ADMIN_EMAIL"):
        monkeypatch.delenv(var, raising=False)
    assert config.get_site_admin_emails() == set()
    assert config.is_site_admin_email("editor1@example.com", db_path=db_path) is False

    monkeypatch.setenv("ADMIN_EMAIL", "Owner@Example.com")
    assert config.is_site_admin_email("owner@example.com") is True
    assert config.is_site_admin_email("editor1@example.com", db_path=db_path) is False


def test_login_with_missing_family_id_is_rejected(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "no_fid"))
    monkeypatch.setenv("PUBLIC_GOOGLE_SIGNUP_ENABLED", "0")
    orphan = {"orphan@example.com": {"user_id": 5, "name": "Orphan", "display_name": "Orphan", "role": "admin", "permissions": ["all"]}}
    with patch("services.auth_google.get_family_whitelist", return_value=orphan):
        with app.test_request_context():
            ok, member, msg = auth_google.authenticate_family_email("orphan@example.com")
            assert ok is False and member is None and "Access denied" in msg
            assert not session.get("authenticated")
            assert session.get("family_id") is None


def test_exiting_demo_without_saved_family_does_not_land_in_family_1(app):
    with app.test_request_context():
        session["prev_user"] = "Someone"
        session["prev_user_email"] = "someone@example.com"
        session["is_demo"] = True
        session["family_id"] = 3
        assert auth_session.restore_or_clear_demo_session() is False
        assert not session.get("authenticated")
        assert session.get("family_id") is None


def test_exiting_demo_restores_real_saved_family_and_role(app):
    with app.test_request_context():
        session.update(prev_user="Someone", prev_user_email="s@example.com", prev_user_role="viewer", prev_user_family_id=7)
        assert auth_session.restore_or_clear_demo_session() is True
        assert session["family_id"] == 7 and session["user_family_id"] == 7
        assert session["role"] == "viewer"


def test_invite_without_creator_family_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "inv"))
    db_path = tmp_path / "inv" / "global.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    security.init_db(db_path)
    token = {"code": "ABCD1234", "invite_type": "join_household", "created_by_family_id": 0, "target_role": "viewer"}
    with patch("security.invites.validate_invite_token", return_value=token):
        assert security.redeem_invite_token(db_path, "ABCD1234", "joiner@example.com", "Joiner") is None


def test_legacy_encrypted_store_is_kept_and_family_1_not_seeded(tmp_path):
    from hvl_common.db import run_migrations

    legacy_sql = Path(__file__).resolve().parent / "fixtures" / "legacy_migrations"
    db_path = tmp_path / "legacy.db"
    run_migrations(db_path, legacy_sql)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO encrypted_store VALUES ('k', 'c', 't', 'payload')")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("INSERT INTO family_encrypted_store (family_id, key, category, encrypted_payload) VALUES (0, 'k', 'c', 'x')")
    security.init_db(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM encrypted_store").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM families").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM family_encrypted_store").fetchone()[0] == 0


def test_join_locked_household_surfaces_vault_locked_message(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "locked"))
    monkeypatch.setenv("PUBLIC_GOOGLE_SIGNUP_ENABLED", "0")
    db_path = tmp_path / "locked" / "public" / "global.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(auth_google, "DB_PATH", db_path)
    security.init_db(db_path)

    with patch("security.get_family_key", side_effect=PermissionError("locked")), \
         patch("security.init._candidate_family_metadata_dbs", return_value=[]):
        with pytest.raises(security.init.VaultLockedError, match="Support Access = OFF"):
            security._join_invited_household(db_path, 2, "Joiner", "joiner@example.com", "viewer", "public")

    with app.test_request_context():
        session["pending_invite_code"] = "ABCD1234"
        msg_err = security.init.VaultLockedError(security.init.HOUSEHOLD_VAULT_LOCKED_INVITE_MESSAGE)
        with patch("security.redeem_invite_token", side_effect=msg_err), \
             patch("services.auth_google.get_family_whitelist", return_value={}):
            ok, member, msg = auth_google.authenticate_family_email("joiner@example.com")
        assert ok is False and member is None
        assert "Support Access = OFF" in msg and "Allow Support Access" in msg


def _denied_login_leaves_clean_session(app, tmp_path, monkeypatch, seed: dict, invite: str | None):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "denied"))
    monkeypatch.setenv("PUBLIC_GOOGLE_SIGNUP_ENABLED", "0")
    db_path = tmp_path / "denied" / "public" / "global.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(auth_google, "DB_PATH", db_path)
    security.init_db(db_path)
    with app.test_request_context():
        session.update(seed)
        if invite:
            session["pending_invite_code"] = invite
        ok, member, _ = auth_google.authenticate_family_email("stranger@example.com")
        assert ok is False and member is None
        assert not session.get("authenticated")
        assert session.get("family_id") is None
        assert session.get("universe") in (None, "")
        assert not session.get("is_demo") and not session.get("is_sandbox")


@pytest.mark.parametrize("invite", ["BOGUS123", None])
def test_denied_login_clears_demo_session(app, tmp_path, monkeypatch, invite):
    seed = {"authenticated": True, "is_demo": True, "universe": "demo", "family_id": 1, "role": "viewer", "user_role": "viewer"}
    _denied_login_leaves_clean_session(app, tmp_path, monkeypatch, seed, invite)


@pytest.mark.parametrize("invite", ["BOGUS123", None])
def test_denied_login_clears_sandbox_session(app, tmp_path, monkeypatch, invite):
    seed = {"authenticated": True, "is_sandbox": True, "universe": "sandbox", "family_id": 9, "role": "admin", "user_role": "admin"}
    _denied_login_leaves_clean_session(app, tmp_path, monkeypatch, seed, invite)


def test_denied_login_missing_family_id_clears_demo_session(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "denied_fid"))
    orphan = {"orphan@example.com": {"user_id": 5, "name": "Orphan", "display_name": "Orphan", "role": "admin", "permissions": ["all"]}}
    with patch("services.auth_google.get_family_whitelist", return_value=orphan):
        with app.test_request_context():
            session.update(authenticated=True, is_demo=True, universe="demo", family_id=1, role="viewer")
            ok, _, _ = auth_google.authenticate_family_email("orphan@example.com")
            assert ok is False
            assert not session.get("authenticated") and session.get("family_id") is None


def test_demo_persona_session_has_no_real_user_family(app):
    with app.test_request_context("/"):
        with patch("services.auth_session.ensure_demo_database"):
            auth_session.apply_demo_persona_session("1")
        assert session["user_family_id"] == 0 and session["is_demo"] is True


def test_site_admin_allowlist_is_union_of_both_env_vars(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "")
    monkeypatch.setenv("HVL_ADMIN_EMAIL", "second@example.com")
    assert config.get_site_admin_emails() == {"second@example.com"}
    monkeypatch.setenv("ADMIN_EMAIL", "first@example.com")
    assert config.get_site_admin_emails() == {"first@example.com", "second@example.com"}
    monkeypatch.setenv("HVL_ADMIN_EMAILS", "extra@example.com")
    assert not config.is_site_admin_email("extra@example.com")


def test_non_vault_permission_error_is_not_shown_on_login(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "eacces"))
    monkeypatch.setenv("PUBLIC_GOOGLE_SIGNUP_ENABLED", "0")
    db_path = tmp_path / "eacces" / "public" / "global.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(auth_google, "DB_PATH", db_path)
    security.init_db(db_path)
    with app.test_request_context():
        session["pending_invite_code"] = "ABCD1234"
        with patch("security.redeem_invite_token", side_effect=PermissionError(13, "denied", "/secret/path.db")):
            ok, _, msg = auth_google.authenticate_family_email("joiner@example.com")
    assert ok is False and "/secret/path" not in msg


def test_exception_mid_login_clears_sandbox_session(app, tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "boom"))
    db_path = tmp_path / "boom" / "public" / "global.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(auth_google, "DB_PATH", db_path)
    security.init_db(db_path)
    with app.test_request_context():
        session.update(authenticated=True, is_sandbox=True, universe="sandbox", family_id=9, user_family_id=9,
                       role="editor", user_role="editor")
        with patch("services.auth_google.get_family_whitelist", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                auth_google.authenticate_family_email("anyone@example.com")
        assert not session.get("authenticated")
        for key in ("family_id", "user_family_id", "role", "user_role", "is_sandbox"):
            assert session.get(key) is None


def test_new_login_drops_previous_admin_identity_saved_by_demo(app, tmp_path, monkeypatch):
    """An admin's identity saved while browsing a demo persona must not survive a different user's login."""
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "switch"))
    monkeypatch.setenv("ADMIN_EMAIL", "site-admin@example.com")
    db_path = tmp_path / "switch" / "public" / "global.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(auth_google, "DB_PATH", db_path)
    security.init_db(db_path)
    member = {"viewer@example.com": {"family_id": 7, "user_id": 3, "name": "Viewer", "display_name": "Viewer",
                                     "role": "viewer", "permissions": []}}
    with patch("services.auth_google.get_family_whitelist", return_value=member):
        with app.test_request_context():
            session.update(authenticated=True, is_demo=True, universe="demo", family_id=1, role="viewer",
                           prev_user="Admin", prev_user_email="site-admin@example.com", prev_user_role="admin",
                           prev_user_family_id=2, prev_auth_method="google")
            ok, _, _ = auth_google.authenticate_family_email("viewer@example.com")
            assert ok is True
            for key in ("prev_user", "prev_user_email", "prev_user_role", "prev_user_family_id", "prev_auth_method"):
                assert session.get(key) is None
            assert auth_session.is_site_admin() is False
