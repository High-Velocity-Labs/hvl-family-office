"""
Anonymous Workspace (sandbox) to Cloud Vault migration at Google sign-in: captures the resumable
sandbox lease before the OAuth session reset, then moves its data into the signed-in household.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from flask import g, has_request_context, request, session
from sqlalchemy.exc import SQLAlchemyError

import config

logger = logging.getLogger(__name__)


def capture_pending_sandbox_migration() -> Tuple[int, Optional[bytes], bool]:
    """Captures any active resumable Anonymous Workspace lease before OAuth session reset."""
    if config.is_local_mode() or not has_request_context():
        return 0, None, False
    wants_migrate = bool(
        session.pop("migrate_sandbox_to_cloud", False)
        or request.args.get("migrate_sandbox") == "1"
    )
    try:
        from routes.sandbox import get_resumable_sandbox_lease
        sb_fid, sb_fek, sb_lease = get_resumable_sandbox_lease()
        if sb_fid > 0 and sb_fek and (wants_migrate or (sb_lease and sb_lease.get("has_data"))):
            return sb_fid, sb_fek, wants_migrate
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Could not read the resumable sandbox lease; skipping sandbox migration: %s", exc)
    return 0, None, False


def apply_pending_sandbox_migration(
    sb_ctx: Tuple[int, Optional[bytes], bool],
    fid: int,
    raw_fek: Optional[bytes],
    user_row: Optional[Dict[str, Any]],
    db_path: Any,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Migrates an active Anonymous Workspace into the newly authenticated Cloud Vault when applicable."""
    sb_fid, sb_fek, wants_migrate = sb_ctx
    if sb_fid <= 0 or not sb_fek or not raw_fek or fid <= 0:
        return False, user_row
    try:
        from services.fovault_service import migrate_active_sandbox_to_cloud_vault
        migrated = migrate_active_sandbox_to_cloud_vault(
            sb_fid, sb_fek, fid, raw_fek, force_overwrite=wants_migrate
        )
        if not migrated:
            return False, user_row
        if has_request_context():
            g._clear_sandbox_cookie = True
        if user_row is not None and db_path.exists():
            from db.auth_repo import get_user_by_id
            refreshed = get_user_by_id(db_path, int(user_row["user_id"]))
            if refreshed is not None:
                user_row = refreshed
        return True, user_row
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Sandbox %s migration into household %s failed; the sandbox is kept: %s", sb_fid, fid, exc)
        return False, user_row
