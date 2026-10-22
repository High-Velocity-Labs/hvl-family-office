"""
Household deletion quarantine, tenant cryptographic shredding, and cleanup audit routines.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Optional
from hvl_common.db import get_db_connection

_TENANT_CLEANUP_TABLES = (
    "advisor_messages", "advisor_conversations", "monarch_holdings", "monarch_accounts",
    "account_roles", "equity_grants", "equity_events", "equity_companies", "compensation",
    "tax_transcripts", "estate_trusts", "estate_beneficiaries", "gifting_records",
    "philanthropy_donations", "philanthropy_daf_accounts", "tuition_records",
    "forecast_scenarios", "family_encrypted_store", "family_state_versions", "household_profile",
)

_TENANT_CLEANUP_STATEMENTS: tuple[str, ...] = (
    "UPDATE families SET encryption_key_enc = NULL, support_access_enabled = 0 WHERE family_id = ?",
    "UPDATE users SET pending_fek_enc = NULL WHERE family_id = ?",
    *[f"DELETE FROM {t} WHERE family_id = ?" for t in _TENANT_CLEANUP_TABLES],
    "DELETE FROM invite_tokens WHERE created_by_family_id = ?",
    "DELETE FROM users WHERE family_id = ?",
    "DELETE FROM families WHERE family_id = ?",
)


def _parse_deletion_status_from_settings(parsed_settings: dict) -> Optional[dict]:
    """Parses active 30-day deletion quarantine metadata from a family settings dict."""
    if not isinstance(parsed_settings, dict):
        return None
    scheduled_at = parsed_settings.get("deletion_scheduled_at")
    purge_after = parsed_settings.get("deletion_purge_after")
    if not scheduled_at or not purge_after:
        return None

    now_dt = datetime.now(timezone.utc)
    try:
        purge_dt = datetime.fromisoformat(str(purge_after).replace("Z", "+00:00"))
        if purge_dt.tzinfo is None:
            purge_dt = purge_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

    seconds_left = (purge_dt - now_dt).total_seconds()
    days_remaining = max(0, int(math.ceil(seconds_left / 86400.0)))
    return {
        "is_scheduled": True,
        "scheduled_at": str(scheduled_at),
        "purge_after": str(purge_after),
        "purge_date_display": purge_dt.strftime("%b %d, %Y"),
        "days_remaining": days_remaining,
        "requested_by": str(parsed_settings.get("deletion_requested_by") or "Household Editor"),
        "is_expired": seconds_left <= 0,
    }


def get_family_deletion_status(
    db_path: Path,
    family_id: int = 0,
    universe: Optional[str] = None,
) -> Optional[dict]:
    """Returns active 30-day deletion quarantine status for family_id, or None if not scheduled."""
    import security

    fid = int(family_id or 0)
    if fid <= 0:
        return None

    for cand in security._candidate_family_metadata_dbs(Path(db_path), fid, universe=universe):
        if not cand.exists():
            continue
        try:
            with get_db_connection(cand, timeout=10.0) as conn:
                row = conn.execute("SELECT settings FROM families WHERE family_id = ?", (fid,)).fetchone()
                if row and row[0]:
                    parsed = json.loads(row[0]) if isinstance(row[0], str) else {}
                    status = _parse_deletion_status_from_settings(parsed)
                    if status is not None:
                        return status
        except Exception:
            continue
    return None


def schedule_family_deletion(
    db_path: Path,
    family_id: int = 0,
    requested_by: str = "",
    grace_days: int = 30,
    universe: Optional[str] = None,
) -> dict:
    """Places a household into a 30-day soft-delete quarantine."""
    import security
    from config import get_cache_db_path_for_universe
    from hvl_common.db.sqlite import close_all_pools

    fid = int(family_id or 0)
    if fid <= 0:
        raise ValueError("Valid family_id > 0 is required to schedule deletion.")

    uni = security._resolve_universe_from_db_path(Path(db_path), universe=universe)
    days = max(1, min(365, int(grace_days or 30)))
    now_dt = datetime.now(timezone.utc)
    purge_dt = now_dt + timedelta(days=days)
    scheduled_iso, purge_iso = now_dt.isoformat(), purge_dt.isoformat()
    actor = (requested_by or "Household Editor").strip()[:120]

    candidates = security._candidate_family_metadata_dbs(Path(db_path), fid, universe=uni)
    updated_any = False
    for cand in candidates:
        if not cand.exists():
            continue
        try:
            security.init_db(cand)
            with get_db_connection(cand, timeout=15.0) as conn:
                row = conn.execute("SELECT settings FROM families WHERE family_id = ?", (fid,)).fetchone()
                if not row:
                    continue
                try:
                    parsed = json.loads(row[0]) if row[0] else {}
                except Exception:
                    parsed = {}
                parsed = parsed if isinstance(parsed, dict) else {}
                parsed.update({
                    "deletion_scheduled_at": scheduled_iso,
                    "deletion_purge_after": purge_iso,
                    "deletion_requested_by": actor,
                })
                conn.execute(
                    "UPDATE families SET settings = ? WHERE family_id = ?",
                    (json.dumps(parsed), fid),
                )
                conn.commit()
                updated_any = True
        except Exception:
            continue

    if not updated_any:
        primary_cand = candidates[0]
        security.init_db(primary_cand)
        payload = json.dumps({
            "primary_state": "WA",
            "tax_filing_status": "MFJ",
            "deletion_scheduled_at": scheduled_iso,
            "deletion_purge_after": purge_iso,
            "deletion_requested_by": actor,
        })
        with get_db_connection(primary_cand, timeout=15.0) as conn:
            conn.execute("UPDATE families SET settings = ? WHERE family_id = ?", (payload, fid))
            conn.commit()

    try:
        from db import store as _store
        _store.invalidate_family(fid)
    except Exception:
        pass

    try:
        import forecast_cache
        forecast_cache.CACHE._evict_l1_prefix(f"{fid}:")
    except Exception:
        pass

    try:
        cache_db = get_cache_db_path_for_universe(uni, family_id=fid)
        close_all_pools(cache_db)
        for suffix in ("", "-wal", "-shm"):
            Path(f"{cache_db}{suffix}").unlink(missing_ok=True)
    except Exception:
        pass

    try:
        import monarch_service
        monarch_service.get_family_session_file(fid).unlink(missing_ok=True)
    except Exception:
        pass

    status = _parse_deletion_status_from_settings({
        "deletion_scheduled_at": scheduled_iso,
        "deletion_purge_after": purge_iso,
        "deletion_requested_by": actor,
    })
    assert status is not None
    return status


def cancel_family_deletion(
    db_path: Path,
    family_id: int = 0,
    universe: Optional[str] = None,
) -> bool:
    """Cancels a scheduled 30-day household deletion and restores normal access."""
    import security

    fid = int(family_id or 0)
    if fid <= 0:
        return False

    uni = security._resolve_universe_from_db_path(Path(db_path), universe=universe)
    for cand in security._candidate_family_metadata_dbs(Path(db_path), fid, universe=uni):
        if not cand.exists():
            continue
        try:
            with get_db_connection(cand, timeout=15.0) as conn:
                row = conn.execute("SELECT settings FROM families WHERE family_id = ?", (fid,)).fetchone()
                if not row:
                    continue
                try:
                    parsed = json.loads(row[0]) if row[0] else {}
                except Exception:
                    parsed = {}
                parsed = parsed if isinstance(parsed, dict) else {}
                for k in ("deletion_scheduled_at", "deletion_purge_after", "deletion_requested_by"):
                    parsed.pop(k, None)
                conn.execute("UPDATE families SET settings = ? WHERE family_id = ?", (json.dumps(parsed), fid))
                conn.commit()
        except Exception:
            continue

    try:
        from db import store as _store
        _store.notify_family_mutation(fid)
    except Exception:
        pass
    return True


def permanently_delete_family(
    db_path: Path,
    family_id: int = 0,
    universe: Optional[str] = None,
) -> dict:
    """Executes permanent cryptographic shredding and physical database file deletion for family_id."""
    import security
    from config import get_cache_db_path_for_universe, get_family_db_path, get_global_db_path
    from hvl_common.db.sqlite import close_all_pools

    fid = int(family_id or 0)
    if fid <= 0:
        raise ValueError("Valid family_id > 0 is required for permanent deletion.")

    uni = security._resolve_universe_from_db_path(Path(db_path), universe=universe)
    fam_db = get_family_db_path(fid, universe=uni)
    cache_db = get_cache_db_path_for_universe(uni, family_id=fid)
    glob_db = get_global_db_path(universe=uni)

    unlinked_files: list[str] = []
    family_dbs_to_unlink: list[Path] = [fam_db, cache_db]
    path_uni = security._resolve_universe_from_db_path(Path(db_path), universe=None)
    if path_uni != uni:
        family_dbs_to_unlink.extend([
            get_family_db_path(fid, universe=path_uni),
            get_cache_db_path_for_universe(path_uni, family_id=fid),
        ])

    shared_dbs: list[Path] = []
    for candidate in (glob_db, Path(db_path)):
        try:
            c_path = Path(candidate)
            if c_path.exists() and not any(t.exists() and c_path.resolve() == t.resolve() for t in family_dbs_to_unlink):
                if not any(c_path.resolve() == s.resolve() for s in shared_dbs):
                    shared_dbs.append(c_path)
        except Exception:
            continue

    for s_db in shared_dbs:
        try:
            with get_db_connection(s_db, timeout=15.0) as conn:
                for stmt in _TENANT_CLEANUP_STATEMENTS:
                    try:
                        conn.execute(stmt, (fid,))
                    except Exception:
                        continue
                conn.commit()
        except Exception:
            continue

    if fam_db.exists():
        try:
            with get_db_connection(fam_db, timeout=10.0) as conn:
                conn.execute(
                    "UPDATE families SET encryption_key_enc = NULL, support_access_enabled = 0 WHERE family_id = ?",
                    (fid,),
                )
                conn.execute("UPDATE users SET pending_fek_enc = NULL WHERE family_id = ?", (fid,))
                conn.commit()
        except Exception:
            pass

    for k in [k for k in list(security._FAMILY_KEY_CACHE) if k[1] == fid]:
        security._FAMILY_KEY_CACHE.pop(k, None)

    try:
        from db import store as _store
        _store.invalidate_family(fid)
    except Exception:
        pass

    try:
        import forecast_cache
        forecast_cache.CACHE._evict_l1_prefix(f"{fid}:")
    except Exception:
        pass

    import gc
    gc.collect()
    seen_targets: set[str] = set()
    for target_db in family_dbs_to_unlink:
        t_str = str(target_db)
        if t_str in seen_targets:
            continue
        seen_targets.add(t_str)
        try:
            close_all_pools(target_db)
        except Exception:
            pass
        security._DB_INIT_CACHE.discard(t_str)
        for suffix in ("", "-wal", "-shm"):
            f_path = Path(f"{target_db}{suffix}")
            if f_path.exists():
                try:
                    f_path.unlink(missing_ok=True)
                    if suffix == "":
                        unlinked_files.append(f_path.name)
                except Exception:
                    pass

    try:
        import monarch_service
        monarch_service.get_family_session_file(fid).unlink(missing_ok=True)
    except Exception:
        pass

    return {
        "family_id": fid,
        "permanently_deleted": True,
        "unlinked_files": unlinked_files,
    }


def purge_expired_deleted_families(db_path: Optional[Path] = None, universe: Optional[str] = None) -> list[int]:
    """Scans families and permanently shreds households whose 30-day grace period has expired."""
    import security
    from config import get_global_db_path

    uni = security._resolve_universe_from_db_path(Path(db_path) if db_path else Path("global.db"), universe=universe)
    target_db = Path(db_path) if db_path is not None else get_global_db_path(universe=uni)
    if not target_db.exists():
        return []

    expired_ids: list[int] = []
    try:
        with get_db_connection(target_db, timeout=10.0) as conn:
            for r in conn.execute("SELECT family_id, settings FROM families").fetchall():
                if r[0] and r[1]:
                    try:
                        status = _parse_deletion_status_from_settings(json.loads(r[1]))
                        if status and status.get("is_expired"):
                            expired_ids.append(int(r[0]))
                    except Exception:
                        continue
    except Exception:
        return []

    for fid in expired_ids:
        try:
            permanently_delete_family(target_db, family_id=fid, universe=uni)
        except Exception:
            pass
    return expired_ids
