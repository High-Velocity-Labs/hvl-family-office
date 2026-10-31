"""
Shared Ephemeral Sandbox Lifecycle, Lease Management, Storage Quotas, and Cookie Primitives.
Standardizes zero-login sandbox household provisioning, deterministic expiry, untouched/orphan
sweeping, and cookie-only FEK transport across High Velocity Labs applications.
"""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from hvl_common.db.sqlite import close_all_pools, get_db_connection
from hvl_common.security.crypto import VAULT_COOKIE_NAME, wrap_cookie_fek

logger = logging.getLogger(__name__)

SANDBOX_FID_COOKIE = "hvl_sandbox_fid"
SANDBOX_DEFAULT_TTL_SECONDS = 86400
SANDBOX_EXTENDED_TTL_SECONDS = 7 * 86400
SANDBOX_UNTOUCHED_TTL_SECONDS = 2 * 3600
SANDBOX_SURGE_UNTOUCHED_TTL_SECONDS = 15 * 60
MAX_ACTIVE_SANDBOX_FAMILIES = 1500
MAX_SANDBOX_DISK_MB = 2048

_SANDBOX_LEASES_DDL = """
CREATE TABLE IF NOT EXISTS sandbox_leases (
    family_id INTEGER PRIMARY KEY, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
    extended_7d INTEGER DEFAULT 0, seed_mode TEXT DEFAULT 'blank', session_hash TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sandbox_leases_exp ON sandbox_leases (expires_at);
"""
_LEASE_COLS = "family_id, created_at, expires_at, extended_7d, seed_mode, session_hash"


class SandboxCapacityError(RuntimeError):
    """Raised when sandbox storage or active household capacity is reached."""


def ensure_sandbox_leases_table(global_db: Path | str | Any) -> None:
    """Ensures the `sandbox_leases` tracking table exists in `global_db` (or on an active connection)."""
    if hasattr(global_db, "executescript"):
        global_db.executescript(_SANDBOX_LEASES_DDL)
        return
    db_path = Path(global_db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection(db_path) as conn:
        conn.executescript(_SANDBOX_LEASES_DDL)
        conn.commit()


def allocate_unique_sandbox_id(global_db: Path | str, tenant_table: str = "families") -> int:
    """Allocates a random 6-digit ID (100000..999999) not present in `sandbox_leases` or `tenant_table`."""
    if tenant_table not in ("families", "households"):
        raise ValueError(f"Unsupported tenant_table: {tenant_table}")
    pk_col, db_path = ("family_id" if tenant_table == "families" else "id"), Path(global_db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection(db_path) as conn:
        ensure_sandbox_leases_table(conn)
        has_tbl = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (tenant_table,)).fetchone())
        while True:
            tid = secrets.randbelow(899999) + 100000
            if conn.execute("SELECT 1 FROM sandbox_leases WHERE family_id = ?", (tid,)).fetchone():
                continue
            if not has_tbl or not conn.execute(f'SELECT 1 FROM "{tenant_table}" WHERE "{pk_col}" = ?', (tid,)).fetchone():
                return tid


def insert_sandbox_lease(
    global_db: Path | str, tenant_id: int, expires_at: int, seed_mode: str = "blank",
    created_at: int | None = None, session_hash: str = "",
) -> None:
    """Inserts or replaces a sandbox lease row in `global_db`."""
    now_ts = int(created_at if created_at is not None else time.time())
    with get_db_connection(Path(global_db)) as conn:
        ensure_sandbox_leases_table(conn)
        conn.execute(f"INSERT OR REPLACE INTO sandbox_leases ({_LEASE_COLS}) VALUES (?, ?, ?, 0, ?, ?)", (int(tenant_id), now_ts, int(expires_at), str(seed_mode or "blank"), str(session_hash or "")))
        conn.commit()


def list_all_sandbox_leases(global_db: Path | str) -> list[dict[str, Any]]:
    """Returns all rows from `sandbox_leases` as dictionaries."""
    db_path = Path(global_db)
    if not db_path.exists():
        return []
    try:
        with get_db_connection(db_path) as conn:
            ensure_sandbox_leases_table(conn)
            rows = conn.execute(f"SELECT {_LEASE_COLS} FROM sandbox_leases").fetchall()
            return [
                {"family_id": int(r[0]), "created_at": int(r[1] or 0), "expires_at": int(r[2] or 0), "extended_7d": int(r[3] or 0), "seed_mode": str(r[4] or "blank"), "session_hash": str(r[5] or "")}
                for r in rows if r and r[0] is not None
            ]
    except Exception as exc:
        logger.warning("Error querying sandbox leases: %s", exc)
        return []


def get_sandbox_lease_row(global_db: Path | str, tenant_id: int) -> dict[str, Any] | None:
    """Fetches the sandbox lease row for `tenant_id` as a dictionary, or None if not found."""
    tid = int(tenant_id)
    return next((r for r in list_all_sandbox_leases(global_db) if r["family_id"] == tid), None)


