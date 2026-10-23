"""
Shared Multi-Universe Portal & Sandbox Lifecycle Telemetry (`hvl_common.telemetry.portal`).

Provides zero-PII operational event recording (`portal_telemetry_events`),
audience classification (`admin`, `sandbox`, `demo`, `public`), and anonymous
request session hashing across HVL multi-tenant applications.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from hvl_common.db import get_db_connection

VALID_PORTAL_UNIVERSES = ("public", "sandbox", "demo", "admin")

_PORTAL_TELEMETRY_DDL = """
CREATE TABLE IF NOT EXISTS portal_telemetry_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT, universe TEXT NOT NULL DEFAULT 'public',
    event_type TEXT NOT NULL, feature_key TEXT NOT NULL DEFAULT '',
    session_hash TEXT NOT NULL DEFAULT '', meta_json TEXT NOT NULL DEFAULT '{}',
    tab TEXT NOT NULL DEFAULT '', action TEXT NOT NULL DEFAULT '', modal TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_portal_telemetry_uni_evt ON portal_telemetry_events(universe, event_type, created_at);
"""


def normalize_portal_universe(raw_universe: str | None) -> str:
    """Normalizes arbitrary universe identifiers to 'public', 'sandbox', 'demo', or 'admin'."""
    u = str(raw_universe or "").strip().lower()
    if u in ("beta", "demo"):
        return "demo"
    return u if u in ("sandbox", "admin") else "public"


def _ensure_table_on_conn(conn: Any) -> None:
    """Ensures `portal_telemetry_events` and its columns exist on an open SQLite connection."""
    conn.executescript(_PORTAL_TELEMETRY_DDL)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(portal_telemetry_events)").fetchall()}
    for col in ("tab", "action", "modal"):
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE portal_telemetry_events ADD COLUMN {col} TEXT DEFAULT ''")
            except Exception:
                pass


def ensure_portal_telemetry_table(db_path: Path | str | Any) -> None:
    """Ensures the `portal_telemetry_events` table exists in `db_path` (or on an open connection)."""
    if hasattr(db_path, "execute"):
        _ensure_table_on_conn(db_path)
        return
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection(target) as conn:
        _ensure_table_on_conn(conn)
        conn.commit()


def compute_request_session_hash(cookie_names: tuple[str, ...] = ()) -> str:
    """Computes a zero-PII 16-char SHA-256 hash of the active browser session or vault cookie."""
    try:
        from flask import has_request_context, request

        if not has_request_context():
            return ""
        candidates = cookie_names or (
            "assistant_session", "assistant_beta_session", "session", "session_id",
            "hvl_sandbox_fid", "hvl_vault_fek", "fo_vault_fek",
        )
        raw_token = next((str(request.cookies.get(n)) for n in candidates if request.cookies.get(n)), "")
        if not raw_token:
            return ""
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return ""


def resolve_telemetry_audience(
    is_admin_fn: Callable[[], bool] | bool | None = None,
    is_sandbox_fn: Callable[[], bool] | bool | None = None,
    is_demo_fn: Callable[[], bool] | bool | None = None,
) -> str:
    """Resolves the canonical telemetry universe ('admin', 'sandbox', 'demo', 'public') for the active request."""
    def _eval(fn_or_val: Callable[[], bool] | bool | None) -> bool:
        try:
            return bool(fn_or_val() if callable(fn_or_val) else fn_or_val)
        except Exception:
            return False

    if _eval(is_admin_fn):
        return "admin"
    if _eval(is_sandbox_fn):
        return "sandbox"
    if _eval(is_demo_fn):
        return "demo"
    try:
        from flask import has_request_context, request, session

        if has_request_context():
            if request.args.get("admin") == "1":
                return "admin"
            if session.get("is_sandbox") or request.args.get("sandbox") == "1":
                return "sandbox"
            if session.get("is_demo") or request.args.get("demo") == "1":
                return "demo"
    except Exception:
        pass
    return "public"


def record_portal_telemetry_event(
    db_path: Path | str, universe: str, event_type: str, feature_key: str = "",
    session_hash: str = "", meta: dict[str, Any] | None = None,
    tab: str | None = None, action: str | None = None, modal: str | None = None,
) -> bool:
    """Records a zero-PII operational event in `portal_telemetry_events` in `db_path`."""
    evt = str(event_type or "").strip().lower()
    if not evt:
        return False
    params = (
        normalize_portal_universe(universe), evt, str(feature_key or "").strip()[:100],
        str(session_hash or compute_request_session_hash()).strip()[:64], json.dumps(meta or {}, default=str),
        str(tab or "").strip()[:64], str(action or "").strip()[:64], str(modal or "").strip()[:64],
    )
    target_db = Path(db_path)
    target_db.parent.mkdir(parents=True, exist_ok=True)
    try:
        with get_db_connection(target_db) as conn:
            _ensure_table_on_conn(conn)
            conn.execute(
                "INSERT INTO portal_telemetry_events (universe, event_type, feature_key, session_hash, meta_json, tab, action, modal) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            conn.commit()
        return True
    except Exception:
        return False


def get_portal_telemetry_counts(db_path: Path | str, days: int = 30) -> dict[str, Any]:
    """Returns per-universe event counts, unique session counts, and lifecycle counters."""
    default_keys = ("events", "unique_sessions", "sandbox_started", "sandbox_seeded_demo", "sandbox_saved_7d", "sandbox_wiped", "onboarding_completed", "ai_chat_turn", "tab_view", "ui_action")
    by_universe: dict[str, dict[str, int]] = {u: dict.fromkeys(default_keys, 0) for u in VALID_PORTAL_UNIVERSES}
    by_event: dict[str, int] = {}
    demo_personas: dict[str, int] = {}
    target = Path(db_path)
    if not target.exists():
        return {"by_universe": by_universe, "by_event": by_event, "demo_personas": demo_personas, "total_events": 0}
    try:
        with get_db_connection(target) as conn:
            _ensure_table_on_conn(conn)
            where = "WHERE created_at >= datetime('now', '-' || ? || ' days')" if days > 0 else ""
            params: tuple[Any, ...] = (int(days),) if days > 0 else ()
            for r in conn.execute(f"SELECT universe, COUNT(*), COUNT(DISTINCT CASE WHEN session_hash != '' THEN session_hash END) FROM portal_telemetry_events {where} GROUP BY universe", params).fetchall():
                u = normalize_portal_universe(r[0])
                by_universe[u]["events"] += int(r[1] or 0)
                by_universe[u]["unique_sessions"] += int(r[2] or 0)
            for r in conn.execute(f"SELECT universe, event_type, COUNT(*) FROM portal_telemetry_events {where} GROUP BY universe, event_type", params).fetchall():
                u = normalize_portal_universe(r[0])
                evt = str(r[1] or "")
                if evt:
                    by_universe[u][evt] = by_universe[u].get(evt, 0) + int(r[2] or 0)
                    by_event[evt] = by_event.get(evt, 0) + int(r[2] or 0)
            persona_where = f"{where} AND event_type = 'sandbox_seeded_demo'" if where else "WHERE event_type = 'sandbox_seeded_demo'"
            for r in conn.execute(f"SELECT feature_key, COUNT(*) FROM portal_telemetry_events {persona_where} GROUP BY feature_key", params).fetchall():
                if r[0]:
                    demo_personas[str(r[0])] = int(r[1] or 0)
    except Exception:
        pass
    total = sum(v["events"] for v in by_universe.values())
    return {"by_universe": by_universe, "by_event": by_event, "demo_personas": demo_personas, "total_events": total}
