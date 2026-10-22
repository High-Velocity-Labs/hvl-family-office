"""
desktop_helpers.py: OS-level environment, port discovery, process locking,
vault backup, and chromeless browser launcher helpers for HVL Family Office desktop mode.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_default_local_data_dir(platform_name: Optional[str] = None) -> Path:
    """Resolves the OS-appropriate user-writable data directory for local desktop mode."""
    override = os.environ.get("FAMILY_OFFICE_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    plat = platform_name or sys.platform
    home = Path.home()
    if plat == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else (home / "AppData" / "Local")
        new_dir = base / "HVLFamilyOffice"
        legacy_dir = base / "AIFamilyOffice"
        if not new_dir.exists() and legacy_dir.exists():
            return legacy_dir
        return new_dir
    if plat == "darwin":
        app_support = home / "Library" / "Application Support"
        new_dir = app_support / "HVLFamilyOffice"
        legacy_dir = app_support / "AIFamilyOffice"
        if not new_dir.exists() and legacy_dir.exists():
            return legacy_dir
        return new_dir
    xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg_data) if xdg_data else (home / ".local" / "share")
    new_dir = base / "hvl-family-office"
    legacy_dir = base / "ai-family-office"
    if not new_dir.exists() and legacy_dir.exists():
        return legacy_dir
    return new_dir


def get_local_lan_ip() -> str:
    """Determines the primary local LAN / Wi-Fi / Tailscale IPv4 address without sending traffic."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Returns True if `host:port` is free to bind."""
    if port <= 0 or port > 65535:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            else:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind((host, int(port)))
            return True
    except OSError:
        return False


def find_available_port(
    preferred_start: int = 5050,
    preferred_end: int = 5099,
    host: str = "127.0.0.1",
) -> int:
    """
    Finds the first available TCP port in [preferred_start, preferred_end].
    If all ports in the preferred range are occupied, asks the OS for any free ephemeral port.
    """
    for port in range(int(preferred_start), int(preferred_end) + 1):
        if is_port_available(port, host=host):
            return port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def probe_running_instance(port: int, timeout: float = 0.75) -> bool:
    """Checks if an HVL Family Office server is actively responding on `127.0.0.1:<port>`."""
    url = f"http://127.0.0.1:{int(port)}/api/desktop/health"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            return bool(isinstance(payload, dict) and payload.get("app") in ("hvl-family-office", "ai-family-office"))
    except Exception:
        return False