def format_lease_remaining(remaining_sec: int) -> str:
    """Formats remaining lease seconds identically to the client-side countdown formatter."""
    diff_sec = int(remaining_sec or 0)
    if diff_sec <= 0:
        return "Expired"
    days, hours, mins, secs = diff_sec // 86400, (diff_sec % 86400) // 3600, (diff_sec % 3600) // 60, diff_sec % 60
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    return f"{hours}h {mins:02d}m {secs:02d}s" if hours > 0 else f"{mins}m {secs:02d}s"


def build_sandbox_lease_info(global_db: Path | str, tenant_id: int, has_user_data_fn: Callable[[int], bool] | None = None) -> dict[str, Any] | None:
    """Builds the structured lease status dictionary for a sandbox tenant, or None if not found."""
    tid = int(tenant_id or 0)
    row = get_sandbox_lease_row(global_db, tid) if tid > 0 else None
    if not row:
        return None
    expires_at, rem_sec = int(row["expires_at"]), max(0, int(row["expires_at"]) - int(time.time()))
    return {
        "family_id": tid, "household_id": tid, "created_at": int(row["created_at"]), "expires_at": expires_at,
        "remaining_seconds": rem_sec, "countdown_str": format_lease_remaining(rem_sec), "extended_7d": bool(row["extended_7d"]),
        "seed_mode": str(row.get("seed_mode") or "blank"), "has_data": bool(has_user_data_fn(tid)) if has_user_data_fn is not None else False,
    }


def update_sandbox_lease_expiry(global_db: Path | str, tenant_id: int, expires_at: int, extended_7d: int = 1) -> None:
    """Updates `expires_at` and `extended_7d` for `tenant_id`, raising `ValueError` if not found."""
    tid = int(tenant_id)
    with get_db_connection(Path(global_db)) as conn:
        ensure_sandbox_leases_table(conn)
        if not conn.execute("SELECT 1 FROM sandbox_leases WHERE family_id = ?", (tid,)).fetchone():
            raise ValueError("Sandbox lease not found or already expired.")
        conn.execute("UPDATE sandbox_leases SET expires_at = ?, extended_7d = ? WHERE family_id = ?", (int(expires_at), int(extended_7d), tid))
        conn.commit()


def delete_sandbox_lease_row(global_db: Path | str, tenant_id: int) -> None:
    """Deletes the sandbox lease row for `tenant_id` from `global_db`."""
    db_path = Path(global_db)
    if db_path.exists():
        with get_db_connection(db_path) as conn:
            ensure_sandbox_leases_table(conn)
            conn.execute("DELETE FROM sandbox_leases WHERE family_id = ?", (int(tenant_id),))
            conn.commit()


def count_active_sandbox_leases(global_db: Path | str, now_ts: int | None = None) -> int:
    """Returns the count of sandbox leases in `global_db` (optionally filtering by `expires_at > now_ts`)."""
    rows = list_all_sandbox_leases(global_db)
    return sum(1 for r in rows if int(r["expires_at"]) > int(now_ts)) if now_ts is not None else len(rows)


def compute_sandbox_disk_usage_mb(universe_dir: Path | str) -> float:
    """Computes total disk usage in MB across `universe_dir` (including tenant subdirectories)."""
    u_path = Path(universe_dir)
    return round(sum(p.stat().st_size for p in u_path.rglob("*") if p.is_file()) / (1024 * 1024), 2) if u_path.exists() else 0.0


def enforce_sandbox_capacity(
    global_db: Path | str, universe_dir: Path | str, max_active: int = MAX_ACTIVE_SANDBOX_FAMILIES, max_disk_mb: int = MAX_SANDBOX_DISK_MB,
) -> None:
    """Raises `SandboxCapacityError` when active leases or disk usage reach configured limits."""
    if count_active_sandbox_leases(global_db) >= max_active or compute_sandbox_disk_usage_mb(universe_dir) >= max_disk_mb:
        raise SandboxCapacityError(f"Community Sandbox capacity is full ({max_active:,} households or {max_disk_mb} MB disk).")


