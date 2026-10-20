#!/usr/bin/env python3
"""
Cross-Platform Local Desktop Launcher for HVL Family Office (Windows, macOS, Linux).

Behavior:
1. Resolves the user-writable local vault directory:
   - Windows: %LOCALAPPDATA%\\HVLFamilyOffice
   - macOS:   ~/Library/Application Support/HVLFamilyOffice
   - Linux:   ~/.local/share/hvl-family-office
   - Override: FAMILY_OFFICE_DATA_DIR environment variable
2. Checks `server.json` in the vault directory to see if an instance is already running:
   - If running and healthy (`GET /api/desktop/health`), opens `http://localhost:<port>` in
     the user's default browser and exits 0 (so re-clicking the Desktop / Start Menu / Dock
     icon simply brings up the dashboard).
3. If not running, selects port 5050 (or falls back to 5051..5099 / OS-assigned free port if
   5050 is occupied), writes `server.json`, opens the user's browser, and serves the app via
   Waitress (or threaded Werkzeug WSGI server).
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
_VENDOR_DIR = BASE_DIR / "vendor"
if _VENDOR_DIR.exists() and str(_VENDOR_DIR) not in sys.path:
    sys.path.append(str(_VENDOR_DIR))


from desktop_helpers import (
    _get_app_version,
    _terminate_stale_version_process,
    ensure_pre_upgrade_backup,
    find_app_mode_browser,
    find_available_port,
    get_default_local_data_dir,
    get_local_lan_ip,
    get_running_server_info,
    is_port_available,
    open_desktop_window,
    probe_running_instance,
    remove_server_lockfile,
    write_server_lockfile,
)


def launch_desktop(
    preferred_port: int = 5050,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    window_mode: str = "auto",
    data_dir: Optional[Path] = None,
    restart: bool = False,
) -> int:
    """
    Main desktop launcher entrypoint.
    - Reuses an already-running local instance if present and on the same version (opening the app window immediately).
    - If a running instance is from an older version or restart=True, gracefully stops the old process and snapshots the vault before upgrading.
    - Configures `LOCAL_MODE=1`, picks a free port (`5050..5099` or fallback),
      writes `server.json`, opens the standalone app window (or browser), and starts the WSGI server.
    """
    resolved_data_dir = Path(data_dir) if data_dir is not None else get_default_local_data_dir()
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    current_version = _get_app_version()

    # 1. Check if HVL Family Office is already running locally
    existing = get_running_server_info(resolved_data_dir)
    if existing is not None:
        running_version = str(existing.get("version") or current_version).strip()
        if restart or running_version != current_version:
            action = "Restarting" if restart else "Upgrading"
            print(f"[HVL Family Office] {action} running background server (v{running_version})...")
            _terminate_stale_version_process(resolved_data_dir, existing)
        else:
            existing_url = str(existing.get("url") or f"http://localhost:{existing['port']}")
            if open_browser:
                open_desktop_window(existing_url, window_mode=window_mode)
            print(f"[HVL Family Office] Already running (v{running_version}) at {existing_url}")
            return 0

    ensure_pre_upgrade_backup(resolved_data_dir, current_version)

    # 2. Configure environment for Local Desktop Mode before importing app/config
    os.environ["LOCAL_MODE"] = "1"
    os.environ["FAMILY_OFFICE_DATA_DIR"] = str(resolved_data_dir)

    bind_check_host = "127.0.0.1" if host in ("0.0.0.0", "127.0.0.1", "localhost") else host
    port = find_available_port(preferred_start=preferred_port, preferred_end=5099, host=bind_check_host)
    os.environ["FAMILY_OFFICE_PORT"] = str(port)

    info = write_server_lockfile(resolved_data_dir, port=port, host=host)
    my_pid = os.getpid()
    atexit.register(remove_server_lockfile, resolved_data_dir, my_pid)

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is not None:
            try:
                signal.signal(sig, lambda _s, _f: sys.exit(0))
            except Exception:
                pass

    from app import create_app

    flask_app = create_app()
    local_url = info["url"]
    print(f"[HVL Family Office] Vault directory: {resolved_data_dir}")
    print(f"[HVL Family Office] Local dashboard: {local_url}")
    if host == "0.0.0.0" and info["lan_ip"] != "127.0.0.1":
        print(f"[HVL Family Office] Home Wi-Fi / LAN URL: {info['lan_url']}")

    if open_browser:
        def _open_when_ready() -> None:
            for _ in range(30):
                if probe_running_instance(port, timeout=0.25):
                    break
                time.sleep(0.1)
            open_desktop_window(local_url, window_mode=window_mode)

        threading.Thread(target=_open_when_ready, daemon=True).start()

    try:
        from waitress import serve  # type: ignore[import-untyped]
        serve(flask_app, host=host, port=port, threads=8)
    except ImportError:
        from werkzeug.serving import make_server
        srv = make_server(host, port, flask_app, threaded=True)
        srv.serve_forever()
    finally:
        remove_server_lockfile(resolved_data_dir, my_pid)

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HVL Family Office Local Desktop Launcher")
    parser.add_argument("--port", type=int, default=5050, help="Preferred starting port (default: 5050)")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1; pass 0.0.0.0 to allow LAN phone QR access)",
    )
    parser.add_argument("--data-dir", type=str, default=None, help="Custom directory for encrypted SQLite vault")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open window on startup")
    parser.add_argument("--browser", action="store_true", help="Open in standard web browser tab instead of standalone chromeless app window")
    parser.add_argument("--restart", action="store_true", help="Restart running background server if one is already active")
    parser.add_argument("--reset-vault", action="store_true", help="Permanently wipes the local vault directory to test fresh onboarding")
    args = parser.parse_args(argv)

    custom_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else None
    if getattr(args, "reset_vault", False):
        resolved_dir = custom_dir or get_default_local_data_dir()
        existing = get_running_server_info(resolved_dir)
        if existing is not None:
            _terminate_stale_version_process(resolved_dir, existing)
        if resolved_dir.exists():
            shutil.rmtree(resolved_dir, ignore_errors=True)
            print(f"[HVL Family Office] Local vault wiped: {resolved_dir}")

    mode = "browser" if args.browser else "auto"
    kwargs: dict[str, Any] = {}
    if getattr(args, "restart", False) or getattr(args, "reset_vault", False):
        kwargs["restart"] = True
    return launch_desktop(
        preferred_port=args.port,
        host=args.host,
        open_browser=not args.no_browser,
        window_mode=mode,
        data_dir=custom_dir,
        **kwargs,
    )


if __name__ == "__main__":
    raise SystemExit(main())
