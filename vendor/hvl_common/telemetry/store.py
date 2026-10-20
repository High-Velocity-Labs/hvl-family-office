"""
Zero-Cost Operational Telemetry Store (`telemetry.db`).
Persists sanitized operational events (`ERROR_500`, `SLOW_REQUEST`, `RATE_LIMIT`, `JOB_ERROR`)
across High Velocity Labs services in a shared SQLite WAL database with automatic 1,000-row
ring-buffer pruning and strict zero-PII sanitation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from flask import current_app, has_app_context

from hvl_common.db.sqlite import _resolve_db_key, get_db_connection

logger = logging.getLogger(__name__)

EVENT_ERROR_500 = "ERROR_500"
EVENT_SLOW_REQUEST = "SLOW_REQUEST"
EVENT_RATE_LIMIT = "RATE_LIMIT"
EVENT_JOB_ERROR = "JOB_ERROR"

VALID_EVENT_TYPES: Set[str] = {
    EVENT_ERROR_500, EVENT_SLOW_REQUEST, EVENT_RATE_LIMIT, EVENT_JOB_ERROR,
}

_COMMON_ROOT = Path(__file__).resolve().parent.parent.parent
_APP_ROOT = _COMMON_ROOT.parent if _COMMON_ROOT.name == "vendor" else _COMMON_ROOT
_SHARED_ADMIN_DATA = Path("/var/www/admin/data")
_DEFAULT_TELEMETRY_DB = (
    _SHARED_ADMIN_DATA / "telemetry.db"
    if _SHARED_ADMIN_DATA.exists()
    else _APP_ROOT / "data" / "telemetry.db"
)

_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_QUERY_IN_TEXT_RE = re.compile(r"\?[^\s\"'<>]+")
_SECRET_KV_RE = re.compile(
    r"(?i)\b(bearer\s+|token\s*[=:]\s*|api[_-]?key\s*[=:]\s*|secret\s*[=:]\s*|password\s*[=:]\s*|passwd\s*[=:]\s*|session\s*[=:]\s*)([^\s,;\"'&]+)"
)

_init_lock = threading.Lock()
_initialized_dbs: Set[str] = set()


def get_default_telemetry_db_path(db_path: Optional[Union[str, Path]] = None) -> Path:
    """
    Resolves the operational `telemetry.db` path with priority:
    1. Explicit `db_path` argument
    2. Active Flask `current_app.config["TELEMETRY_DB_PATH"]`
    3. Environment variable `HVL_TELEMETRY_DB_PATH` or `TELEMETRY_DB_PATH`
    4. `<common_root>/data/telemetry.db`
    """
    if db_path is not None:
        return Path(db_path)
    if has_app_context():
        try:
            cfg_path = current_app.config.get("TELEMETRY_DB_PATH")
            if cfg_path:
                return Path(cfg_path)
        except Exception:
            pass
    env_path = os.getenv("HVL_TELEMETRY_DB_PATH") or os.getenv("TELEMETRY_DB_PATH")
    if env_path:
        return Path(env_path)
    return _DEFAULT_TELEMETRY_DB


def sanitize_telemetry_path(path: Optional[str], max_length: int = 200) -> str:
    """
    Sanitizes a request route path for telemetry logging.
    Strictly strips query strings (`?...`), fragments (`#...`), control characters,
    and email patterns so no query parameters or PII ever enter `telemetry.db`.
    """
    if not path:
        return ""
    cleaned = _CTRL_RE.sub("", str(path)).strip()
    cleaned = cleaned.split("?", 1)[0].split("#", 1)[0]
    cleaned = _EMAIL_RE.sub("[REDACTED_EMAIL]", cleaned)
    return cleaned[:max_length]


def sanitize_telemetry_detail(detail: Optional[str], max_length: int = 240) -> str:
    """
    Sanitizes a short telemetry detail summary.
    Strips control characters, URL query parameters, email addresses, and bearer/secret tokens.
    """
    if not detail:
        return ""
    cleaned = _CTRL_RE.sub(" ", str(detail)).strip()
    cleaned = _QUERY_IN_TEXT_RE.sub("", cleaned)
    cleaned = _EMAIL_RE.sub("[REDACTED_EMAIL]", cleaned)
    cleaned = _SECRET_KV_RE.sub(r"\1[REDACTED]", cleaned)
    return cleaned[:max_length]


def _ensure_telemetry_schema(db_path: Path) -> None:
    db_key = _resolve_db_key(db_path)
    if db_key in _initialized_dbs and db_path.exists():
        return
    with _init_lock:
        if db_key in _initialized_dbs and db_path.exists():
            return
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = get_db_connection(db_path, timeout=5.0)
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS telemetry_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        service TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        method TEXT NOT NULL DEFAULT '',
                        path TEXT NOT NULL DEFAULT '',
                        status_code INTEGER NOT NULL DEFAULT 0,
                        duration_ms REAL NOT NULL DEFAULT 0.0,
                        error_type TEXT NOT NULL DEFAULT '',
                        detail TEXT NOT NULL DEFAULT ''
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_created_at ON telemetry_events (created_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_service_type ON telemetry_events (service, event_type, id DESC);")
            _initialized_dbs.add(db_key)
        finally:
            conn.close()


class TelemetryStore:
    """
    Operational SQLite WAL telemetry store with automatic ring-buffer pruning.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None, max_rows: int = 1000) -> None:
        self._explicit_db_path = Path(db_path) if db_path is not None else None
        self.max_rows = max(1, int(max_rows))

    @property
    def db_path(self) -> Path:
        return get_default_telemetry_db_path(self._explicit_db_path)

    def record_event(
        self, service: str, event_type: str, *, method: str = "", path: str = "",
        status_code: int = 0, duration_ms: float = 0.0, error_type: str = "", detail: str = "",
    ) -> Optional[int]:
        """
        Inserts a sanitized telemetry event and prunes `telemetry_events` to `self.max_rows`.
        Never raises exceptions into application callers.
        """
        try:
            target_db = self.db_path
            _ensure_telemetry_schema(target_db)

            now = time.time()
            iso_ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
            clean_service = _CTRL_RE.sub("", str(service or "unknown")).strip()[:64] or "unknown"
            clean_event_type = _CTRL_RE.sub("", str(event_type or "ERROR_500")).strip().upper()[:32]
            if clean_event_type not in VALID_EVENT_TYPES:
                clean_event_type = EVENT_ERROR_500
            clean_method = _CTRL_RE.sub("", str(method or "")).strip().upper()[:16]
            clean_path = sanitize_telemetry_path(path, max_length=200)
            clean_status = int(status_code or 0)
            clean_duration = round(max(0.0, float(duration_ms or 0.0)), 2)
            clean_error_type = sanitize_telemetry_detail(error_type, max_length=80)
            clean_detail = sanitize_telemetry_detail(detail, max_length=240)

            conn = get_db_connection(target_db, timeout=5.0)
            try:
                with conn:
                    cur = conn.execute(
                        """
                        INSERT INTO telemetry_events (
                            timestamp, created_at, service, event_type,
                            method, path, status_code, duration_ms, error_type, detail
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            iso_ts, now, clean_service, clean_event_type, clean_method,
                            clean_path, clean_status, clean_duration, clean_error_type, clean_detail,
                        ),
                    )
                    row_id = int(cur.lastrowid) if cur.lastrowid is not None else None
                    conn.execute(
                        "DELETE FROM telemetry_events WHERE id NOT IN (SELECT id FROM telemetry_events ORDER BY id DESC LIMIT ?)",
                        (self.max_rows,),
                    )
                return row_id
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("TelemetryStore.record_event skipped: %s", exc)
            return None

    def get_events(
        self, *, service: Optional[str] = None, event_type: Optional[str] = None, limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Returns recent telemetry events ordered newest-first (`id DESC`).
        """
        target_db = self.db_path
        if not target_db.exists():
            return []
        try:
            _ensure_telemetry_schema(target_db)
            eff_limit = max(1, min(1000, int(limit or 100)))
            clauses: List[str] = []
            params: List[Any] = []
            if service:
                clauses.append("service = ?")
                params.append(str(service).strip())
            if event_type:
                clauses.append("event_type = ?")
                params.append(str(event_type).strip().upper())

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(eff_limit)

            conn = get_db_connection(target_db, timeout=5.0)
            try:
                cur = conn.execute(
                    f"""
                    SELECT id, timestamp, created_at, service, event_type,
                           method, path, status_code, duration_ms, error_type, detail
                    FROM telemetry_events {where_sql} ORDER BY id DESC LIMIT ?
                    """,
                    tuple(params),
                )
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("TelemetryStore.get_events failed: %s", exc)
            return []

    def get_summary(self, *, service: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns aggregate telemetry counts by `event_type`, `service`, and `recent_24h`.
        """
        empty_by_type = {
            EVENT_ERROR_500: 0, EVENT_SLOW_REQUEST: 0, EVENT_RATE_LIMIT: 0, EVENT_JOB_ERROR: 0,
        }
        summary: Dict[str, Any] = {
            "total_events": 0,
            EVENT_ERROR_500: 0,
            EVENT_SLOW_REQUEST: 0,
            EVENT_RATE_LIMIT: 0,
            EVENT_JOB_ERROR: 0,
            "by_type": dict(empty_by_type),
            "counts_by_type": dict(empty_by_type),
            "by_service": {},
            "by_service_24h": {},
            "recent_24h": {"total": 0, **empty_by_type},
        }
        target_db = self.db_path
        if not target_db.exists():
            return summary

        try:
            _ensure_telemetry_schema(target_db)
            cutoff_24h = time.time() - 86400.0
            where_sql = "WHERE service = ?" if service else ""
            params: Tuple[Any, ...] = (str(service).strip(),) if service else ()

            conn = get_db_connection(target_db, timeout=5.0)
            try:
                cur_type = conn.execute(
                    f"SELECT event_type, COUNT(*) AS cnt FROM telemetry_events {where_sql} GROUP BY event_type",
                    params,
                )
                total = 0
                for row in cur_type.fetchall():
                    et, cnt = str(row["event_type"]), int(row["cnt"])
                    total += cnt
                    summary[et] = cnt
                    summary["by_type"][et] = cnt
                    summary["counts_by_type"][et] = cnt
                summary["total_events"] = total

                cur_svc = conn.execute(
                    f"SELECT service, COUNT(*) AS cnt FROM telemetry_events {where_sql} GROUP BY service ORDER BY cnt DESC",
                    params,
                )
                summary["by_service"] = {str(row["service"]): int(row["cnt"]) for row in cur_svc.fetchall()}

                where_24h = "WHERE service = ? AND created_at >= ?" if service else "WHERE created_at >= ?"
                params_24h = (str(service).strip(), cutoff_24h) if service else (cutoff_24h,)
                cur_24h = conn.execute(
                    f"SELECT event_type, COUNT(*) AS cnt FROM telemetry_events {where_24h} GROUP BY event_type",
                    params_24h,
                )
                total_24h = 0
                for row in cur_24h.fetchall():
                    et, cnt = str(row["event_type"]), int(row["cnt"])
                    total_24h += cnt
                    summary["recent_24h"][et] = cnt
                summary["recent_24h"]["total"] = total_24h

                cur_svc_24h = conn.execute(
                    f"SELECT service, event_type, COUNT(*) AS cnt FROM telemetry_events {where_24h} GROUP BY service, event_type",
                    params_24h,
                )
                by_svc_24h: Dict[str, Dict[str, int]] = {}
                for row in cur_svc_24h.fetchall():
                    svc_name, et, cnt = str(row["service"]), str(row["event_type"]), int(row["cnt"])
                    bucket = by_svc_24h.setdefault(svc_name, {"total": 0, **empty_by_type})
                    bucket[et] = cnt
                    bucket["total"] += cnt
                summary["by_service_24h"] = by_svc_24h
                return summary
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("TelemetryStore.get_summary failed: %s", exc)
            return summary

    def clear_events(self, *, service: Optional[str] = None, event_type: Optional[str] = None) -> int:
        """
        Deletes telemetry events matching optional `service` and/or `event_type` filters.
        Returns the number of deleted rows.
        """
        target_db = self.db_path
        if not target_db.exists():
            return 0
        try:
            _ensure_telemetry_schema(target_db)
            clauses: List[str] = []
            params: List[Any] = []
            if service:
                clauses.append("service = ?")
                params.append(str(service).strip())
            if event_type:
                clauses.append("event_type = ?")
                params.append(str(event_type).strip().upper())

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            conn = get_db_connection(target_db, timeout=5.0)
            try:
                with conn:
                    cur = conn.execute(f"DELETE FROM telemetry_events {where_sql}", tuple(params))
                    return int(cur.rowcount or 0)
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("TelemetryStore.clear_events failed: %s", exc)
            return 0


def record_telemetry_event(
    service: str, event_type: str, *, method: str = "", path: str = "",
    status_code: int = 0, duration_ms: float = 0.0, error_type: str = "",
    detail: str = "", db_path: Optional[Union[str, Path]] = None, max_rows: int = 1000,
) -> Optional[int]:
    """Convenience function to record a single sanitized operational telemetry event."""
    return TelemetryStore(db_path=db_path, max_rows=max_rows).record_event(
        service=service, event_type=event_type, method=method, path=path,
        status_code=status_code, duration_ms=duration_ms, error_type=error_type, detail=detail,
    )


def get_telemetry_events(
    *, service: Optional[str] = None, event_type: Optional[str] = None,
    limit: int = 100, db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Convenience function to query recent operational telemetry events."""
    return TelemetryStore(db_path=db_path).get_events(service=service, event_type=event_type, limit=limit)


def get_telemetry_summary(
    *, service: Optional[str] = None, db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Convenience function to fetch operational telemetry aggregate counts."""
    return TelemetryStore(db_path=db_path).get_summary(service=service)


def clear_telemetry_events(
    *, service: Optional[str] = None, event_type: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Convenience function to clear operational telemetry events."""
    return TelemetryStore(db_path=db_path).clear_events(service=service, event_type=event_type)
