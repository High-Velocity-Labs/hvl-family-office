"""
Tests for HVL Family Office PWA Manifest/Service Worker, Web Push Dispatch,
and Settings Device Integrations UI.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wsgi import app
import db


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
    """Verifies Settings renders the Push card and secondary page headers omit standalone theme toggles."""
    client = _make_auth_client(family_id=1)
    html = client.get("/").data.decode("utf-8")
    assert 'id="hvl-enable-push-btn"' in html
    assert 'id="hvl-test-push-btn"' in html
    assert "siri" not in html.lower().split('id="settings-section-device-integrations"', 1)[-1][:4000]

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
