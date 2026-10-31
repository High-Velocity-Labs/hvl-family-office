"""
Vault access lifecycle, server FEK escrow, and local passphrase vault management.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from db.security_repo import (
    check_local_passphrase_in_db,
    escrow_local_vault_key_in_db,
    fetch_local_login_record_from_dbs,
    update_local_passphrase_fek_in_dbs,
    upsert_first_local_household_in_db,
)
from db.vault import (
    check_local_vault_unclaimed_in_db,
    fetch_any_pending_user_fek,
    has_escrowed_family_key,
)
from db.vault_support_state import restore_support_access_state, snapshot_support_access_state
from db.vault_support_access import (
    adopt_peer_vault_sync_flags,
    disable_family_support_access_in_db,
    enable_family_support_access_in_db,
    sync_support_access_to_peers,
)


class SupportAccessWriteError(RuntimeError):
    """A support-access toggle could not be written to every database file; all of them were rolled back."""


def household_auth_peer_dbs(path_obj: Path, fid: int) -> list[Path]:
    """
    Returns the other DB (global.db <-> families/{fid}.db) beside `path_obj` that keeps a copy of this household's
    auth rows. Derived from the file's own location, never from a universe name: a DB outside a universe dir has
    no peer, so a write through it can never reach another directory's household.
    """
    if path_obj.parent.name == "families":
        cand = path_obj.parent.parent / "global.db"
    elif path_obj.name == "global.db":
        cand = path_obj.parent / "families" / f"{fid}.db"
    else:
        return []
    return [cand] if cand.exists() and cand.resolve() != path_obj.resolve() else []


def _enable_support_access(path_obj: Path, peers: list[Path], fid: int, fernet_kek: Any) -> None:
    """Escrows the household FEK under the root KEK in every file; the peers are written before the source."""
    import security

    if not security._is_authenticated_for_family(fid):
        if not has_escrowed_family_key(path_obj, fid):
            raise PermissionError(
                f"Cannot enable support access for household {fid} without an authenticated member session."
            )
    fam_key = security.get_family_key(path_obj, fid)
    enc_dek = fernet_kek.encrypt(fam_key).decode("utf-8")
    for target in (*peers, path_obj):
        enable_family_support_access_in_db(target, fid, enc_dek)
    security._FAMILY_KEY_CACHE[(str(path_obj), fid)] = fam_key


def _disable_support_access(path_obj: Path, peers: list[Path], fid: int, fernet_kek: Any) -> None:
    """Drops the server-side escrow in every file; the peers are written before the source."""
    import security

    fam_key_opt: Optional[bytes] = None
    try:
        fam_key_opt = security.get_family_key(path_obj, fid)
    except PermissionError:
        pending_fek_str = fetch_any_pending_user_fek(path_obj, fid)
        if pending_fek_str:
            try:
                fam_key_opt = fernet_kek.decrypt(pending_fek_str.encode("utf-8"))
            except Exception:
                fam_key_opt = None

    enc_dek_opt: Optional[str] = None
    encrypt_name_fn = None
    if fam_key_opt is not None:
        if security._is_authenticated_for_family(fid):
            security.stash_request_vault_fek(fid, fam_key_opt)
        enc_dek_opt = fernet_kek.encrypt(fam_key_opt).decode("utf-8")
        encrypt_name_fn = lambda plain: security.encrypt_string(plain, key=fam_key_opt)

    adopt_peer_vault_sync_flags(path_obj, fid, peers)
    for target in (*peers, path_obj):
        disable_family_support_access_in_db(target, fid, enc_dek_opt, encrypt_name_fn=encrypt_name_fn)

    for k in [k for k in security._FAMILY_KEY_CACHE if k[1] == fid]:
        security._FAMILY_KEY_CACHE.pop(k, None)


def set_family_support_access(db_path: Path, family_id: int, enabled: bool) -> bool:
    """Toggles support access flag and cryptographic server-side FEK escrow."""
    import security

    if not family_id or int(family_id) <= 0:
        return False

    fid = int(family_id)
    path_obj = Path(db_path)
    security.init_db(path_obj)
    root_kek = security.get_or_create_key()
    fernet_kek = security._get_fernet(root_kek)
    peers = household_auth_peer_dbs(path_obj, fid)
    for peer in peers:
        security.init_db(peer)

    # One unit of work over every file holding a copy of this household's auth rows: each step is idempotent and
    # any failure puts all files back, so a toggle is applied everywhere or nowhere (F-SEC-10).
    all_dbs = [path_obj, *peers]
    snapshots = [snapshot_support_access_state(p, fid) for p in all_dbs]
    try:
        if enabled:
            _enable_support_access(path_obj, peers, fid, fernet_kek)
        else:
            _disable_support_access(path_obj, peers, fid, fernet_kek)
        if peers:
            sync_support_access_to_peers(path_obj, fid, peers)
    except Exception as exc:
        for snap in snapshots:
            restore_support_access_state(snap, fid)
        security._FAMILY_KEY_CACHE.pop((str(path_obj), fid), None)
        if isinstance(exc, (PermissionError, ValueError)):
            raise  # caller errors keep their type (403/400); anything else is a failed write
        raise SupportAccessWriteError(str(exc)) from exc

    try:
        from db import store as _store
        from db.notifications import resolve_family_notification
        if not enabled:
            resolve_family_notification(path_obj, family_id=fid, dedupe_key="security:support_access_on")
        _store.notify_family_mutation(fid)
    except Exception:
        pass
    return True


def is_local_vault_unclaimed(db_path: Path) -> bool:
    """Returns True if the local installation is fresh and unclaimed."""
    import security

    target_db = Path(db_path)
    if not target_db.exists():
        return True
    try:
        security.init_db(target_db)
        return check_local_vault_unclaimed_in_db(target_db)
    except Exception:
        return True


def has_local_passphrase_configured(db_path: Path, family_id: int = 0) -> bool:
    """Returns True if Household has a PBKDF2-wrapped Master Passphrase/PIN configured."""
    target_db = Path(db_path)
    target_fid = int(family_id) if int(family_id) > 0 else _local_household_fid()
    cand_dbs = [p for p in (target_db, target_db.parent / "families" / f"{target_fid}.db") if p.exists()]
    return check_local_passphrase_in_db(cand_dbs, target_fid)


def provision_first_local_household(
    global_db: Path,
    family_db: Path,
    owner_name: str,
    household_name: str,
    owner_email: str = "",
    wrapped_passphrase_fek: Optional[str] = None,
) -> tuple[int, int, bytes]:
    """Initializes primary local household and owner across global.db and families/1.db."""
    import security

    from config import LOCAL_HOUSEHOLD_FAMILY_ID

    primary_fid = LOCAL_HOUSEHOLD_FAMILY_ID
    primary_uid = 1
    security.init_db(global_db)
    security.init_db(family_db)

    raw_fek = security.get_family_key(global_db, primary_fid)
    enc_hh_name = security.encrypt_string(household_name, key=raw_fek)
    enc_user_name = security.encrypt_string(owner_name, key=raw_fek)
    clean_email = owner_email.strip().lower()
    enc_email = security.encrypt_string(clean_email, key=raw_fek) if clean_email else ""
    em_hash = security.hash_email(clean_email) if clean_email else ""

    settings_dict: Dict[str, Any] = {
        "primary_state": "",
        "tax_filing_status": "MFJ",
        "onboarding_completed": False,
        "onboarding_dismissed": False,
    }
    if wrapped_passphrase_fek:
        settings_dict["local_passphrase_fek_enc"] = wrapped_passphrase_fek
    settings_json = json.dumps(settings_dict)

    enc_dek_fn = lambda: security._get_fernet(security.get_or_create_key()).encrypt(raw_fek).decode("utf-8")

    for db_target in (global_db, family_db):
        upsert_first_local_household_in_db(
            db_target,
            primary_fid,
            primary_uid,
            enc_hh_name,
            settings_json,
            enc_dek_fn,
            enc_user_name,
            enc_email,
            em_hash,
        )
        security._FAMILY_KEY_CACHE[(str(db_target), primary_fid)] = raw_fek

    return primary_fid, primary_uid, raw_fek


def _local_household_fid() -> int:
    """Returns the Local Desktop vault's single household id (`config.LOCAL_HOUSEHOLD_FAMILY_ID`)."""
    from config import LOCAL_HOUSEHOLD_FAMILY_ID

    return LOCAL_HOUSEHOLD_FAMILY_ID


