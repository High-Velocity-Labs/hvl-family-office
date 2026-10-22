"""
Pane Bug Reporter & Admin Bug Queue Database Repository.
Stores anonymized client bug reports, triage diagnostics, and status in global.db.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional, Union

from hvl_common.db import get_db_connection
from security_store import init_db


def resolve_bugs_db_path() -> Path:
    """
    Resolves the global SQLite database path for site-wide bug reports.
    Honors test monkeypatches on `auth_google.DB_PATH` and otherwise resolves
    `config.get_global_db_path()`.
    """
    import sys
    import config

    ag = sys.modules.get("auth_google")
    if ag is not None and hasattr(ag, "DB_PATH"):
        ag_db = getattr(ag, "DB_PATH")
        if isinstance(ag_db, Path):
            return ag_db
    return config.get_global_db_path()


def _resolve_peer_bugs_sources(db_path: Optional[Union[str, Path]] = None) -> list[tuple[Path, Optional[str]]]:
    """Returns [(primary_db, None)] plus peer beta/prod global.db on the host if present."""
    import os
    primary = Path(db_path) if db_path is not None else resolve_bugs_db_path()
    sources: list[tuple[Path, Optional[str]]] = [(primary, None)]
    if db_path is not None:
        return sources
    peer_candidates: list[tuple[Path, str]] = []
    env_beta = os.getenv("FINANCES_BETA_GLOBAL_DB_PATH", "").strip()
    if env_beta:
        peer_candidates.append((Path(env_beta), "finances-beta"))
    try:
        if len(primary.parents) >= 3:
            app_root = primary.parents[2]
            base_name = app_root.name.removesuffix("-beta")
            peer_candidates.extend([
                (app_root.parent / f"{base_name}-beta" / "data" / "public" / "global.db", f"{base_name}-beta"),
                (app_root.parent / base_name / "data" / "public" / "global.db", base_name),
            ])
    except Exception:
        pass
    seen = {str(primary.resolve()) if primary.exists() else str(primary)}
    for cand, forced_proj in peer_candidates:
        if cand.exists():
            rk = str(cand.resolve())
            if rk not in seen:
                seen.add(rk)
                sources.append((cand, forced_proj))
    return sources


def _ensure_bug_reports_table(conn: Any) -> None:
    """Ensures the bug_reports table exists in the target SQLite database via SQLAlchemy 2.0 ORM metadata."""
    from db.models_ops import BugReport, ensure_orm_table_on_conn
    ensure_orm_table_on_conn(conn, BugReport)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bug_reports)").fetchall()}
    if "project" not in cols:
        conn.execute("ALTER TABLE bug_reports ADD COLUMN project TEXT NOT NULL DEFAULT 'finances'")
    if "app_version" not in cols:
        conn.execute("ALTER TABLE bug_reports ADD COLUMN app_version TEXT NOT NULL DEFAULT ''")


def _row_to_bug_dict(row: Any, force_project: Optional[str] = None) -> dict[str, Any]:
    """Helper to convert a sqlite3.Row to a dictionary with parsed snapshot JSON."""
    snapshot_raw = row["sanitized_snapshot_json"] or "{}"
    try:
        sanitized_snapshot = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else dict(snapshot_raw)
    except Exception:
        sanitized_snapshot = {}

    keys = row.keys() if hasattr(row, "keys") else ()
    proj = str(row["project"] or "finances") if "project" in keys else "finances"
    app_ver = str(row["app_version"] or "") if "app_version" in keys else ""
    if not app_ver and isinstance(sanitized_snapshot, dict):
        app_ver = str(sanitized_snapshot.get("app_version") or "")
    if force_project:
        proj = force_project
    elif proj == "finances" and app_ver.lower().startswith("finances-beta"):
        proj = "finances-beta"

    import config
    return {
        "bug_id": int(row["bug_id"]),
        "project": proj,
        "app_version": app_ver,
        "created_at": int(row["created_at"]),
        "updated_at": int(row["updated_at"]),
        "status": str(row["status"]),
        "universe": config.normalize_universe(str(row["universe"] or "public")),
        "family_id": int(row["family_id"] or 0),
        "user_role": str(row["user_role"] or "viewer"),
        "user_ref": str(row["user_ref"] or ""),
        "support_access_enabled": bool(row["support_access_enabled"]),
        "pane": str(row["pane"] or "overview"),
        "category": str(row["category"] or "math"),
        "scrubbed_description": str(row["scrubbed_description"] or ""),
        "scrubbed_followup": str(row["scrubbed_followup"] or ""),
        "ai_explanation": str(row["ai_explanation"] or ""),
        "suspected_module": str(row["suspected_module"] or ""),
        "invariant_summary": str(row["invariant_summary"] or ""),
        "scale_factor": None,
        "anonymization_mode": str(row["anonymization_mode"] or "isomorphic_scale"),
        "sanitized_snapshot_json": str(snapshot_raw),
        "sanitized_snapshot": sanitized_snapshot,
        "admin_notes": str(row["admin_notes"] or ""),
    }


def insert_bug_report(db_path: Optional[Union[str, Path]] = None, **kwargs: Any) -> int:
    """
    Inserts a new bug report row.
    Enforces storage hygiene: if total rows exceed 500, deletes oldest resolved/dismissed
    (or oldest overall) records to keep table bounded.
    Returns bug_id.
    """
    import config
    target_db = Path(db_path) if db_path is not None else resolve_bugs_db_path()
    init_db(target_db)
    now = int(time.time())

    project = str(kwargs.get("project") or "finances").strip().lower()
    app_version = str(kwargs.get("app_version") or "").strip()[:80]
    created_at = int(kwargs.get("created_at") or now)
    updated_at = int(kwargs.get("updated_at") or now)
    status = str(kwargs.get("status") or "open").strip().lower()
    universe = config.normalize_universe(str(kwargs.get("universe") or "public"))
    family_id = int(kwargs.get("family_id") or 0)
    user_role = str(kwargs.get("user_role") or "viewer").strip().lower()
    user_ref = str(kwargs.get("user_ref") or "").strip()
    support_access_enabled = 1 if kwargs.get("support_access_enabled") else 0
    pane = str(kwargs.get("pane") or "overview").strip().lower()
    category = str(kwargs.get("category") or "math").strip().lower()
    scrubbed_description = str(kwargs.get("scrubbed_description") or "").strip()
    scrubbed_followup = str(kwargs.get("scrubbed_followup") or "").strip()
    ai_explanation = str(kwargs.get("ai_explanation") or "").strip()
    suspected_module = str(kwargs.get("suspected_module") or "").strip()
    invariant_summary = str(kwargs.get("invariant_summary") or "").strip()
    scale_factor = 0.0
    anonymization_mode = str(kwargs.get("anonymization_mode") or "isomorphic_scale").strip().lower()

    snapshot_raw = kwargs.get("sanitized_snapshot_json")
    if isinstance(snapshot_raw, (dict, list)):
        snapshot_json = json.dumps(snapshot_raw)
    elif isinstance(snapshot_raw, str) and snapshot_raw.strip():
        snapshot_json = snapshot_raw.strip()
    else:
        snapshot_json = "{}"
    admin_notes = str(kwargs.get("admin_notes") or "").strip()

    with get_db_connection(target_db) as conn:
        _ensure_bug_reports_table(conn)

        cur = conn.execute("SELECT COUNT(*) FROM bug_reports")
        total_count = cur.fetchone()[0]
        if total_count >= 500:
            prune_target = total_count - 490
            cur = conn.execute(
                """
                DELETE FROM bug_reports
                WHERE bug_id IN (
                    SELECT bug_id FROM bug_reports
                    WHERE status IN ('resolved', 'dismissed')
                    ORDER BY created_at ASC, bug_id ASC
                    LIMIT ?
                )
                """,
                (prune_target,),
            )
            pruned = cur.rowcount
            remaining = prune_target - pruned
            if remaining > 0:
                conn.execute(
                    """
                    DELETE FROM bug_reports
                    WHERE bug_id IN (
                        SELECT bug_id FROM bug_reports
                        ORDER BY created_at ASC, bug_id ASC
                        LIMIT ?
                    )
                    """,
                    (remaining,),
                )

        cursor = conn.execute(
            """
            INSERT INTO bug_reports (
                project, app_version, created_at, updated_at, status, universe, family_id,
                user_role, user_ref, support_access_enabled, pane, category,
                scrubbed_description, scrubbed_followup, ai_explanation,
                suspected_module, invariant_summary, scale_factor,
                anonymization_mode, sanitized_snapshot_json, admin_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project,
                app_version,
                created_at,
                updated_at,
                status,
                universe,
                family_id,
                user_role,
                user_ref,
                support_access_enabled,
                pane,
                category,
                scrubbed_description,
                scrubbed_followup,
                ai_explanation,
                suspected_module,
                invariant_summary,
                scale_factor,
                anonymization_mode,
                snapshot_json,
                admin_notes,
            ),
        )
        return int(cursor.lastrowid)


