"""
Family metadata CRUD, universe resolution, and invited household provisioning.
"""

from __future__ import annotations

import logging
from pathlib import Path
from db.security_repo import DatabaseError
from typing import Optional

from cryptography.fernet import InvalidToken
from sqlalchemy.exc import SQLAlchemyError

from db.security_repo import (
    fetch_family_metadata_fallback,
    fetch_pending_fek_from_db,
    sync_user_row_between_dbs,
    upsert_invited_household_metadata,
)

logger = logging.getLogger(__name__)


def _resolve_universe_from_db_path(db_path: Path, universe: Optional[str] = None) -> str:
    """Resolves universe string from database path."""
    from config import normalize_universe
    if universe:
        return normalize_universe(universe)
    parts = [pt.lower() for pt in Path(db_path).parts]
    for u in ("demo", "sandbox", "test", "public"):
        if u in parts:
            return u
    p_name = Path(db_path).name.lower()
    if "_beta" in p_name or "_demo" in p_name or "families_beta" in parts:
        return "demo"
    if "_sandbox" in p_name or "families_sandbox" in parts:
        return "sandbox"
    if "_test" in p_name or "families_test" in parts:
        return "test"
    from services.request_context import get_current_universe
    return normalize_universe(get_current_universe())


def _candidate_family_metadata_dbs(db_path: Path, family_id: int, universe: Optional[str] = None) -> list[Path]:
    """Returns candidate database paths where family metadata may reside."""
    from config import get_family_db_path, get_global_db_path
    from db.session import resolve_db_path

    fid = int(family_id or 0)
    uni = _resolve_universe_from_db_path(db_path, universe=universe)
    resolved = resolve_db_path(db_path, family_id=fid)
    fam_db = get_family_db_path(fid, universe=uni) if fid > 0 else resolved
    candidates: list[Path] = []
    for p in (resolved, fam_db, get_global_db_path(universe=uni), Path(db_path)):
        try:
            rp = Path(p)
            if rp not in candidates and not any(
                rp.resolve() == c.resolve() for c in candidates if c.exists() and rp.exists()
            ):
                candidates.append(rp)
        except OSError:  # resolve() on an unreadable path: keep the candidate unresolved
            if Path(p) not in candidates:
                candidates.append(Path(p))
    return candidates


def get_family(db_path: Path, family_id: int) -> Optional[dict]:
    """Retrieves family group metadata (settings: `db.family_settings`), strictly scoped by family_id."""
    from db.models import Family
    from db.session import get_orm_session
    import security

    security.init_db(db_path)
    try:
        with get_orm_session(db_path, family_id=family_id) as session:
            fam = session.get(Family, family_id)
            if not fam:
                return None
            quarantine = (fam.deletion_scheduled_at, fam.deletion_purge_after, fam.deletion_requested_by)
            return {
                "family_id": fam.family_id,
                "name": fam.name or "Family Office",
                "deletion_status": security._parse_deletion_status(quarantine),
                "support_access_enabled": bool(fam.support_access_enabled),
                "created_at": fam.created_at,
            }
    except PermissionError:
        row = fetch_family_metadata_fallback(db_path, int(family_id))
        if not row:
            return None
        return {
            "family_id": int(row[0]),
            "name": "Family Office",
            "deletion_status": security._parse_deletion_status(row[3]),
            "support_access_enabled": bool(int(row[1] or 0)),
            "created_at": row[2],
        }


def update_family(
    db_path: Path,
    family_id: int,
    name: str = "",
    support_access_enabled: Optional[bool] = None,
) -> bool:
    """Updates family name and the optional support_access_enabled flag."""
    from db.models import Family
    from db.session import get_orm_session
    import security

    if name:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            fam = session.get(Family, family_id)
            if fam is not None:
                fam.name = name
                if support_access_enabled is not None and bool(support_access_enabled):
                    fam.support_access_enabled = 1
    if support_access_enabled is not None:
        security.set_family_support_access(db_path, family_id=int(family_id), enabled=bool(support_access_enabled))
    return True


