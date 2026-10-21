"""
Shared Playwright Viewport Overflow & Browser Interaction Test Runner (hvl_common.testing).
Provides reusable Node/Playwright probing, ephemeral Flask test server hosting, and
configurable Desktop/Tablet/Mobile viewport geometry assertions.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any, Dict, Generator, Optional

from werkzeug.serving import make_server

SHARED_RUNNER_JS = Path(__file__).resolve().parent / "js" / "layout_overflow_runner.js"


def resolve_playwright_node_path(root_dir: Path) -> str:
    """Finds node_modules containing playwright-core across workspace or sibling repos."""
    dev_root = root_dir.parent
    candidates = [root_dir / "node_modules"]
    if dev_root.is_dir():
        for sibling in dev_root.iterdir():
            if sibling.is_dir() and not sibling.name.startswith("."):
                nm = sibling / "node_modules"
                if nm.is_dir() and (nm / "playwright-core").exists():
                    candidates.append(nm)
    existing = [str(p) for p in candidates if p.exists()]
    return os.pathsep.join(existing)


def is_playwright_chrome_available(root_dir: Path) -> bool:
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
    env = dict(os.environ, NODE_PATH=resolve_playwright_node_path(root_dir))
    try:
        res = subprocess.run(
            [node_bin, "-e", probe_script],
            env=env,
            cwd=str(root_dir),
            capture_output=True,
            timeout=10,
        )
        return res.returncode == 0
    except Exception:
        return False


@contextmanager
def live_flask_server(app: Any, host: str = "127.0.0.1", port: int = 0) -> Generator[str, None, None]:
    """Starts an ephemeral threaded Werkzeug HTTP server on a free port and yields its base_url."""
    server = make_server(host, port, app, threaded=True)
    actual_port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{actual_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)


def run_playwright_overflow_suite(
    base_url: str,
    root_dir: Path,
    *,
    config_dict: Optional[Dict[str, Any]] = None,
    runner_js: Optional[Path] = None,
    timeout: int = 120,
) -> None:
    """Executes the Playwright layout overflow runner against `base_url` and asserts 0 failures."""
    node_bin = shutil.which("node")
    assert node_bin, "Node.js must be installed to run Level 5 layout tests."

    target_js = runner_js or SHARED_RUNNER_JS
    assert target_js.exists(), f"Runner script not found: {target_js}"

    env = dict(
        os.environ,
        BASE_URL=base_url,
        NODE_PATH=resolve_playwright_node_path(root_dir),
    )
    if config_dict is not None:
        env["OVERFLOW_CONFIG_JSON"] = json.dumps(config_dict)

    result = subprocess.run(
        [node_bin, "--test", str(target_js)],
        env=env,
        cwd=str(root_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"Level 5 Playwright layout overflow suite failed:\n"
        f"--- STDOUT ---\n{result.stdout}\n"
        f"--- STDERR ---\n{result.stderr}"
    )
