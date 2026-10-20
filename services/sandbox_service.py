"""
Interactive Ephemeral Sandbox Lifecycle and Quota Management Service.
Handles sandbox provisioning, deterministic expiry, sweeping, and storage quotas.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

import config
import security
from db.sandbox_repo import (
    allocate_unique_sandbox_fid,
    copy_fovault_to_sandbox_db,
    count_active_sandbox_leases,
    delete_sandbox_lease_in_db,
    ensure_sandbox_leases_table as _ensure_sandbox_leases_table,
    extend_sandbox_lease_in_db,
    get_sandbox_lease_row,
    has_sandbox_user_data_in_db,
    insert_sandbox_household_and_lease,
    list_all_sandbox_leases,
    register_restored_sandbox_in_global_db,
)
from db.telemetry import record_portal_telemetry_event
from security_store import init_db
from services.fovault_service import (
    PORTABLE_VAULT_FEK_KEY,
    extract_fek_from_backup_snapshot,
    inject_wrapped_fek_into_backup,
    remap_vault_family_id,
    scrub_escrowed_fek_in_sandbox_db,
)

logger = logging.getLogger(__name__)

MAX_SANDBOX_DISK_MB = 2048
MAX_ACTIVE_SANDBOX_FAMILIES = 1500
SANDBOX_DEFAULT_TTL_SECONDS = 86400  # 24 hours
SANDBOX_EXTENDED_TTL_SECONDS = 7 * 86400  # 7 days
SANDBOX_UNTOUCHED_TTL_SECONDS = 2 * 3600  # 2 hours for empty/abandoned sandboxes
SANDBOX_SURGE_UNTOUCHED_TTL_SECONDS = 15 * 60  # 15 minutes when >50% capacity


class SandboxCapacityError(Exception):
    """Raised when sandbox storage or active household capacity is reached."""


def _resolve_sandbox_families_dir() -> Path:
    sb_dir = (
        (config.get_universe_dir("sandbox") / "families")
        if hasattr(config, "get_universe_dir")
        else (config.get_data_dir() / "families_sandbox")
    )
    if not sb_dir.exists() and (config.get_data_dir() / "families_sandbox").exists():
        sb_dir = config.get_data_dir() / "families_sandbox"
    return sb_dir


def reap_expired_sandboxes() -> int:
    """
    Sweeps and shreds sandbox households whose leases have expired, plus:
    - Untouched/empty sandboxes (`has_sandbox_user_data == False`) older than 2 hours
      (or older than 15 minutes when active sandboxes exceed 50% capacity).
    - Orphan database files in `data/families_sandbox` older than 7 days.
    """
    glob_db = config.get_global_db_path("sandbox")
    init_db(glob_db)
    now_ts = int(time.time())
    reaped = 0

    rows = list_all_sandbox_leases(glob_db)
    total_leases = len(rows)
    untouched_ttl = (
        SANDBOX_SURGE_UNTOUCHED_TTL_SECONDS
        if total_leases >= (MAX_ACTIVE_SANDBOX_FAMILIES // 2)
        else SANDBOX_UNTOUCHED_TTL_SECONDS
    )

    fids_to_reap: list[tuple[int, str]] = []
    for r in rows:
        if not r or not r[0]:
            continue
        fid = int(r[0])
        created_at = int(r[1] or 0)
        expires_at = int(r[2] or 0)
        extended_7d = bool(r[3])
        if expires_at <= now_ts:
            fids_to_reap.append((fid, "expired_reaped"))
        elif not extended_7d and (now_ts - created_at) >= untouched_ttl:
            if not has_sandbox_user_data(fid):
                fids_to_reap.append((fid, "expired_untouched"))

    for fid, reason in fids_to_reap:
        try:
            wipe_sandbox_immediately(fid, reason=reason)
            reaped += 1
        except Exception as e:
            logger.warning(f"Failed to shred expired sandbox {fid}: {e}")

    try:
        sb_dir = _resolve_sandbox_families_dir()
        if sb_dir.exists():
            cutoff = now_ts - SANDBOX_EXTENDED_TTL_SECONDS
            for p in sb_dir.glob("*.db"):
                if p.stat().st_mtime < cutoff:
                    stem = p.stem.replace("_cache", "")
                    if stem.isdigit():
                        wipe_sandbox_immediately(int(stem), reason="expired_orphan")
                        reaped += 1
    except Exception:
        pass
    return reaped


def get_sandbox_storage_stats() -> dict[str, Any]:
    """Calculates active sandbox households and aggregate disk footprint across families_sandbox/."""
    glob_db = config.get_global_db_path("sandbox")
    init_db(glob_db)
    active_count = count_active_sandbox_leases(glob_db)

    total_bytes = 0
    try:
        sb_dir = _resolve_sandbox_families_dir()
        if sb_dir.exists():
            total_bytes = sum(p.stat().st_size for p in sb_dir.glob("*") if p.is_file())
        if glob_db.exists():
            total_bytes += glob_db.stat().st_size
    except Exception:
        pass

    return {
        "active_sandboxes": active_count,
        "disk_mb": round(total_bytes / (1024 * 1024), 2),
        "max_disk_mb": MAX_SANDBOX_DISK_MB,
        "max_families": MAX_ACTIVE_SANDBOX_FAMILIES,
    }


def _format_countdown_str(diff_sec: int) -> str:
    """Formats remaining lease seconds identically to the client-side formatCountdown()."""
    if diff_sec <= 0:
        return "Expired"
    days = diff_sec // 86400
    hours = (diff_sec % 86400) // 3600
    mins = (diff_sec % 3600) // 60
    secs = diff_sec % 60
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    if hours > 0:
        return f"{hours}h {mins:02d}m {secs:02d}s"
    return f"{mins}m {secs:02d}s"


def has_sandbox_user_data(family_id: int) -> bool:
    """Returns True if the sandbox household has entered any accounts, members, scenarios, equity grants, or encrypted settings."""
    fid = int(family_id or 0)
    if fid <= 0:
        return False
    fam_db = config.get_family_db_path(fid, "sandbox")
    return has_sandbox_user_data_in_db(fam_db, fid)


def get_sandbox_lease_info(family_id: int) -> dict[str, Any] | None:
    """Returns active lease details for a sandbox household, or None if not found."""
    fid = int(family_id or 0)
    if fid <= 0:
        return None
    glob_db = config.get_global_db_path("sandbox")
    row = get_sandbox_lease_row(glob_db, fid)
    if not row:
        return None
    now_ts = int(time.time())
    expires_at = int(row[1] or 0)
    rem_sec = max(0, expires_at - now_ts)
    return {
        "family_id": fid,
        "created_at": int(row[0] or 0),
        "expires_at": expires_at,
        "remaining_seconds": rem_sec,
        "countdown_str": _format_countdown_str(rem_sec),
        "extended_7d": bool(row[2]),
        "seed_mode": str(row[3] or "blank"),
        "has_data": has_sandbox_user_data(fid),
    }


def create_sandbox_session(seed_mode: str = "blank", session_hash: str = "") -> tuple[int, bytes, int]:
    """Provisions a fresh, isolated sandbox household with a cookie-only FEK."""
    reap_expired_sandboxes()
    stats = get_sandbox_storage_stats()
    if stats["active_sandboxes"] >= MAX_ACTIVE_SANDBOX_FAMILIES or stats["disk_mb"] >= MAX_SANDBOX_DISK_MB:
        raise SandboxCapacityError(
            "Community Sandbox capacity is currently full (1,500 active households or 2 GB disk). "
            "Please download your vault (.fovault) to continue locally, or try again later."
        )

    glob_db = config.get_global_db_path("sandbox")
    init_db(glob_db)
    fid = allocate_unique_sandbox_fid(glob_db)

    raw_fek = Fernet.generate_key()
    now_ts = int(time.time())
    expires_at = now_ts + SANDBOX_DEFAULT_TTL_SECONDS
    fam_db = config.get_family_db_path(fid, "sandbox")
    security.init_db(fam_db)

    insert_sandbox_household_and_lease(
        glob_db, fam_db, fid, now_ts, expires_at, seed_mode, session_hash
    )

    norm_seed = str(seed_mode or "").strip().lower()
    if norm_seed in ("demo", "sample", "1", "2", "3", "4", "5", "6", "jones", "miller", "chen"):
        from routes.helpers import reset_background_context, set_background_context
        bg_tok = set_background_context(family_id=fid, universe="sandbox", vault_fek=raw_fek)
        try:
            from flask import g
            if not hasattr(g, "_active_vault_feks") or not isinstance(g._active_vault_feks, dict):
                g._active_vault_feks = {}
            g._active_vault_feks[fid] = raw_fek
        except Exception:
            pass

        try:
            import scripts.seed_demo_families as seeder
            seed_map = {
                "2": seeder.seed_miller_family, "miller": seeder.seed_miller_family,
                "3": seeder.seed_chen_family, "chen": seeder.seed_chen_family,
                "4": seeder.seed_ramirez_family, "ramirez": seeder.seed_ramirez_family,
                "5": seeder.seed_taylor_family, "taylor": seeder.seed_taylor_family,
                "6": seeder.seed_foster_family, "foster": seeder.seed_foster_family,
            }
            seeder_fn = seed_map.get(norm_seed, seeder.seed_jones_family)
            seeder_fn(fam_db, family_id=fid, verbose=False)
        except Exception as e:
            logger.warning(f"Could not seed sample persona {seed_mode} for sandbox {fid}: {e}")
        finally:
            reset_background_context(bg_tok)

        scrub_escrowed_fek_in_sandbox_db(fam_db, fid, raw_fek=raw_fek)
        record_portal_telemetry_event("sandbox", "sandbox_seeded_demo", feature_key=norm_seed, session_hash=session_hash)

    record_portal_telemetry_event("sandbox", "sandbox_started", feature_key=norm_seed, session_hash=session_hash)
    return fid, raw_fek, expires_at


def extend_sandbox_lease_7d(family_id: int) -> dict[str, Any]:
    """Extends a sandbox household lease to now + 7 days."""
    fid = int(family_id or 0)
    if fid <= 0:
        raise ValueError("Valid sandbox family_id required.")

    stats = get_sandbox_storage_stats()
    if stats["disk_mb"] >= MAX_SANDBOX_DISK_MB or stats["active_sandboxes"] >= MAX_ACTIVE_SANDBOX_FAMILIES:
        raise SandboxCapacityError(
            "Community server 7-day storage slots are currently full. "
            "Please click 'Download Vault (.fovault)' to save your file locally."
        )

    glob_db = config.get_global_db_path("sandbox")
    now_ts = int(time.time())
    new_expires_at = now_ts + SANDBOX_EXTENDED_TTL_SECONDS
    extend_sandbox_lease_in_db(glob_db, fid, new_expires_at)

    record_portal_telemetry_event("sandbox", "sandbox_saved_7d", feature_key=str(fid))
    return {"status": "ok", "expires_at": new_expires_at, "remaining_seconds": SANDBOX_EXTENDED_TTL_SECONDS, "extended_7d": True}


def wipe_sandbox_immediately(family_id: int, reason: str = "manual") -> bool:
    """Permanently shreds a sandbox database, cache, and lease row immediately."""
    fid = int(family_id or 0)
    if fid <= 0:
        return False
    glob_db = config.get_global_db_path("sandbox")
    try:
        security.permanently_delete_family(glob_db, family_id=fid, universe="sandbox")
    except Exception as e:
        logger.warning(f"Error invoking permanently_delete_family for sandbox {fid}: {e}")

    delete_sandbox_lease_in_db(glob_db, fid)
    telemetry_event = "sandbox_expired_reaped" if "expired" in reason else "sandbox_wiped"
    record_portal_telemetry_event("sandbox", telemetry_event, feature_key=str(fid))
    return True


def restore_sandbox_from_fovault_bytes(
    raw_bytes: bytes, session_hash: str = "", target_fid: int = 0
) -> tuple[int, bytes, int]:
    """Restores an uploaded .fovault archive into an ephemeral sandbox household (reusing `target_fid` if provided)."""
    if len(raw_bytes) < 100 or not raw_bytes.startswith(b"SQLite format 3\x00"):
        raise ValueError("Invalid .fovault file: not a valid SQLite database archive.")

    reap_expired_sandboxes()
    stats = get_sandbox_storage_stats()
    if target_fid <= 0 and (
        stats["active_sandboxes"] >= MAX_ACTIVE_SANDBOX_FAMILIES or stats["disk_mb"] >= MAX_SANDBOX_DISK_MB
    ):
        raise SandboxCapacityError("Sandbox storage slots are full. Please try again later.")

    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".fovault")
    os.close(tmp_fd)
    tmp_path = Path(tmp_path_str)
    try:
        tmp_path.write_bytes(raw_bytes)
        import security_store
        is_valid, err_msg = security_store.validate_vault_snapshot_file(tmp_path)
        if not is_valid:
            raise ValueError(f"Vault snapshot validation failed: {err_msg}")

        raw_fek = extract_fek_from_backup_snapshot(tmp_path)
        if raw_fek is None:
            raw_fek = Fernet.generate_key()

        glob_db = config.get_global_db_path("sandbox")
        init_db(glob_db)
        new_fid = int(target_fid) if target_fid > 0 else allocate_unique_sandbox_fid(glob_db)

        now_ts = int(time.time())
        expires_at = now_ts + SANDBOX_DEFAULT_TTL_SECONDS
        fam_db = config.get_family_db_path(new_fid, "sandbox")

        copy_fovault_to_sandbox_db(tmp_path, fam_db)
        remap_vault_family_id(fam_db, new_fid)
        scrub_escrowed_fek_in_sandbox_db(fam_db, new_fid)
        security._clear_security_caches()
        security.stash_request_vault_fek(new_fid, raw_fek)
        security.init_db(fam_db)
        remap_vault_family_id(fam_db, new_fid)
        try:
            from db import store as _store
            _store.notify_family_mutation(new_fid)
        except Exception:
            pass

        register_restored_sandbox_in_global_db(glob_db, new_fid, now_ts, expires_at, session_hash)
        record_portal_telemetry_event("sandbox", "fovault_uploaded", feature_key=str(new_fid), session_hash=session_hash)
        return new_fid, raw_fek, expires_at
    finally:
        tmp_path.unlink(missing_ok=True)
