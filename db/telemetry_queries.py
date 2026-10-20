"""
Telemetry queries and aggregations for downloads, releases, and portal usage.
Extracted from db/telemetry.py for modularity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hvl_common.db import get_db_connection
from security_store import init_db


def get_download_telemetry_summary(
    db_path: Path,
    include_github_live: bool = False,
    force_github_refresh: bool = False,
) -> dict[str, Any]:
    """
    Aggregates first-party `/download/<target>` click telemetry from `global.db`
    and optionally combines it with GitHub Release asset download counts.
    """
    import config
    from db.telemetry import (
        VALID_DOWNLOAD_TARGETS,
        _ensure_download_events_table,
        _fetch_github_release_metrics,
    )

    counts_all = {k: 0 for k in VALID_DOWNLOAD_TARGETS}
    counts_7d = {k: 0 for k in VALID_DOWNLOAD_TARGETS}
    counts_30d = {k: 0 for k in VALID_DOWNLOAD_TARGETS}
    recent_events: list[dict[str, Any]] = []
    by_referrer: list[dict[str, Any]] = []

    target_db = Path(db_path)
    if target_db.exists():
        init_db(target_db)
        try:
            with get_db_connection(target_db) as conn:
                _ensure_download_events_table(conn)
                for row in conn.execute(
                    "SELECT target, COUNT(*) FROM download_events GROUP BY target"
                ).fetchall():
                    t_key = str(row[0] or "").strip().lower()
                    if t_key in counts_all:
                        counts_all[t_key] = int(row[1] or 0)

                for row in conn.execute(
                    "SELECT target, COUNT(*) FROM download_events WHERE created_at >= datetime('now', '-7 days') GROUP BY target"
                ).fetchall():
                    t_key = str(row[0] or "").strip().lower()
                    if t_key in counts_7d:
                        counts_7d[t_key] = int(row[1] or 0)

                for row in conn.execute(
                    "SELECT target, COUNT(*) FROM download_events WHERE created_at >= datetime('now', '-30 days') GROUP BY target"
                ).fetchall():
                    t_key = str(row[0] or "").strip().lower()
                    if t_key in counts_30d:
                        counts_30d[t_key] = int(row[1] or 0)

                referrer_map: dict[str, dict[str, Any]] = {}
                for row in conn.execute(
                    """
                    SELECT COALESCE(NULLIF(TRIM(referrer), ''), 'direct') AS ref,
                           target,
                           COUNT(*) AS cnt,
                           MAX(created_at) AS last_seen
                    FROM download_events
                    GROUP BY ref, target
                    """
                ).fetchall():
                    ref_name = str(row[0] or "direct")
                    t_target = str(row[1] or "").strip().lower()
                    cnt = int(row[2] or 0)
                    last_seen = str(row[3] or "")[:16].replace("T", " ")
                    if ref_name not in referrer_map:
                        referrer_map[ref_name] = {
                            "referrer": ref_name,
                            "macos": 0,
                            "windows": 0,
                            "github": 0,
                            "releases": 0,
                            "total": 0,
                            "last_seen": last_seen,
                        }
                    if t_target in referrer_map[ref_name]:
                        referrer_map[ref_name][t_target] += cnt
                    referrer_map[ref_name]["total"] += cnt
                    if last_seen > referrer_map[ref_name]["last_seen"]:
                        referrer_map[ref_name]["last_seen"] = last_seen

                by_referrer = sorted(referrer_map.values(), key=lambda r: r["total"], reverse=True)

                for row in conn.execute(
                    """
                    SELECT event_id, target, app_version, referrer, user_agent, created_at
                    FROM download_events
                    ORDER BY event_id DESC
                    LIMIT 25
                    """
                ).fetchall():
                    recent_events.append({
                        "event_id": int(row[0]),
                        "target": str(row[1] or ""),
                        "app_version": str(row[2] or ""),
                        "referrer": str(row[3] or ""),
                        "user_agent": str(row[4] or ""),
                        "created_at": str(row[5] or "")[:16].replace("T", " "),
                    })
        except Exception:
            pass

    github_metrics = (
        _fetch_github_release_metrics(config.GITHUB_REPO_SLUG, force_refresh=force_github_refresh)
        if include_github_live
        else {
            "available": False,
            "repo_slug": config.GITHUB_REPO_SLUG,
            "stars": 0,
            "forks": 0,
            "watchers": 0,
            "total_asset_downloads": 0,
            "macos_asset_downloads": 0,
            "windows_asset_downloads": 0,
            "releases": [],
        }
    )

    return {
        "total_events": sum(counts_all.values()),
        "total_7d": sum(counts_7d.values()),
        "total_30d": sum(counts_30d.values()),
        "counts_by_target": counts_all,
        "last_7d_by_target": counts_7d,
        "last_30d_by_target": counts_30d,
        "by_referrer": by_referrer,
        "recent_events": recent_events,
        "github": github_metrics,
    }


def get_portal_telemetry_summary(
    db_path: Path | None = None,
    days: int = 30,
    universe_filter: str | None = None,
) -> dict[str, Any]:
    """
    Aggregates operational, sandbox lifecycle, sync, rate limit, and AI usage telemetry
    from `portal_telemetry_events`.
    """
    import config
    from db.telemetry import (
        VALID_PORTAL_UNIVERSES,
        _ensure_portal_telemetry_table,
        normalize_portal_universe,
    )

    target_db = Path(db_path) if db_path is not None else config.get_global_db_path("public")
    by_universe = {
        u: {
            "events": 0,
            "unique_sessions": 0,
            "rate_limit_hits": 0,
            "ai_shared_calls": 0,
            "ai_byo_calls": 0,
            "syncs": 0,
            "fovault_downloads": 0,
            "fovault_uploads": 0,
        }
        for u in VALID_PORTAL_UNIVERSES
    }

    sandbox_lifecycle = {
        "started": 0,
        "seeded_demo": 0,
        "saved_7d": 0,
        "wiped": 0,
        "expired_reaped": 0,
        "fovault_downloaded": 0,
        "fovault_uploaded": 0,
        "active_sandboxes": 0,
        "disk_mb": 0.0,
    }

    ai_usage = {
        "shared_calls": 0,
        "byo_calls": 0,
        "pdf_ocr_calls": 0,
        "rate_limit_hits": 0,
    }

    rate_limits_by_scope: list[dict[str, Any]] = []
    recent_events: list[dict[str, Any]] = []

    try:
        from services.sandbox_service import get_sandbox_storage_stats
        s_stats = get_sandbox_storage_stats()
        sandbox_lifecycle["active_sandboxes"] = int(s_stats.get("active_sandboxes", 0))
        sandbox_lifecycle["disk_mb"] = float(s_stats.get("disk_mb", 0.0))
    except Exception:
        pass

    if target_db.exists():
        init_db(target_db)
        try:
            with get_db_connection(target_db) as conn:
                _ensure_portal_telemetry_table(conn)

                filter_clause = "WHERE created_at >= datetime('now', ? || ' days')"
                params: list[Any] = [f"-{int(days)}"]

                norm_filter = normalize_portal_universe(universe_filter) if universe_filter else None
                if norm_filter:
                    filter_clause += " AND universe = ?"
                    params.append(norm_filter)

                rows = conn.execute(
                    f"""
                    SELECT universe, event_type, COUNT(*), COUNT(DISTINCT CASE WHEN session_hash != '' THEN session_hash END)
                    FROM portal_telemetry_events
                    {filter_clause}
                    GROUP BY universe, event_type
                    """,
                    tuple(params),
                ).fetchall()

                uni_sess_rows = conn.execute(
                    f"""
                    SELECT universe, COUNT(*), COUNT(DISTINCT CASE WHEN session_hash != '' THEN session_hash END)
                    FROM portal_telemetry_events
                    {filter_clause}
                    GROUP BY universe
                    """,
                    tuple(params),
                ).fetchall()
                for r in uni_sess_rows:
                    u_key = str(r[0] or "").lower()
                    if u_key in by_universe:
                        by_universe[u_key]["events"] = int(r[1] or 0)
                        by_universe[u_key]["unique_sessions"] = int(r[2] or 0)

                for r in rows:
                    u_key = str(r[0] or "").lower()
                    e_type = str(r[1] or "").lower()
                    cnt = int(r[2] or 0)

                    if u_key in by_universe:
                        if e_type == "rate_limit_hit":
                            by_universe[u_key]["rate_limit_hits"] += cnt
                        elif "ai_shared" in e_type:
                            by_universe[u_key]["ai_shared_calls"] += cnt
                        elif "ai_byo" in e_type:
                            by_universe[u_key]["ai_byo_calls"] += cnt
                        elif any(k in e_type for k in ("monarch_sync", "simplefin_sync", "sync")):
                            by_universe[u_key]["syncs"] += cnt
                        elif e_type in ("fovault_downloaded", "vault_downloaded"):
                            by_universe[u_key]["fovault_downloads"] += cnt
                        elif e_type in ("fovault_uploaded", "vault_uploaded"):
                            by_universe[u_key]["fovault_uploads"] += cnt

                    if e_type in sandbox_lifecycle:
                        sandbox_lifecycle[e_type] += cnt
                    elif e_type in ("sandbox_started", "sandbox_created"):
                        sandbox_lifecycle["started"] += cnt
                    elif e_type == "vault_downloaded":
                        sandbox_lifecycle["fovault_downloaded"] += cnt
                    elif e_type == "vault_uploaded":
                        sandbox_lifecycle["fovault_uploaded"] += cnt

                    if "ai_shared" in e_type:
                        ai_usage["shared_calls"] += cnt
                    elif "ai_byo" in e_type:
                        ai_usage["byo_calls"] += cnt
                    elif "pdf_ocr" in e_type:
                        ai_usage["pdf_ocr_calls"] += cnt
                    elif e_type == "rate_limit_hit" and "ai" in e_type:
                        ai_usage["rate_limit_hits"] += cnt

                rl_rows = conn.execute(
                    f"""
                    SELECT feature_key, universe, COUNT(*), COUNT(DISTINCT CASE WHEN session_hash != '' THEN session_hash END)
                    FROM portal_telemetry_events
                    {filter_clause} AND event_type = 'rate_limit_hit'
                    GROUP BY feature_key, universe
                    ORDER BY COUNT(*) DESC
                    """,
                    tuple(params),
                ).fetchall()
                for rl in rl_rows:
                    rate_limits_by_scope.append({
                        "scope": str(rl[0] or "global_http"),
                        "universe": str(rl[1] or "public"),
                        "hits": int(rl[2] or 0),
                        "unique_sessions": int(rl[3] or 0),
                    })

                rec_rows = conn.execute(
                    f"""
                    SELECT event_id, universe, event_type, feature_key, session_hash, created_at
                    FROM portal_telemetry_events
                    {filter_clause}
                    ORDER BY event_id DESC
                    LIMIT 25
                    """,
                    tuple(params),
                ).fetchall()
                for rec in rec_rows:
                    recent_events.append({
                        "event_id": int(rec[0]),
                        "universe": str(rec[1] or ""),
                        "event_type": str(rec[2] or ""),
                        "feature_key": str(rec[3] or ""),
                        "session_hash": str(rec[4] or ""),
                        "created_at": str(rec[5] or "")[:16].replace("T", " "),
                    })
        except Exception:
            pass

    return {
        "days": days,
        "universe_filter": universe_filter,
        "by_universe": by_universe,
        "sandbox_lifecycle": sandbox_lifecycle,
        "rate_limits_by_scope": rate_limits_by_scope,
        "ai_usage": ai_usage,
        "recent_events": recent_events,
    }
