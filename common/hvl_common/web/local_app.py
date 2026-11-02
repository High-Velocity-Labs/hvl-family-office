"""
Shared local desktop/app launcher primitives (`hvl_common.web.local_app`).

Provides cross-platform port probing/selection (`is_port_available`, `find_available_port`)
and chromeless Chromium `--app=<url>` window discovery and launch (`find_app_mode_browser`,
`open_app_window`) for apps that run as a local desktop window.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import socket
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional
import webbrowser


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Returns True if `host:port` is free to bind."""
    if port <= 0 or port > 65535:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sys.platform != "win32":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((host, int(port)))
            return True
    except OSError:
        return False


def find_available_port(
    preferred_start: int = 5050,
    preferred_end: int = 5099,
    host: str = "127.0.0.1",
) -> int:
    """
    Finds the first available TCP port in `[preferred_start, max(preferred_end, preferred_start + 50)]`.
    If all ports in the preferred range are occupied, asks the OS for any free ephemeral port.
    """
    start = int(preferred_start)
    end = max(int(preferred_end), start + 50)
    for port in range(start, end + 1):
        if is_port_available(port, host=host):
            return port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def find_app_mode_browser(platform_name: Optional[str] = None) -> Optional[str]:
    """
    Locates an installed Chromium-based browser (Edge, Chrome, Brave, Chromium) that supports
    standalone chromeless window mode (`--app=<url>`).
    """
    import os

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


def open_app_window(
    url: str,
    window_mode: str = "auto",
    *,
    browser_finder: Callable[[Optional[str]], Optional[str]] = find_app_mode_browser,
) -> str:
    """
    Opens `url` either as a standalone chromeless desktop window (`--app=<url>`)
    or in the user's standard web browser (`window_mode="browser"`).
    Returns the mode actually used (`"app"` or `"browser"`).
    """
    mode = (window_mode or "auto").strip().lower()
    if mode in ("auto", "app"):
        browser_bin = browser_finder(None)
        if browser_bin:
            try:
                popen_kwargs: Dict[str, Any] = {
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                }
                if sys.platform == "win32":
                    popen_kwargs["creationflags"] = getattr(
                        subprocess, "DETACHED_PROCESS", 0x00000008
                    )
                subprocess.Popen([browser_bin, f"--app={url}"], **popen_kwargs)
                return "app"
            except OSError:
                pass
    webbrowser.open(url)
    return "browser"


__all__ = [
    "find_app_mode_browser",
    "find_available_port",
    "is_port_available",
    "open_app_window",
]