def get_running_server_info(data_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Inspects `data_dir / 'server.json'` and verifies whether that server is still alive.
    Returns the parsed server metadata dict if active, or None if stale/stopped.
    """
    lock_file = Path(data_dir) / "server.json"
    if not lock_file.exists():
        return None
    try:
        info = json.loads(lock_file.read_text(encoding="utf-8"))
        port = int(info.get("port") or 0)
        desktop_mod = sys.modules.get("desktop_app")
        probe_fn = getattr(desktop_mod, "probe_running_instance", probe_running_instance) if desktop_mod else probe_running_instance
        if port > 0 and probe_fn(port):
            return info
    except Exception:
        pass
    return None


def _get_app_version() -> str:
    return os.environ.get("APP_VERSION", "1.0.0").strip() or "1.0.0"


def ensure_pre_upgrade_backup(data_dir: Path, current_version: str) -> Optional[Path]:
    """
    Checks `data_dir / 'version.json'`. If a previous installation version exists and differs
    from `current_version`, creates a consistent timestamped SQLite snapshot of the primary
    household database in `data_dir / 'backups'` before any new schema migrations run.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    version_file = data_dir / "version.json"
    prev_version = None
    if version_file.exists():
        try:
            meta = json.loads(version_file.read_text(encoding="utf-8"))
            prev_version = str(meta.get("version") or "").strip()
        except Exception:
            prev_version = None

    backup_created: Optional[Path] = None
    candidate_dbs = [
        data_dir / "public" / "families" / "1.db",
        data_dir / "families" / "1.db",
        data_dir / "public" / "global.db",
        data_dir / "global.db",
    ]
    primary_db = next((p for p in candidate_dbs if p.exists()), data_dir / "families" / "1.db")

    if prev_version and prev_version != current_version and primary_db.exists():
        try:
            backups_dir = data_dir / "backups"
            backups_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            dst_path = backups_dir / f"pre_upgrade_v{prev_version}_to_v{current_version}_{ts}.fovault"
            from db.auth_repo import backup_sqlite_database
            backup_sqlite_database(primary_db, dst_path)
            backup_created = dst_path
        except Exception:
            backup_created = None

    try:
        version_file.write_text(
            json.dumps(
                {
                    "version": current_version,
                    "previous_version": prev_version,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    return backup_created


def write_server_lockfile(data_dir: Path, port: int, host: str = "127.0.0.1") -> Dict[str, Any]:
    """Writes active server metadata to `data_dir / 'server.json'`."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    lan_ip = get_local_lan_ip()
    info: Dict[str, Any] = {
        "app": "hvl-family-office",
        "version": _get_app_version(),
        "pid": os.getpid(),
        "port": int(port),
        "host": host,
        "lan_ip": lan_ip,
        "url": f"http://localhost:{int(port)}",
        "lan_url": f"http://{lan_ip}:{int(port)}",
        "data_dir": str(data_dir),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    lock_file = data_dir / "server.json"
    lock_file.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def remove_server_lockfile(data_dir: Path, expected_pid: Optional[int] = None) -> None:
    """Removes `server.json` on clean shutdown if owned by the current process."""
    lock_file = Path(data_dir) / "server.json"
    if not lock_file.exists():
        return
    try:
        if expected_pid is not None:
            info = json.loads(lock_file.read_text(encoding="utf-8"))
            if int(info.get("pid") or 0) != int(expected_pid):
                return
        lock_file.unlink(missing_ok=True)
    except Exception:
        pass


def _terminate_stale_version_process(data_dir: Path, existing: Dict[str, Any]) -> None:
    """Stops a running background server from an older app version so the upgraded binary can take over."""
    old_pid = int(existing.get("pid") or 0)
    old_port = int(existing.get("port") or 5050)
    if old_pid > 0 and old_pid != os.getpid():
        try:
            sig = getattr(signal, "SIGTERM", 15)
            os.kill(old_pid, sig)
        except Exception:
            pass
    remove_server_lockfile(data_dir)
    for _ in range(30):
        if is_port_available(old_port, host="127.0.0.1"):
            break
        time.sleep(0.1)


def find_app_mode_browser(platform_name: Optional[str] = None) -> Optional[str]:
    """
    Locates an installed Chromium-based browser (Edge, Chrome, Brave, Chromium) that supports
    standalone chromeless window mode (`--app=<url>`), hiding the `localhost` URL bar and tabs
    while preserving the user's real Google OAuth session, Passkeys, and Password Manager.
    """
    plat = platform_name or sys.platform
    candidates: List[Path] = []

    if plat == "win32":
        prog_files = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")),
        ]
        rel_paths = [
            Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
            Path("Google") / "Chrome" / "Application" / "chrome.exe",
            Path("BraveSoftware") / "Brave-Browser" / "Application" / "brave.exe",
        ]
        for base in prog_files:
            if base:
                for rel in rel_paths:
                    candidates.append(Path(base) / rel)
        for cmd in ("msedge", "chrome", "brave"):
            found = shutil.which(cmd)
            if found:
                candidates.append(Path(found))
    elif plat == "darwin":
        app_dirs = [Path("/Applications"), Path.home() / "Applications"]
        bundles = [
            Path("Google Chrome.app") / "Contents" / "MacOS" / "Google Chrome",
            Path("Microsoft Edge.app") / "Contents" / "MacOS" / "Microsoft Edge",
            Path("Brave Browser.app") / "Contents" / "MacOS" / "Brave Browser",
            Path("Chromium.app") / "Contents" / "MacOS" / "Chromium",
        ]
        for app_dir in app_dirs:
            for bundle in bundles:
                candidates.append(app_dir / bundle)
    else:
        for cmd in (
            "google-chrome",
            "google-chrome-stable",
            "microsoft-edge",
            "microsoft-edge-stable",
            "brave-browser",
            "chromium",
            "chromium-browser",
        ):
            found = shutil.which(cmd)
            if found:
                candidates.append(Path(found))

    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                return str(cand)
        except OSError:
            continue
    return None


def open_desktop_window(url: str, window_mode: str = "auto") -> str:
    """
    Opens `url` either as a standalone chromeless desktop window (`--app=<url>`, no `localhost`
    URL bar or tabs) or in the user's standard web browser (`window_mode="browser"`).
    Returns the mode actually used (`"app"` or `"browser"`).
    """
    mode = (window_mode or "auto").strip().lower()
    if mode in ("auto", "app"):
        desktop_mod = sys.modules.get("desktop_app")
        find_fn = getattr(desktop_mod, "find_app_mode_browser", find_app_mode_browser) if desktop_mod else find_app_mode_browser
        browser_bin = find_fn()
        if browser_bin:
            try:
                popen_kwargs: Dict[str, Any] = {
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                }
                if sys.platform == "win32":
                    popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                subprocess.Popen([browser_bin, f"--app={url}"], **popen_kwargs)
                return "app"
            except Exception:
                pass
    webbrowser.open(url)
    return "browser"
