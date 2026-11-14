"""
Household vault key (FEK) at sign-in: finds the Family Encryption Key across the browser cookie,
the user's Google Drive `appDataFolder`, the one-time `pending_fek_enc` handoff and the server escrow,
then escrows it back to Google Drive and marks the user's vault as synced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from cryptography.fernet import InvalidToken
from flask import g, has_request_context, session

import config
from hvl_common.auth import write_google_appdata_json
from hvl_common.security import is_valid_candidate_fek


def _extract_appdata_fek(appdata: Optional[Dict[str, Any]], family_id: int) -> Optional[bytes]:
    """Extracts and validates a Fernet FEK for `family_id` from a Google appDataFolder JSON dict."""
    if not isinstance(appdata, dict):
        return None
    import security

    candidate: Optional[str] = None
    fek_map = appdata.get("fek_map")
    if isinstance(fek_map, dict) and str(family_id) in fek_map:
        candidate = str(fek_map[str(family_id)] or "").strip()
    elif appdata.get("fek"):
        stored_fid = appdata.get("family_id")
        if stored_fid is None or int(stored_fid or 0) == int(family_id):
            candidate = str(appdata["fek"]).strip()

    if not candidate:
        return None
    try:
        raw_bytes = candidate.encode("utf-8")
        security._get_fernet(raw_bytes)
        return raw_bytes
    except ValueError:
        return None


def _is_valid_candidate_fek(
    candidate_fek: Optional[bytes],
    user_row: Optional[Dict[str, Any]],
    clean_email: str,
) -> bool:
    """Verifies that a candidate FEK from cookie/session can decrypt the user's encrypted email record."""
    if not candidate_fek:
        return False
    enc_email = str(user_row.get("email") or "") if user_row is not None else ""
    return is_valid_candidate_fek(
        candidate_fek,
        [enc_email] if enc_email else (),
        expected_email=clean_email if enc_email.startswith("gAAAAA") else None,
    )


def _resolve_appdata_fek(
    read_fn: Callable[..., Any],
    access_token: str,
    fid: int,
    user_row: Optional[Dict[str, Any]],
    clean_email: str,
) -> Optional[bytes]:
    """Reads and validates a household FEK from the user's Google Drive appDataFolder."""
    appdata_fname = config.get_vault_appdata_filename()
    appdata = read_fn(str(access_token), filename=appdata_fname)
    cand_appdata_fek = _extract_appdata_fek(appdata, fid)
    if not _is_valid_candidate_fek(cand_appdata_fek, user_row, clean_email) and appdata_fname != "hvl_vault_key.json":
        appdata = read_fn(str(access_token), filename="hvl_vault_key.json")
        cand_appdata_fek = _extract_appdata_fek(appdata, fid)
    if _is_valid_candidate_fek(cand_appdata_fek, user_row, clean_email):
        return cand_appdata_fek
    return None