def get_local_login_record(global_db: Path, family_id: int = 0) -> Dict[str, Any]:
    """Loads wrapped local passphrase FEK blob and primary user metadata."""
    primary_fid = int(family_id) if int(family_id) > 0 else _local_household_fid()
    cand_dbs = []
    if global_db.exists():
        cand_dbs.append(global_db)
    fam_db = global_db.parent / "families" / f"{primary_fid}.db"
    if fam_db.exists() and fam_db not in cand_dbs:
        cand_dbs.append(fam_db)

    return fetch_local_login_record_from_dbs(cand_dbs, primary_fid)


def update_local_passphrase_fek(
    global_db: Path,
    family_db: Path,
    wrapped_passphrase_fek: str,
    family_id: int = 0,
) -> None:
    """Updates settings['local_passphrase_fek_enc'] in both global_db and family_db."""
    primary_fid = int(family_id) if int(family_id) > 0 else _local_household_fid()
    update_local_passphrase_fek_in_dbs((global_db, family_db), primary_fid, wrapped_passphrase_fek)


def escrow_local_vault_key(
    global_db: Path,
    family_db: Path,
    raw_fek: bytes,
    family_id: int = 0,
) -> None:
    """Escrows local household encryption key (FEK) into families table."""
    import security

    fid = int(family_id) if int(family_id) > 0 else _local_household_fid()
    root_kek = security.get_or_create_key()
    enc_dek = security._get_fernet(root_kek).encrypt(raw_fek).decode("utf-8")
    for db_target in (global_db, family_db):
        if db_target.exists():
            escrow_local_vault_key_in_db(db_target, fid, enc_dek)
            security._FAMILY_KEY_CACHE[(str(db_target), fid)] = raw_fek