def list_bug_reports(
    db_path: Optional[Union[str, Path]] = None,
    status: Optional[str] = None,
    universe: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Returns list of bug report dicts ordered by created_at DESC, bug_id DESC.
    Parses sanitized_snapshot_json into sanitized_snapshot dict.
    """
    bounded_limit = max(1, min(limit, 500))
    clean_status = str(status).strip().lower() if status and str(status).strip().lower() != "all" else None
    clean_uni = str(universe).strip().lower() if universe and str(universe).strip().lower() != "all" else None
    clean_proj = str(project).strip().lower() if project and str(project).strip().lower() != "all" else None

    out: list[dict[str, Any]] = []
    for src_db, forced_proj in _resolve_peer_bugs_sources(db_path):
        init_db(src_db)
        with get_db_connection(src_db) as conn:
            _ensure_bug_reports_table(conn)
            for r in conn.execute("SELECT * FROM bug_reports").fetchall():
                item = _row_to_bug_dict(r, force_project=forced_proj)
                if clean_status and item["status"].lower() != clean_status:
                    continue
                if clean_uni and item["universe"].lower() != clean_uni:
                    continue
                if clean_proj and item["project"].lower() != clean_proj:
                    continue
                out.append(item)
    out.sort(key=lambda x: (int(x["created_at"]), int(x["bug_id"])), reverse=True)
    return out[:bounded_limit]


def get_bug_report(bug_id: int, db_path: Optional[Union[str, Path]] = None) -> Optional[dict[str, Any]]:
    """Returns a single bug report by bug_id, or None."""
    target_db = Path(db_path) if db_path is not None else resolve_bugs_db_path()
    init_db(target_db)
    with get_db_connection(target_db) as conn:
        _ensure_bug_reports_table(conn)
        cursor = conn.execute(
            "SELECT * FROM bug_reports WHERE bug_id = ?",
            (int(bug_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_bug_dict(row)


def update_bug_report_status(
    bug_id: int,
    status: str,
    admin_notes: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Updates bug report status and optional admin_notes."""
    now = int(time.time())
    clean_status = str(status).strip().lower()

    for src_db, _ in _resolve_peer_bugs_sources(db_path):
        init_db(src_db)
        with get_db_connection(src_db) as conn:
            _ensure_bug_reports_table(conn)
            if admin_notes is not None:
                cur = conn.execute(
                    "UPDATE bug_reports SET status = ?, admin_notes = ?, updated_at = ? WHERE bug_id = ?",
                    (clean_status, str(admin_notes).strip(), now, int(bug_id)),
                )
            else:
                cur = conn.execute(
                    "UPDATE bug_reports SET status = ?, updated_at = ? WHERE bug_id = ?",
                    (clean_status, now, int(bug_id)),
                )
            if cur.rowcount > 0:
                return True
    return False


def get_bug_queue_counts(
    db_path: Optional[Union[str, Path]] = None,
    project: Optional[str] = None,
) -> dict[str, Any]:
    """
    Returns aggregate counts of bug reports by status and project:
    {'total': N, 'open': N, 'investigating': N, 'resolved': N, 'dismissed': N, 'by_project': {...}}
    """
    clean_proj = str(project).strip().lower() if project and str(project).strip().lower() != "all" else None
    counts: dict[str, Any] = {
        "total": 0,
        "open": 0,
        "investigating": 0,
        "resolved": 0,
        "dismissed": 0,
        "by_project": {"all": 0, "finances": 0, "finances-beta": 0, "ff": 0, "apex": 0},
    }
    for src_db, forced_proj in _resolve_peer_bugs_sources(db_path):
        init_db(src_db)
        with get_db_connection(src_db) as conn:
            _ensure_bug_reports_table(conn)
            for r in conn.execute("SELECT * FROM bug_reports").fetchall():
                item = _row_to_bug_dict(r, force_project=forced_proj)
                p = item["project"].lower()
                st = item["status"].lower()
                counts["by_project"][p] = counts["by_project"].get(p, 0) + 1
                counts["by_project"]["all"] += 1
                if clean_proj is None or p == clean_proj:
                    if st in counts:
                        counts[st] += 1
                    counts["total"] += 1
    return counts