def reap_expired_sandbox_leases(
    global_db: Path | str, tenants_dir: Path | str, delete_tenant_fn: Callable[[int], None],
    has_user_data_fn: Callable[[int], bool] | None = None, on_reap_fn: Callable[[int, str], None] | None = None,
    max_active: int = MAX_ACTIVE_SANDBOX_FAMILIES, untouched_ttl: int = SANDBOX_UNTOUCHED_TTL_SECONDS,
    surge_untouched_ttl: int = SANDBOX_SURGE_UNTOUCHED_TTL_SECONDS, extended_ttl: int = SANDBOX_EXTENDED_TTL_SECONDS,
) -> int:
    """Sweeps expired, untouched, and orphaned sandbox tenants and returns the count reaped."""
    now_ts, rows = int(time.time()), list_all_sandbox_leases(global_db)
    eff_ttl = surge_untouched_ttl if len(rows) >= (max_active // 2) else untouched_ttl
    to_reap: list[tuple[int, str]] = []
    for r in rows:
        tid = int(r["family_id"])
        if int(r["expires_at"]) <= now_ts:
            to_reap.append((tid, "expired_reaped"))
        elif not bool(r["extended_7d"]) and (now_ts - int(r["created_at"])) >= eff_ttl and has_user_data_fn and not has_user_data_fn(tid):
            to_reap.append((tid, "expired_untouched"))
    t_dir = Path(tenants_dir)
    if t_dir.exists():
        cutoff, seen = now_ts - extended_ttl, {tid for tid, _ in to_reap}
        for p in t_dir.glob("*.db"):
            stem = p.stem.replace("_cache", "")
            if stem.isdigit() and int(stem) not in seen and p.stat().st_mtime < cutoff:
                to_reap.append((int(stem), "expired_orphan"))
                seen.add(int(stem))
    reaped = 0
    for tid, reason in to_reap:
        try:
            delete_tenant_fn(tid)
            delete_sandbox_lease_row(global_db, tid)
            if on_reap_fn is not None:
                on_reap_fn(tid, reason)
            reaped += 1
        except Exception as exc:
            logger.warning("Failed to reap expired sandbox %s: %s", tid, exc)
    return reaped


def has_tenant_table_rows(tenant_db: Path | str, tables: Sequence[str] = ("lists", "memories", "calendar_events", "scheduled_reminders")) -> bool:
    """Returns True if any of `tables` in `tenant_db` contains at least one row (without decrypting)."""
    t_path = Path(tenant_db)
    if not t_path.exists():
        return False
    with get_db_connection(t_path) as conn:
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        return any(t in existing and conn.execute(f'SELECT 1 FROM "{t}" LIMIT 1').fetchone() for t in tables)


def scrub_sandbox_escrowed_feks(db_paths: Sequence[Path | str], tenant_id: int, tenant_table: str = "households") -> None:
    """Scrubs escrowed FEK columns to NULL on disk across the specified SQLite databases."""
    tid, pk_col = int(tenant_id), ("family_id" if tenant_table == "families" else "id")
    for raw_p in db_paths:
        p = Path(raw_p)
        if p.exists():
            with get_db_connection(p) as conn:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                if tenant_table in tables:
                    conn.execute(f'UPDATE "{tenant_table}" SET encryption_key_enc = NULL, support_access_enabled = 0 WHERE "{pk_col}" = ?', (tid,))
                if "household_members" in tables:
                    conn.execute("UPDATE household_members SET pending_fek_enc = NULL, google_vault_synced = 1 WHERE household_id = ?", (tid,))
                conn.commit()


def shred_sandbox_tenant_storage(
    global_db: Path | str, tenant_db: Path | str, tenant_id: int,
    cache_db: Path | str | None = None, tenant_table: str = "households",
) -> None:
    """Deletes tenant records in `global_db`, disposes SQLite pools, and unlinks tenant database files."""
    tid, pk_col, g_path = int(tenant_id), ("family_id" if tenant_table == "families" else "id"), Path(global_db)
    if g_path.exists():
        with get_db_connection(g_path) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "household_members" in tables:
                conn.execute("DELETE FROM household_members WHERE household_id = ?", (tid,))
            if tenant_table in tables:
                conn.execute(f'DELETE FROM "{tenant_table}" WHERE "{pk_col}" = ?', (tid,))
            if "sandbox_leases" in tables:
                conn.execute("DELETE FROM sandbox_leases WHERE family_id = ?", (tid,))
            conn.commit()
    for target in (tenant_db, cache_db):
        if target:
            close_all_pools(Path(target))
            for suffix in ("", "-wal", "-shm"):
                Path(f"{target}{suffix}").unlink(missing_ok=True)


def set_sandbox_vault_cookies(
    response: Any, raw_fek: bytes, kek: bytes | str, tenant_id: int = 0,
    max_age: int = SANDBOX_DEFAULT_TTL_SECONDS, cookie_name: str = VAULT_COOKIE_NAME,
    fid_cookie_name: str = SANDBOX_FID_COOKIE, is_secure: bool = False,
) -> None:
    """Wraps `raw_fek` and attaches the vault FEK and sandbox tenant ID cookies to `response`."""
    wrapped, sec = wrap_cookie_fek(raw_fek, kek), bool(is_secure)
    for c_name in {VAULT_COOKIE_NAME, cookie_name}:
        if c_name:
            response.set_cookie(str(c_name), wrapped, max_age=max_age, httponly=True, samesite="Lax", secure=sec, path="/")
    if int(tenant_id or 0) > 0 and fid_cookie_name:
        response.set_cookie(str(fid_cookie_name), str(int(tenant_id)), max_age=max_age, httponly=True, samesite="Lax", secure=sec, path="/")


def clear_sandbox_vault_cookies(
    response: Any, cookie_names: Sequence[str] = (VAULT_COOKIE_NAME, "hvl_vault_fek_beta"),
    fid_cookie_name: str = SANDBOX_FID_COOKIE,
) -> None:
    """Deletes sandbox vault FEK and tenant ID cookies from `response`."""
    for c_name in {*(cookie_names or ()), fid_cookie_name}:
        if c_name and hasattr(response, "delete_cookie"):
            response.delete_cookie(str(c_name), path="/")