def resolve_household_vault_fek(
    db_path: Any,
    fid: int,
    user_row: Optional[Dict[str, Any]],
    clean_email: str,
    access_token: Optional[str],
    already_synced: bool,
    read_appdata_fn: Callable[..., Any],
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    """
    Resolves the Family Encryption Key (FEK) across browser cookie, Google Drive appDataFolder,
    one-time `pending_fek_enc`, and server-escrowed `families.encryption_key_enc`.
    Returns `(raw_fek, fek_source, error_message)`.
    """
    import security

    raw_fek: Optional[bytes] = None
    fek_source: Optional[str] = None
    locked_err = "Household vault is cryptographically locked and no key was found in your Google Drive appDataFolder or device cookie."

    if already_synced:
        cand_fek = security.get_request_vault_fek(fid)
        if _is_valid_candidate_fek(cand_fek, user_row, clean_email):
            raw_fek = cand_fek
            fek_source = "cookie"
        else:
            session.pop("vault_fek", None)
            if has_request_context() and hasattr(g, "_active_vault_feks"):
                getattr(g, "_active_vault_feks", {}).pop(fid, None)

        vault_locked = False
        if raw_fek is None and db_path.exists():
            try:
                raw_fek = security.get_family_key(db_path, fid)
                if raw_fek is not None:
                    fek_source = "family_table"
            except PermissionError:
                vault_locked = True

        if raw_fek is None and access_token:
            raw_fek = _resolve_appdata_fek(read_appdata_fn, str(access_token), fid, user_row, clean_email)
            if raw_fek is not None:
                fek_source = "appdata"

        if raw_fek is None and vault_locked and user_row is not None:
            return None, None, locked_err
        return raw_fek, fek_source, None

    if access_token:
        raw_fek = _resolve_appdata_fek(read_appdata_fn, str(access_token), fid, user_row, clean_email)
        if raw_fek is not None:
            fek_source = "appdata"

    if raw_fek is None:
        cand_fek = security.get_request_vault_fek(fid)
        if _is_valid_candidate_fek(cand_fek, user_row, clean_email):
            raw_fek = cand_fek
            fek_source = "cookie"
        else:
            session.pop("vault_fek", None)
            if has_request_context() and hasattr(g, "_active_vault_feks"):
                getattr(g, "_active_vault_feks", {}).pop(fid, None)

    if raw_fek is None and user_row is not None and user_row.get("pending_fek_enc"):
        try:
            raw_fek = security._get_fernet(security.get_or_create_key()).decrypt(
                str(user_row["pending_fek_enc"]).encode("utf-8")
            )
            fek_source = "pending"
        except (InvalidToken, ValueError):
            raw_fek = None

    if raw_fek is None and db_path.exists():
        try:
            raw_fek = security.get_family_key(db_path, fid)
            fek_source = "family_table"
        except PermissionError:
            if user_row is not None:
                return None, None, locked_err

    return raw_fek, fek_source, None


def _sync_fek_to_google_and_db(
    access_token: Optional[str],
    fid: int,
    uid: Optional[int],
    raw_fek: bytes,
    fek_source: Optional[str],
    needs_google_write: bool,
    db_path: Path,
    family_db_path: Optional[Path] = None,
) -> bool:
    """Syncs the resolved FEK to Google Drive appDataFolder (when needed) and marks the user vault as synced in SQLite."""
    import security

    synced_to_google = False
    if access_token:
        if needs_google_write:
            synced_to_google = bool(
                write_google_appdata_json(
                    str(access_token),
                    {"family_id": fid, "fek": raw_fek.decode("utf-8")},
                    filename=config.get_vault_appdata_filename(),
                )
            )
        else:
            synced_to_google = True

    if uid is not None and (synced_to_google or fek_source == "pending"):
        target_paths = [Path(db_path)]
        if family_db_path is not None and Path(family_db_path) != Path(db_path) and Path(family_db_path).exists():
            target_paths.append(Path(family_db_path))
        from db.auth_repo import clear_pending_vault_and_sync
        clear_pending_vault_and_sync(target_paths, uid, fid)
        for k in [k for k in list(security._FAMILY_KEY_CACHE) if k[1] == fid]:
            security._FAMILY_KEY_CACHE.pop(k, None)

    return synced_to_google


def escrow_resolved_fek(
    access_token: Optional[str],
    fid: int,
    uid: Optional[int],
    raw_fek: bytes,
    fek_source: Optional[str],
    already_synced: bool,
    db_path: Any,
) -> None:
    """
    Escrows a freshly resolved FEK to the user's Google Drive and clears its server-side handoff copies.
    `uid` is None when the sign-in matched no users row (whitelist-only member): nothing to mark synced.
    The Drive write runs in the background unless jobs run synchronously (tests, local desktop).
    """
    import security
    from services import background_jobs

    needs_google_write = bool(access_token and fek_source != "appdata" and not already_synced)
    needs_db_sync = bool(uid is not None and not already_synced and (access_token or fek_source == "pending"))
    if not (needs_google_write or needs_db_sync):
        return

    resolved_db_path = Path(db_path)
    # The per-family DB holds its own copy of users/families; clearing escrow only in
    # global.db would leave the household server-decryptable through families/{fid}.db.
    peer_dbs = security.household_auth_peer_dbs(resolved_db_path, fid)
    family_db_path = peer_dbs[0] if peer_dbs else None
    if needs_google_write and not background_jobs.should_run_synchronously():
        background_jobs.EXECUTOR.submit(
            _sync_fek_to_google_and_db, access_token, fid, uid, raw_fek, fek_source,
            needs_google_write, resolved_db_path, family_db_path,
        )
    else:
        _sync_fek_to_google_and_db(
            access_token, fid, uid, raw_fek, fek_source, needs_google_write, resolved_db_path, family_db_path,
        )