def _provision_invited_household(
    db_path: Path,
    new_fid: int,
    clean_name: str,
    clean_email: str,
    uni: str,
    state: str = "",
) -> int:
    """Provisions a new household database, key, profile, and primary member ("" state = onboarding asks)."""
    from db.session import resolve_db_path
    import security

    target_fam_db = resolve_db_path(db_path, family_id=new_fid)
    security.init_db(target_fam_db)
    fam_key = security.get_family_key(target_fam_db, new_fid)
    security.stash_request_vault_fek(new_fid, fam_key)
    enc_dek = security._get_fernet(security.get_or_create_key()).encrypt(fam_key).decode("utf-8")

    household_name = f"{clean_name}'s Family Office"
    enc_household_name = security.encrypt_string(household_name, key=fam_key)
    for dest_db in _candidate_family_metadata_dbs(Path(db_path), new_fid, universe=uni):
        security.init_db(dest_db)
        upsert_invited_household_metadata(dest_db, new_fid, enc_household_name, enc_dek, state=state)

    uid = security.add_family_member(
        target_fam_db,
        family_id=new_fid,
        name=clean_name,
        email=clean_email,
        relationship="primary",
        role="editor",
    )
    for dest_db in _candidate_family_metadata_dbs(Path(db_path), new_fid, universe=uni):
        if dest_db.exists() and dest_db.resolve() != target_fam_db.resolve():
            sync_user_row_between_dbs(target_fam_db, dest_db, uid, mode="timestamps")
    return uid


class VaultLockedError(PermissionError):
    """Raised when an invited household's vault is locked (Support Access OFF); the message is safe to show users."""


HOUSEHOLD_VAULT_LOCKED_INVITE_MESSAGE = (
    "This household's vault is currently cryptographically locked (Support Access = OFF). "
    "Please ask the household owner to toggle Allow Support Access ON in Settings \u2192 Household & Access, "
    "then try your invite again."
)


def _join_invited_household(
    db_path: Path,
    target_fid: int,
    clean_name: str,
    clean_email: str,
    target_role: str,
    uni: str,
) -> tuple[int, str]:
    """Adds an invited user to an existing household."""
    from db.session import resolve_db_path
    import security

    assigned_role = "editor" if str(target_role or "").strip().lower() == "editor" else "viewer"
    rel = "spouse" if assigned_role == "editor" else "relative"
    target_fam_db = resolve_db_path(db_path, family_id=target_fid)
    security.init_db(target_fam_db)

    try:
        fam_key = security.get_family_key(target_fam_db, target_fid)
        security.stash_request_vault_fek(target_fid, fam_key)
    except PermissionError:
        for cand in _candidate_family_metadata_dbs(Path(db_path), target_fid, universe=uni):
            if not cand.exists():
                continue
            try:
                pending_fek = fetch_pending_fek_from_db(cand, target_fid)
                if pending_fek:
                    dek = security._get_fernet(security.get_or_create_key()).decrypt(pending_fek.encode("utf-8"))
                    security.stash_request_vault_fek(target_fid, dek)
                    break
            except (DatabaseError, InvalidToken) as exc:
                logger.warning("Pending FEK of household %s not usable from %s: %s", target_fid, cand, exc)
                continue
        else:
            raise VaultLockedError(HOUSEHOLD_VAULT_LOCKED_INVITE_MESSAGE)

    existing = security.find_user_by_email(target_fam_db, clean_email, family_id=target_fid)
    if existing:
        return int(existing["user_id"]), assigned_role

    uid = security.add_family_member(
        target_fam_db,
        family_id=target_fid,
        name=clean_name,
        email=clean_email,
        relationship=rel,
        role=assigned_role,
    )
    try:
        from db.notifications import emit_family_notification
        emit_family_notification(
            target_fam_db, family_id=target_fid, category="invite",
            dedupe_key=f"invite:accepted:user:{uid}", deep_link="/?settings=members",
            title="New household member joined",
            body=f"{clean_name or clean_email} accepted your household invite ({assigned_role}).",
            sender_email=clean_email, sender_name=clean_name,
        )
    except (DatabaseError, SQLAlchemyError, PermissionError) as exc:
        logger.warning("Invite-accepted notification for household %s not recorded: %s", target_fid, exc)
    for dest_db in _candidate_family_metadata_dbs(Path(db_path), target_fid, universe=uni):
        if dest_db.exists() and dest_db.resolve() != target_fam_db.resolve():
            try:
                sync_user_row_between_dbs(target_fam_db, dest_db, uid, mode="permissions")
            except DatabaseError as exc:
                logger.warning("User %s not mirrored into %s: %s", uid, dest_db, exc)
                continue

    return uid, assigned_role
