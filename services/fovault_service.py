"""
Portable Vault (.fovault) Backup, Cross-Instance FEK Packaging, and Family ID Remapping Service.
Enables seamless movement of encrypted household SQLite vaults between Anonymous Workspace (Sandbox),
Google OAuth Cloud Vault, and Standalone Local Desktop Mode.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from typing import Any

import config
from db.fovault_repo import (
    PORTABLE_VAULT_FEK_KEY,
    copy_sqlite_backup,
    extract_fek_from_backup_snapshot,
    get_vault_import_summary,
    inject_wrapped_fek_into_backup,
    remap_vault_family_id,
    scrub_escrowed_fek_in_sandbox_db,
)
from db.telemetry import record_portal_telemetry_event
from db.vault_migration import (
    has_cloud_vault_financial_data,
    reconcile_cloud_vault_auth_after_restore,
    rotate_sqlite_fernet_tokens,
    snapshot_cloud_vault_auth_state,
)
import security
import security_store

__all__ = [
    "PORTABLE_VAULT_FEK_KEY",
    "remap_vault_family_id",
    "inject_wrapped_fek_into_backup",
    "extract_fek_from_backup_snapshot",
    "scrub_escrowed_fek_in_sandbox_db",
    "build_fovault_backup_bytes",
    "apply_fovault_restore_to_db",
    "get_vault_import_summary",
    "migrate_active_sandbox_to_cloud_vault",
]


def build_fovault_backup_bytes(
    src_db: Path, family_id: int, is_sandbox: bool = False, is_local: bool = False
) -> tuple[bytes, str]:
    """Creates a consistent `.fovault` SQLite snapshot with portable FEK packaging and returns `(bytes, filename)`."""
    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".fovault")
    os.close(tmp_fd)
    tmp_path = Path(tmp_path_str)
    try:
        copy_sqlite_backup(src_db, tmp_path)
        try:
            inject_wrapped_fek_into_backup(src_db, tmp_path, family_id)
        except Exception:
            pass
        if is_sandbox:
            record_portal_telemetry_event("sandbox", "fovault_downloaded", feature_key=str(family_id))
        else:
            record_portal_telemetry_event("public", "fovault_downloaded", feature_key=str(family_id))
        data_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return data_bytes, f"ai_family_office_vault_{family_id}_{date_tag}.fovault"


def apply_fovault_restore_to_db(
    raw_bytes: bytes,
    dst_db: Path,
    family_id: int,
    is_sandbox: bool = False,
    is_local: bool = False,
    backup_dir: Path | None = None,
    universe: str = "public",
) -> tuple[bool, str, bytes | None]:
    """
    Validates and restores `.fovault` bytes into `dst_db`, remapping `family_id` and handling
    FEK escrow/scrubbing across Anonymous Workspace (Sandbox), Cloud Vault, and Local Desktop Mode.
    """
    if len(raw_bytes) < 100 or not raw_bytes.startswith(b"SQLite format 3\x00"):
        return False, "Invalid .fovault file: not a valid SQLite vault archive.", None

    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".fovault")
    os.close(tmp_fd)
    tmp_path = Path(tmp_path_str)
    try:
        tmp_path.write_bytes(raw_bytes)
        is_valid, err_msg = security_store.validate_vault_snapshot_file(tmp_path)
        if not is_valid:
            return False, err_msg, None

        if dst_db.exists() and is_local and backup_dir is not None:
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            pre_restore_path = backup_dir / f"pre_restore_family_{family_id}_{ts}.fovault"
            copy_sqlite_backup(dst_db, pre_restore_path)

        global_db = config.get_global_db_path(universe)
        is_cloud_vault = not is_sandbox and not is_local
        cloud_snapshot: dict[str, Any] = {}
        if is_cloud_vault:
            cloud_snapshot = snapshot_cloud_vault_auth_state(global_db, dst_db, family_id)

        extracted_fek = extract_fek_from_backup_snapshot(tmp_path)
        copy_sqlite_backup(tmp_path, dst_db)
        remap_vault_family_id(dst_db, family_id)
        security._clear_security_caches()

        active_fek = extracted_fek
        if is_sandbox:
            if extracted_fek:
                security.stash_request_vault_fek(family_id, extracted_fek)
            scrub_escrowed_fek_in_sandbox_db(dst_db, family_id)
        elif is_local and extracted_fek:
            security.stash_request_vault_fek(family_id, extracted_fek)
            scrub_escrowed_fek_in_sandbox_db(dst_db, family_id)
            security.escrow_local_vault_key(global_db, dst_db, extracted_fek, family_id=family_id)
        elif is_cloud_vault:
            cloud_fek = cloud_snapshot.get("cloud_fek") or extracted_fek
            if cloud_fek and extracted_fek and cloud_fek != extracted_fek:
                rotate_sqlite_fernet_tokens(dst_db, extracted_fek, cloud_fek)
            active_fek = cloud_fek
            if active_fek:
                security.stash_request_vault_fek(family_id, active_fek)
                reconcile_cloud_vault_auth_after_restore(
                    global_db, dst_db, family_id, active_fek, cloud_snapshot, PORTABLE_VAULT_FEK_KEY
                )

        security.init_db(dst_db)
        remap_vault_family_id(dst_db, family_id)
        try:
            from db import store as _store

            _store.notify_family_mutation(family_id)
        except Exception:
            pass

        record_portal_telemetry_event(
            "sandbox" if is_sandbox else "public", "fovault_uploaded", feature_key=str(family_id)
        )
        return True, "", active_fek
    finally:
        tmp_path.unlink(missing_ok=True)


def migrate_active_sandbox_to_cloud_vault(
    sandbox_fid: int,
    sandbox_fek: bytes,
    cloud_fid: int,
    cloud_fek: bytes,
    force_overwrite: bool = False,
) -> bool:
    """
    Migrates an active Anonymous Workspace (`sandbox_fid`) directly into a user's authenticated
    Google Cloud Vault (`cloud_fid`), re-encrypting all records under `cloud_fek` and shredding
    the temporary sandbox database upon completion.
    """
    from services.sandbox_service import has_sandbox_user_data, wipe_sandbox_immediately

    if sandbox_fid <= 0 or cloud_fid <= 0 or not sandbox_fek or not cloud_fek:
        return False
    if not has_sandbox_user_data(sandbox_fid):
        return False
    if not force_overwrite and has_cloud_vault_financial_data(cloud_fid, universe="public"):
        return False

    sb_db = config.get_family_db_path(sandbox_fid, "sandbox")
    if not sb_db.exists():
        return False

    security.stash_request_vault_fek(sandbox_fid, sandbox_fek)
    raw_bytes, _ = build_fovault_backup_bytes(sb_db, sandbox_fid, is_sandbox=True, is_local=False)

    security.stash_request_vault_fek(cloud_fid, cloud_fek)
    cloud_db = config.get_family_db_path(cloud_fid, "public")
    ok, _, _ = apply_fovault_restore_to_db(
        raw_bytes,
        cloud_db,
        cloud_fid,
        is_sandbox=False,
        is_local=False,
        universe="public",
    )
    if ok:
        try:
            wipe_sandbox_immediately(sandbox_fid, reason="migrated_to_cloud_vault")
        except Exception:
            pass
        record_portal_telemetry_event("public", "sandbox_migrated_to_cloud", feature_key=str(cloud_fid))
    return ok


def submit_async_fovault_restore_job(raw_bytes: bytes, target_fid: int = 0, is_cloud: bool = False) -> str:
    """Submits a non-blocking `.fovault` restore job to `background_jobs` (`SQLiteJobPool`) and returns `job_id`."""
    import background_jobs
    from services.sandbox_service import restore_sandbox_from_fovault_bytes

    if is_cloud:
        cloud_db = config.get_family_db_path(target_fid, "public")
        cloud_fek = security.get_request_vault_fek(target_fid)

        def _cloud_task() -> dict[str, Any]:
            if cloud_fek:
                security.stash_request_vault_fek(target_fid, cloud_fek)
            ok, err, active_fek = apply_fovault_restore_to_db(
                raw_bytes, cloud_db, target_fid, is_sandbox=False, is_local=False, universe="public"
            )
            if not ok:
                raise ValueError(err or "Cloud Vault restore failed.")
            summary = get_vault_import_summary(cloud_db, target_fid, raw_fek=active_fek)
            return {
                "success": True,
                "family_id": target_fid,
                "is_sandbox_restore": False,
                "redirect": "/",
                "summary": summary,
                "message": summary.get("summary_text", "Vault backup restored into your Cloud Vault."),
            }

        return background_jobs.submit_job(_cloud_task, family_id=target_fid, universe="public", job_type="vault_restore")

    def _sb_task() -> dict[str, Any]:
        new_fid, raw_fek, expires_at = restore_sandbox_from_fovault_bytes(raw_bytes, target_fid=target_fid)
        summary = get_vault_import_summary(config.get_family_db_path(new_fid, "sandbox"), new_fid, raw_fek=raw_fek)
        return {
            "success": True,
            "family_id": new_fid,
            "is_sandbox_restore": True,
            "raw_fek_b64": raw_fek.decode("utf-8") if isinstance(raw_fek, bytes) else str(raw_fek),
            "expires_at": expires_at,
            "redirect": "/?sandbox=1",
            "summary": summary,
            "message": summary.get("summary_text", "Vault backup restored successfully."),
        }

    return background_jobs.submit_job(_sb_task, family_id=target_fid, universe="sandbox", job_type="vault_restore")
