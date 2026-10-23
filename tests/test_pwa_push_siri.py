"""
Tests for HVL Family Office PWA Manifest/Service Worker, Web Push Dispatch,
Settings Device Integrations UI, and Apple Siri & Shortcuts Gateway (`/api/siri`).
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app
import config
import db
from hvl_common.db import get_db_connection
from hvl_common.mcp.tokens import ensure_mcp_tokens_table
from routes.helpers import get_current_db_path
import security
from services.mcp_service import _resolve_mcp_db_path, get_household_mcp_status


def _make_auth_client(family_id: int = 1, role: str = "editor", is_demo: bool = False, email: str = "alex@example.com"):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Alex Test"
        sess["user_email"] = email
        sess["user_family_id"] = family_id
        sess["family_id"] = family_id
        sess["role"] = role
        sess["is_demo"] = is_demo
        sess["universe"] = "demo" if is_demo else "test"
        sess["auth_method"] = "Google OAuth"
    return client


@pytest.fixture(autouse=True)
def clean_siri_tokens_db():
    """Ensures clean mcp_tokens table before each test run."""
    db_file = _resolve_mcp_db_path()
    ensure_mcp_tokens_table(db_file)
    with sqlite3.connect(str(db_file)) as conn:
        try:
            conn.execute("DELETE FROM mcp_tokens")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    yield


def test_pwa_manifest_sw_and_index_head():
    """Verifies /manifest.json, /sw.js, and index.html PWA & device-integrations script tags."""
    client = _make_auth_client(family_id=1)

    r_man = client.get("/manifest.json")
    assert r_man.status_code == 200
    man = r_man.get_json()
    assert man["name"] == "HVL Family Office"
    assert man["short_name"] == "Family Office"
    assert man["display"] == "standalone"
    assert any("fo-logo-512.png" in icon["src"] for icon in man["icons"])

    r_sw = client.get("/sw.js")
    assert r_sw.status_code == 200
    assert "javascript" in r_sw.content_type
    assert r_sw.headers.get("Service-Worker-Allowed") == "/"
    assert "no-cache" in r_sw.headers.get("Cache-Control", "")
    assert 'self.addEventListener("push"' in r_sw.data.decode("utf-8")

    r_idx = client.get("/")
    assert r_idx.status_code == 200
    html = r_idx.data.decode("utf-8")
    assert '<link rel="manifest" href="/manifest.json">' in html
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
    assert "/common/device-integrations.js" in html


def test_settings_device_integrations_and_header_theme_toggle_removal():
    """Verifies Settings renders Push & Siri cards and secondary page headers omit standalone theme toggles."""
    client = _make_auth_client(family_id=1)
    html = client.get("/").data.decode("utf-8")
    assert 'id="asst-enable-push-btn"' in html
    assert 'id="hvl-test-push-btn"' in html
    assert 'id="asst-mint-siri-btn"' in html
    assert 'id="hvl-revoke-siri-btn"' in html

    for path, removed_id in (
        ("/helm", "btn-theme-toggle-helm"),
        ("/features", "btn-theme-toggle-features"),
        ("/whats-new", "btn-theme-toggle-wn"),
    ):
        page_resp = client.get(path)
        assert page_resp.status_code == 200
        assert removed_id not in page_resp.data.decode("utf-8")


def test_web_push_dispatch_on_test_push_and_emit_family_notification(monkeypatch):
    """Verifies /api/notifications/test-push and emit_family_notification dispatch Web Push payloads."""
    client = _make_auth_client(family_id=1, email="alex@example.com")
    fam_db = db.session.resolve_db_path(None, family_id=1)
    db.notifications.clear_all_notifications(family_id=1, recipient_email="alex@example.com", db_path=fam_db)

    r_sub = client.post(
        "/api/notifications/subscribe",
        json={
            "endpoint": "https://push.example/alex-device",
            "keys": {"p256dh": "key_p256dh", "auth": "key_auth"},
            "device_label": "Alex iPhone",
        },
    )
    assert r_sub.status_code == 200 and r_sub.get_json()["success"] is True

    dispatched: list[dict] = []

    def _fake_dispatch(sub, title, body, deep_link="/"):
        dispatched.append({"endpoint": sub.get("endpoint"), "title": title, "body": body, "deep_link": deep_link})
        return True

    monkeypatch.setattr("hvl_common.web.notifications.dispatch_web_push", _fake_dispatch)
    monkeypatch.setattr("db.notifications.dispatch_web_push", _fake_dispatch)

    r_test = client.post("/api/notifications/test-push", json={"title": "Custom Test Push", "deep_link": "/accounts"})
    assert r_test.status_code == 200
    body = r_test.get_json()
    assert body["success"] is True
    assert body["devices_notified"] >= 1
    assert any(d["title"] == "Custom Test Push" and d["deep_link"] == "/accounts" for d in dispatched)

    dispatched.clear()
    out = db.notifications.emit_family_notification(
        fam_db, family_id=1, recipient_email="alex@example.com", category="async_job",
        dedupe_key="job:test:push_emit", deep_link="/?tab=tax", title="Tax return ready", body="1040 summary parsed.",
    )
    assert out.get("devices_notified", 0) >= 1
    assert any(d["title"] == "Tax return ready" and d["deep_link"] == "/?tab=tax" for d in dispatched)


def test_siri_gateway_mint_turn_revoke_and_zero_knowledge_fek_unwrap(monkeypatch):
    """Verifies /api/siri mint, turn, revoke, and zero-knowledge vault_fek unwrapping when vault is locked."""
    fam_db = get_current_db_path(family_id=1)
    security.init_db(fam_db)
    raw_fek = security.get_family_key(fam_db, 1)
    enc_dek = security._get_fernet(security.get_or_create_key()).encrypt(raw_fek).decode("utf-8")
    security.db_save_encrypted(
        fam_db, "siri_vault_probe", "test", {"secret_marker": "VaultUnlockedViaSiriToken"}, family_id=1
    )

    client = _make_auth_client(family_id=1, email="alex@example.com")
    r_mint = client.post("/api/siri/mint-token", json={})
    assert r_mint.status_code == 200
    mint_data = r_mint.get_json()
    assert mint_data["success"] is True
    raw_token = mint_data["token"]
    assert raw_token.startswith("hvl_siri_")

    # Siri tokens must not pollute Personal Assistant MCP status list
    mcp_status = get_household_mcp_status(1)
    assert not any(str(t.get("user_email", "")).startswith("siri:") for t in mcp_status["tokens"])

    captured_turns: list[dict] = []

    def _fake_execute_advisor(*, family_id, user_message, **kwargs):
        # Verify the zero-knowledge FEK from the Siri token was bound into the request context!
        loaded = security.db_load_encrypted(fam_db, "siri_vault_probe", family_id=family_id) or {}
        captured_turns.append({"family_id": family_id, "prompt": user_message, "secret": loaded.get("secret_marker")})
        return {"success": True, "reply": f"Liquid net worth is $4.2M ({loaded.get('secret_marker')})."}

    monkeypatch.setattr("services.advisor.chat_service.execute_advisor_generation", _fake_execute_advisor)

    orig_testing = app.config.get("TESTING")
    try:
        # Lock household vault (support_access_enabled=0, encryption_key_enc=NULL) and clear caches
        with get_db_connection(fam_db) as conn:
            conn.execute("UPDATE families SET support_access_enabled = 0, encryption_key_enc = NULL WHERE family_id = 1")
            conn.commit()
        security._clear_security_caches()

        ext_client = app.test_client()
        r_turn = ext_client.post(
            "/api/siri", headers={"Authorization": f"Bearer {raw_token}"}, json={"prompt": "What is our liquid net worth?"},
        )
        assert r_turn.status_code == 200
        turn_json = r_turn.get_json()
        assert turn_json["success"] is True and "VaultUnlockedViaSiriToken" in turn_json["reply"]
        assert captured_turns and captured_turns[0]["secret"] == "VaultUnlockedViaSiriToken"

        # Beta gate exemption check when TESTING=False
        monkeypatch.setattr(config, "is_beta_instance", lambda: True)
        app.config["TESTING"] = False
        r_beta = ext_client.post("/api/siri", headers={"Authorization": f"Bearer {raw_token}"}, json={"prompt": ""})
        assert r_beta.status_code == 200

        # Revoke token and verify subsequent /api/siri call returns 401
        app.config["TESTING"] = orig_testing
        r_rev = client.post("/api/siri/revoke-token", json={})
        assert r_rev.status_code == 200 and r_rev.get_json()["revoked"] is True

        r_after = ext_client.post("/api/siri", headers={"Authorization": f"Bearer {raw_token}"}, json={"prompt": "Still there?"})
        assert r_after.status_code == 401
    finally:
        app.config["TESTING"] = orig_testing
        with get_db_connection(fam_db) as conn:
            conn.execute(
                "UPDATE families SET support_access_enabled = 1, encryption_key_enc = ? WHERE family_id = 1",
                (enc_dek,),
            )
            conn.commit()
        security._clear_security_caches()
