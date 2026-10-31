"""
Level 5: Desktop & Mobile Viewport Overflow & Browser Interaction Test Suite.
Validates:
1. Ephemeral live test server using werkzeug.serving.make_server on a free port.
2. Viewport geometry on Desktop (1440x900) and Mobile (375x812) across all public pages & authenticated tabs.
3. Zero uncaught runtime JavaScript exceptions from Chart.js, HTMX, and Idiomorph.
4. Zero horizontal page overflow (scrollWidth <= clientWidth + 2px).
5. Login CTA alignment on desktop and responsive vertical stacking on mobile.
6. Real browser user interactions: tab switching, Bug Reporter modal lifecycle, sliders, canvases.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Generator

from flask import redirect, session
import pytest
from werkzeug.serving import make_server

from app import app
import config

ROOT_DIR = Path(__file__).resolve().parent.parent


def _is_playwright_chrome_available() -> bool:
    """Checks whether Node.js, playwright-core, and system Chrome are executable."""
    node_bin = shutil.which("node")
    if not node_bin:
        return False

    probe_script = (
        "try {"
        "  const { chromium } = require('playwright-core');"
        "  chromium.launch({ channel: 'chrome', headless: true })"
        "    .then(b => b.close().then(() => process.exit(0)))"
        "    .catch(() => process.exit(1));"
        "} catch {"
        "  process.exit(1);"
        "}"
    )
    env = dict(os.environ, NODE_PATH=str(ROOT_DIR / "node_modules"))
    try:
        res = subprocess.run(
            [node_bin, "-e", probe_script],
            env=env,
            cwd=str(ROOT_DIR),
            capture_output=True,
            timeout=10,
        )
        return res.returncode == 0
    except Exception:
        return False


@pytest.fixture(scope="module")
def live_server_url() -> Generator[str, None, None]:
    """Starts an ephemeral background Flask HTTP server on an OS-assigned free port."""
    if not _is_playwright_chrome_available():
        pytest.skip("System Chrome or playwright-core is unavailable on this environment.")

    # Register test helper route for fast deterministic authentication
    if "_test_auth_session" not in app.view_functions:
        def _test_auth_session():
            session.clear()
            session["authenticated"] = True
            session["universe"] = "test"
            session["is_demo"] = False
            session["family_id"] = 1
            session["role"] = "editor"
            session["user"] = "Test Primary"
            return redirect("/")

        app.url_map.add(app.url_rule_class("/api/test/auth_session", endpoint="_test_auth_session", methods=["GET"]))
        app.view_functions["_test_auth_session"] = _test_auth_session

    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    try:
        yield base_url
    finally:
        server.shutdown()
        thread.join(timeout=3)


def test_desktop_and_mobile_layout_overflow(live_server_url: str):
    """Executes the Level 5 Playwright runner across Desktop (1440x900) and Mobile (375x812)."""
    node_bin = shutil.which("node")
    assert node_bin, "Node.js must be installed to run Level 5 layout tests."

    test_file = ROOT_DIR / "tests" / "js" / "layout_overflow_runner.js"
    assert test_file.exists(), f"Runner script not found: {test_file}"

    env = dict(
        os.environ,
        BASE_URL=live_server_url,
        NODE_PATH=str(ROOT_DIR / "node_modules"),
    )

    result = subprocess.run(
        [node_bin, "--test", str(test_file)],
        env=env,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, (
        f"Level 5 Playwright layout overflow suite failed:\n"
        f"--- STDOUT ---\n{result.stdout}\n"
        f"--- STDERR ---\n{result.stderr}"
    )
