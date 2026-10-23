"""
Tests for Universal Client Update Version Pill and /api/health probes.
Verifies:
1. /api/health supports GET and HEAD methods with 200 OK and X-App-Version header.
2. /static/js/version_pill.js is served correctly.
3. Templates include version_pill in hosted mode, but strictly omit it in local mode.
"""

from __future__ import annotations
import pytest
from app import app


def test_api_health_get_and_head():
    """Verify /api/health returns 200 OK with X-App-Version header on GET and HEAD."""
    client = app.test_client()
    # Test GET
    res_get = client.get("/api/health")
    assert res_get.status_code == 200
    data = res_get.get_json()
    assert data["status"] == "ok"
    assert "X-App-Version" in res_get.headers
    assert len(res_get.headers["X-App-Version"]) > 0

    # Test HEAD
    res_head = client.head("/api/health")
    assert res_head.status_code == 200
    assert "X-App-Version" in res_head.headers


def test_version_pill_script_served():
    """Verify /common/version_pill.js is served with JavaScript content and standalone keyboard sync."""
    from pathlib import Path

    client = app.test_client()
    res = client.get("/common/version_pill.js")
    assert res.status_code == 200
    assert b"showUpdateNotification" in res.data
    assert b"checkAppVersion" in res.data
    assert b"visibilitychange" in res.data
    assert b"hvlSyncStandaloneViewport" in res.data
    assert b"#ai-advisor-messages" in res.data

    res_css = client.get("/common/chat-drawer.css")
    assert res_css.status_code == 200
    assert b"body.hvl-keyboard-open .ai-advisor-drawer" in res_css.data
    assert b"height: var(--vvh, 100dvh);" in res_css.data

    advisor_css = (Path(__file__).resolve().parent.parent / "static" / "css" / "ai_advisor.css").read_text(encoding="utf-8")
    assert "body.hvl-keyboard-open .ai-advisor-drawer" in advisor_css
    assert "height: var(--vvh, 100dvh);" in advisor_css

    advisor_ui_js = (Path(__file__).resolve().parent.parent / "static" / "js" / "ai_advisor_ui.js").read_text(encoding="utf-8")
    assert "window.hvlSyncStandaloneViewport()" in advisor_ui_js

    advisor_threads_js = (Path(__file__).resolve().parent.parent / "static" / "js" / "ai_advisor_threads.js").read_text(encoding="utf-8")
    assert "window.hvlSyncStandaloneViewport()" in advisor_threads_js


def test_version_pill_rendered_in_hosted_mode():
    """Verify version_pill component is rendered on login, help, features, whats-new, and dashboard."""
    client = app.test_client()
    for path in ("/login", "/help", "/features", "/whats-new"):
        res = client.get(path)
        assert res.status_code == 200, f"Failed on {path}"
        assert b"/common/version_pill.js" in res.data, f"Missing version_pill in {path}"
        assert b"window.__APP_VERSION__" in res.data, f"Missing __APP_VERSION__ in {path}"

    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Test User"
        sess["user_family_id"] = 1
        sess["family_id"] = 1
        sess["role"] = "editor"
    res_dash = client.get("/")
    assert res_dash.status_code == 200
    assert b"/common/version_pill.js" in res_dash.data


def test_version_pill_airgapped_in_local_mode(monkeypatch):
    """Verify version_pill component is NEVER rendered in local standalone mode."""
    import config
    monkeypatch.setattr(config, "is_local_mode", lambda: True)

    with app.test_client() as local_client:
        res = local_client.get("/login")
        assert res.status_code == 200
        # In local mode, version_pill.js must not be included
        assert b"/common/version_pill.js" not in res.data
