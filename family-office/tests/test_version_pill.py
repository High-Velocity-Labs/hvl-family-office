"""
Tests for Universal Client Update Version Pill and /api/health probes.
Verifies:
1. /api/health supports GET and HEAD methods with 200 OK and X-App-Version header.
2. /common/version_pill.js is served correctly.
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
    assert client.get("/common/version_pill.js").status_code == 200


def test_version_pill_airgapped_in_local_mode(monkeypatch):
    """Verify version_pill component is NEVER rendered in local standalone mode."""
    import config
    monkeypatch.setattr(config, "is_local_mode", lambda: True)

    with app.test_client() as local_client:
        res = local_client.get("/login")
        assert res.status_code == 200
        # In local mode, version_pill.js must not be included
        assert b"/common/version_pill.js" not in res.data


def test_version_pill_viewport_sync_never_resets_scroll_on_scrollable_pages():
    """Verify hvlSyncStandaloneViewport never calls scrollTo(0, 0) or zeroes scrollTop on scrollable pages."""
    import json
    from pathlib import Path
    import subprocess

    vp_path = Path(__import__("hvl_common").__file__).parent / "ui" / "static" / "version_pill.js"
    vp_src = vp_path.read_text(encoding="utf-8")
    assert "isKeyboardOpen && hasLockedShell" in vp_src
    assert "(isKeyboardOpen || window.scrollY !== 0" not in vp_src
    assert "visualViewport.addEventListener('scroll'" not in vp_src

    node_script = f"""
    const vpSrc = {json.dumps(vp_src)};
    let scrollToCalls = 0;
    const rootEl = {{
        scrollTop: 480,
        clientHeight: 900,
        style: {{ setProperty() {{}}, removeProperty() {{}} }},
    }};
    const bodyEl = {{
        scrollTop: 480,
        classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
        appendChild() {{}},
    }};
    global.window = {{
        scrollY: 480,
        innerHeight: 900,
        innerWidth: 1280,
        visualViewport: {{
            height: 900,
            offsetTop: 0,
            addEventListener() {{}},
        }},
        scrollTo() {{ scrollToCalls += 1; }},
        addEventListener() {{}},
    }};
    global.document = {{
        readyState: 'complete',
        documentElement: rootEl,
        body: bodyEl,
        activeElement: {{ tagName: 'BODY' }},
        addEventListener() {{}},
        querySelector() {{ return null; }},
        querySelectorAll() {{ return []; }},
        getElementById() {{ return null; }},
    }};
    eval(vpSrc);
    window.hvlSyncStandaloneViewport();
    if (scrollToCalls !== 0 || rootEl.scrollTop !== 480 || bodyEl.scrollTop !== 480) {{
        process.exit(1);
    }}
    """
    proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"Node viewport scroll test failed: {proc.stderr}"

