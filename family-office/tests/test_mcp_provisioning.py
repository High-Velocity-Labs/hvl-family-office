"""
Tests for paired-app MCP token provisioning (`services.mcp_provisioning`, `POST /api/mcp/provision`).
Assistant sends a member's Google access token; Family Office verifies it, finds the member's own household,
and mints a read/simulate token bound to that household's FEK (hvl_common C-1 / F-SEC-4).
"""

from __future__ import annotations

import sqlite3

import pytest

import config
import security
from wsgi import app
from hvl_common.mcp.tokens import revoke_mcp_token, verify_mcp_token
from hvl_common.auth import google_tokeninfo
from services import mcp_provisioning
from services.mcp_service import _resolve_mcp_db_path, _resolve_mcp_server_secret

ASSISTANT_CLIENT = "assistant-client.apps.googleusercontent.com"
EMAIL = "provision-member@example.com"
USER_ID = 6301


class _TokenInfo:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _tokeninfo(status: int = 200, **overrides):
    payload = {"azp": ASSISTANT_CLIENT, "aud": ASSISTANT_CLIENT, "email": EMAIL, "email_verified": "true"}
    payload.update(overrides)
    calls: list[str] = []

    def _get(url, params=None, timeout=None):
        assert url == google_tokeninfo.GOOGLE_TOKENINFO_URL and timeout
        calls.append(params["access_token"])
        return _TokenInfo(status, payload)

    _get.calls = calls
    return _get


@pytest.fixture
def member_row(monkeypatch):
    """An editor of the seeded test household 1 (FEK escrowed) in the test universe's global.db."""
    monkeypatch.setenv("MCP_PROVISION_CLIENT_IDS", ASSISTANT_CLIENT)
    monkeypatch.setattr(mcp_provisioning, "read_google_appdata_json", lambda *_a, **_k: None)
    glob = config.get_global_db_path()
    security.init_db(glob)

    def _set(role: str = "editor", family_id: int = 1) -> None:
        with sqlite3.connect(str(glob)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, family_id, name, email, email_hash, role) "
                "VALUES (?, ?, '', '', ?, ?)",
                (USER_ID, family_id, security.hash_email(EMAIL), role),
            )

    _set()
    yield _set
    with sqlite3.connect(str(glob)) as conn:
        conn.execute("DELETE FROM users WHERE user_id = ?", (USER_ID,))
    revoke_mcp_token(_resolve_mcp_db_path(), 1, user_email=EMAIL)


def _post(token: str | None = "ya29.member-token"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return app.test_client().post("/api/mcp/provision", headers=headers)


def test_provision_mints_a_read_simulate_token_for_the_members_own_household(member_row, monkeypatch):
    fake_get = _tokeninfo()
    monkeypatch.setattr(google_tokeninfo.requests, "get", fake_get)
    r = _post()
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["success"] is True and body["raw_token"].startswith("hvl_mcp_")
    assert set(body) == {"success", "raw_token", "token_prefix"}, "no family id, FEK or key leaves Family Office"
    assert fake_get.calls == ["ya29.member-token"]

    meta = verify_mcp_token(_resolve_mcp_db_path(), body["raw_token"], server_secret=_resolve_mcp_server_secret())
    assert meta["owner_id"] == 1 and meta["user_email"] == EMAIL
    assert meta["scopes"] == ["read", "simulate"] and meta["label"] == mcp_provisioning.ASSISTANT_TOKEN_LABEL
    assert meta["secret_payload"] == security.get_family_key(config.get_family_db_path(1), 1)


def test_provision_refuses_unknown_google_accounts_without_echoing_the_email(member_row, monkeypatch):
    monkeypatch.setattr(google_tokeninfo.requests, "get", _tokeninfo(email="stranger@example.com"))
    monkeypatch.setattr(mcp_provisioning, "mint_mcp_token", lambda *a, **k: pytest.fail("minted a token"))
    r = _post()
    assert r.status_code == 404 and "No Family Office account" in r.get_json()["error"]
    assert "stranger" not in r.get_json()["error"]


def test_provision_maps_google_token_refusals_to_their_status(member_row, monkeypatch):
    monkeypatch.setattr(google_tokeninfo.requests, "get", _tokeninfo(status=400))
    assert _post().status_code == 401
    monkeypatch.setattr(google_tokeninfo.requests, "get", _tokeninfo(azp="other", aud="x"))
    assert _post().status_code == 403


def test_provision_requires_a_bearer_and_an_editor(member_row, monkeypatch):
    monkeypatch.setattr(google_tokeninfo.requests, "get", _tokeninfo())
    assert _post(token=None).status_code == 401
    member_row(role="viewer")
    r = _post()
    assert r.status_code == 403 and "editors" in r.get_json()["error"]


@pytest.mark.parametrize("resolved", [(None, None, "Household vault is cryptographically locked"), (None, None, None)])
def test_provision_fails_closed_when_the_vault_is_locked(member_row, monkeypatch, resolved):
    from services import auth_google

    seen: dict = {}

    def _resolve(**kwargs):
        seen.update(kwargs)
        return resolved

    monkeypatch.setattr(auth_google, "resolve_household_vault_fek", _resolve)
    monkeypatch.setattr(google_tokeninfo.requests, "get", _tokeninfo())
    monkeypatch.setattr(mcp_provisioning, "mint_mcp_token", lambda *a, **k: pytest.fail("minted without a FEK"))
    r = _post()
    assert r.status_code == 409 and "locked" in r.get_json()["error"]
    assert seen["fid"] == 1 and seen["access_token"] == "ya29.member-token", "the Drive key is read with the member's token"
