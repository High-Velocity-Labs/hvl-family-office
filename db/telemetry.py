"""
Anonymous Download & GitHub Release Telemetry Repository (Zero-PII Global Store).
Records `/download/<target>` click redirects in `global.db` (`download_events` table)
and aggregates first-party click metrics alongside cached GitHub Release asset download counts.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from hvl_common.db import get_db_connection
from security_store import init_db

VALID_DOWNLOAD_TARGETS = ("macos", "windows", "github", "releases")
_DOWNLOAD_TARGET_ALIASES: dict[str, str] = {
    "mac": "macos",
    "macos": "macos",
    "dmg": "macos",
    "win": "windows",
    "windows": "windows",
    "exe": "windows",
    "github": "github",
    "repo": "github",
    "source": "github",
    "releases": "releases",
    "release": "releases",
}
_GITHUB_TELEMETRY_CACHE: dict[str, Any] = {"fetched_at": 0.0, "data": None}


def resolve_download_redirect_target(
    raw_target: str, repo_slug: str, direct: bool = False
) -> tuple[str, str]:
    """
    Normalizes a requested `/download/<target>` slug and returns `(norm_target, destination_url)`.
    """
    norm_target = _DOWNLOAD_TARGET_ALIASES.get(str(raw_target or "").strip().lower(), "releases")
    if norm_target == "macos" and direct:
        dest = f"https://github.com/{repo_slug}/releases/latest/download/HVL-Family-Office-macOS.dmg"
    elif norm_target == "windows" and direct:
        dest = f"https://github.com/{repo_slug}/releases/latest/download/HVL-Family-Office-Windows-Setup.exe"
    elif norm_target in ("macos", "windows", "releases"):
        dest = f"https://github.com/{repo_slug}/releases"
    else:
        dest = f"https://github.com/{repo_slug}"
    return norm_target, dest


def resolve_telemetry_db_path() -> Path:
    """
    Resolves the global SQLite database path for site-wide download telemetry.
    Honors test monkeypatches on `auth_google.DB_PATH` and otherwise resolves
    `config.get_global_db_path()` using the process `APP_UNIVERSE` so unauthenticated
    download clicks and authenticated admin sessions read/write the same global DB.
    """
    import sys
    import config

    ag = sys.modules.get("auth_google")
    if ag is not None and hasattr(ag, "DB_PATH"):
        ag_db = getattr(ag, "DB_PATH")
        if isinstance(ag_db, Path):
            return ag_db
    return config.get_global_db_path()


def _ensure_download_events_table(conn: Any) -> None:
    """Ensures the `download_events` table exists in the target SQLite database via SQLAlchemy 2.0 ORM metadata."""
    from db.models_ops import DownloadEvent, ensure_orm_table_on_conn
    ensure_orm_table_on_conn(conn, DownloadEvent)


def record_download_event(
    db_path: Path,
    target: str,
    app_version: str = "",
    referrer: str = "",
    user_agent: str = "",
) -> bool:
    """
    Records an anonymous download or GitHub link click in `download_events`.
    Stores zero PII (only target slug, app version, referrer path/domain, and coarse user-agent).
    """
    clean_target = str(target or "").strip().lower()
    if clean_target not in VALID_DOWNLOAD_TARGETS:
        return False
    clean_ver = str(app_version or "").strip()[:32]
    clean_ref = str(referrer or "").strip()[:200]
    clean_ua = str(user_agent or "").strip()[:200]

    target_db = Path(db_path)
    init_db(target_db)
    try:
        with get_db_connection(target_db) as conn:
            _ensure_download_events_table(conn)
            conn.execute(
                """
                INSERT INTO download_events (target, app_version, referrer, user_agent)
                VALUES (?, ?, ?, ?)
                """,
                (clean_target, clean_ver, clean_ref, clean_ua),
            )
            conn.commit()
        return True
    except Exception:
        return False


def _fetch_github_release_metrics(repo_slug: str, force_refresh: bool = False) -> dict[str, Any]:
    """
    Fetches live GitHub repository stars, forks, and release asset download counts
    with a 10-minute in-memory cache. Gracefully falls back when offline or rate-limited.
    """
    now_ts = time.time()
    cached = _GITHUB_TELEMETRY_CACHE.get("data")
    if (
        not force_refresh
        and isinstance(cached, dict)
        and cached.get("repo_slug") == repo_slug
        and (now_ts - float(_GITHUB_TELEMETRY_CACHE.get("fetched_at") or 0.0)) < 600.0
    ):
        return cached

    result: dict[str, Any] = {
        "available": False,
        "repo_slug": repo_slug,
        "stars": 0,
        "forks": 0,
        "watchers": 0,
        "total_asset_downloads": 0,
        "macos_asset_downloads": 0,
        "windows_asset_downloads": 0,
        "releases": [],
    }
    if not repo_slug or "/" not in repo_slug:
        return result

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "HVLFamilyOffice-Telemetry/1.0",
    }
    try:
        repo_req = urllib.request.Request(f"https://api.github.com/repos/{repo_slug}", headers=headers)
        with urllib.request.urlopen(repo_req, timeout=3.5) as resp:
            repo_data = json.loads(resp.read().decode("utf-8"))
            if isinstance(repo_data, dict):
                result["available"] = True
                result["stars"] = int(repo_data.get("stargazers_count") or 0)
                result["forks"] = int(repo_data.get("forks_count") or 0)
                result["watchers"] = int(repo_data.get("subscribers_count") or repo_data.get("watchers_count") or 0)
    except Exception:
        pass

    try:
        rel_req = urllib.request.Request(
            f"https://api.github.com/repos/{repo_slug}/releases?per_page=10",
            headers=headers,
        )
        with urllib.request.urlopen(rel_req, timeout=3.5) as resp:
            rel_list = json.loads(resp.read().decode("utf-8"))
            if isinstance(rel_list, list):
                result["available"] = True
                total_dl = 0
                mac_dl = 0
                win_dl = 0
                releases_out = []
                for rel in rel_list:
                    if not isinstance(rel, dict):
                        continue
                    tag = str(rel.get("tag_name") or rel.get("name") or "Release")
                    pub_at = str(rel.get("published_at") or "")[:10]
                    rel_assets = []
                    rel_dl = 0
                    rel_mac = 0
                    rel_win = 0
                    for asset in rel.get("assets") or []:
                        if not isinstance(asset, dict):
                            continue
                        a_name = str(asset.get("name") or "")
                        a_count = int(asset.get("download_count") or 0)
                        total_dl += a_count
                        rel_dl += a_count
                        low_name = a_name.lower()
                        if any(ext in low_name for ext in (".dmg", "macos", "darwin", "mac")):
                            mac_dl += a_count
                            rel_mac += a_count
                        elif any(ext in low_name for ext in (".exe", ".msi", "windows", "win")):
                            win_dl += a_count
                            rel_win += a_count
                        rel_assets.append({"name": a_name, "download_count": a_count})
                    releases_out.append({
                        "tag": tag,
                        "published_at": pub_at,
                        "total_downloads": rel_dl,
                        "macos_downloads": rel_mac,
                        "windows_downloads": rel_win,
                        "html_url": str(rel.get("html_url") or f"https://github.com/{repo_slug}/releases/tag/{tag}"),
                        "assets": rel_assets,
                    })
                result["total_asset_downloads"] = total_dl
                result["macos_asset_downloads"] = mac_dl
                result["windows_asset_downloads"] = win_dl
                result["releases"] = releases_out
    except Exception:
        pass

    _GITHUB_TELEMETRY_CACHE["fetched_at"] = now_ts
    _GITHUB_TELEMETRY_CACHE["data"] = result
    return result




VALID_PORTAL_UNIVERSES = ("public", "sandbox", "demo", "admin")


def normalize_portal_universe(raw_universe: str | None) -> str:
    """Normalizes arbitrary universe identifiers to 'public', 'sandbox', 'demo', or 'admin'."""
    u = str(raw_universe or "").strip().lower()
    if u in ("beta", "demo"):
        return "demo"
    if u == "sandbox":
        return "sandbox"
    if u == "admin":
        return "admin"
    return "public"


def _ensure_portal_telemetry_table(conn: Any) -> None:
    """Ensures the `portal_telemetry_events` table and indices exist via SQLAlchemy 2.0 ORM metadata."""
    from db.models_ops import PortalTelemetryEvent, ensure_orm_table_on_conn
    ensure_orm_table_on_conn(conn, PortalTelemetryEvent)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(portal_telemetry_events)").fetchall()}
    if "tab" not in cols:
        try:
            conn.execute("ALTER TABLE portal_telemetry_events ADD COLUMN tab TEXT DEFAULT ''")
        except Exception:
            pass
    if "action" not in cols:
        try:
            conn.execute("ALTER TABLE portal_telemetry_events ADD COLUMN action TEXT DEFAULT ''")
        except Exception:
            pass
    if "modal" not in cols:
        try:
            conn.execute("ALTER TABLE portal_telemetry_events ADD COLUMN modal TEXT DEFAULT ''")
        except Exception:
            pass


def record_portal_telemetry_event(
    universe: str,
    event_type: str,
    feature_key: str = "",
    session_hash: str = "",
    meta: dict[str, Any] | None = None,
    db_path: Path | None = None,
    tab: str = "",
    action: str = "",
    modal: str = "",
) -> bool:
    """
    Records a zero-PII operational event in `portal_telemetry_events` in the primary global.db.
    Universes supported: 'public', 'sandbox', 'demo', 'admin'.
    """
    import config

    norm_uni = normalize_portal_universe(universe)
    evt = str(event_type or "").strip().lower()
    feat = str(feature_key or "").strip()[:100]
    sess = str(session_hash or "").strip()[:64]
    eff_tab = str(tab or "").strip()[:64]
    eff_act = str(action or "").strip()[:64]
    eff_mod = str(modal or "").strip()[:64]
    meta_str = json.dumps(meta or {}, default=str)

    target_db = Path(db_path) if db_path is not None else config.get_global_db_path("public")
    init_db(target_db)
    try:
        with get_db_connection(target_db) as conn:
            _ensure_portal_telemetry_table(conn)
            conn.execute(
                """
                INSERT INTO portal_telemetry_events (universe, event_type, feature_key, session_hash, meta_json, tab, action, modal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (norm_uni, evt, feat, sess, meta_str, eff_tab, eff_act, eff_mod),
            )
            conn.commit()
        return True
    except Exception:
        return False


from db.telemetry_queries import (
    get_download_telemetry_summary,
    get_portal_telemetry_summary,
)

__all__ = [
    "VALID_DOWNLOAD_TARGETS",
    "_DOWNLOAD_TARGET_ALIASES",
    "_GITHUB_TELEMETRY_CACHE",
    "resolve_download_redirect_target",
    "resolve_telemetry_db_path",
    "_ensure_download_events_table",
    "record_download_event",
    "_fetch_github_release_metrics",
    "get_download_telemetry_summary",
    "VALID_PORTAL_UNIVERSES",
    "normalize_portal_universe",
    "_ensure_portal_telemetry_table",
    "record_portal_telemetry_event",
    "get_portal_telemetry_summary",
]

