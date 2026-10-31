"""
Per-family envelope encryption key resolution, rotation, schema migrations, and encrypted SQLite store.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from cryptography.fernet import Fernet, MultiFernet

from security.crypto import (
    _DB_INIT_CACHE,
    _FAMILY_KEY_CACHE,
    _clear_security_caches,
    _get_fernet,
    _is_authenticated_for_family,
    _parse_fernet_keys,
    decrypt_data,
    encrypt_data,
    get_or_create_key,
    get_request_vault_fek,
    stash_request_vault_fek,
)

logger = logging.getLogger(__name__)


def _is_household_vault_initialized(conn: Any, family_id: int, fam_name: Any) -> bool:
    """Checks whether a household has already initialized encrypted records or user vault state."""
    return check_household_vault_initialized(conn, family_id, fam_name)


def _is_initial_vault_setup(conn: Any, family_id: int) -> bool:
    """Returns True if the household has not completed Google Drive vault sync (`google_vault_synced == 0` for all members)."""
    return check_initial_vault_setup(conn, family_id)


def _is_non_public_db_path(db_file: str) -> bool:
    """Returns True if the database path belongs to a demo or sandbox universe directory."""
    if not db_file:
        return False
    parts = {pt.lower() for pt in Path(db_file).parts}
    return bool(parts.intersection({"demo", "sandbox", "families_beta", "families_sandbox"}))


def _is_demo_db_path(db_file: str) -> bool:
    """Returns True if the database path belongs to a read-only demo universe directory."""
    if not db_file:
        return False
    parts = {pt.lower() for pt in Path(db_file).parts}
    return bool(parts.intersection({"demo", "families_beta"}))


def _is_sandbox_db_path(db_file: str) -> bool:
    """Returns True if the database path belongs to an ephemeral sandbox universe directory."""
    if not db_file:
        return False
    parts = {pt.lower() for pt in Path(db_file).parts}
    return bool(parts.intersection({"sandbox", "families_sandbox"}))


def _is_public_db_path(db_file: str) -> bool:
    """Returns True if the database path explicitly belongs to the public universe directory."""
    if not db_file:
        return False
    parts = {pt.lower() for pt in Path(db_file).parts}
    return "public" in parts


def run_alembic_migrations(db_path: Path) -> None:
    """Runs Alembic schema migrations up to head for the specified SQLite database (under the migration file lock)."""
    from db.schema_migrations import upgrade_to_head

    upgrade_to_head(Path(db_path))


def init_db(db_path: Path) -> None:
    """Initializes the multi-tenant SQLite schema via migrations and ensures default records."""
    path_obj = Path(db_path)
    p_str = str(path_obj)
    if p_str in _DB_INIT_CACHE and path_obj.exists():
        return

    for k in [k for k in _FAMILY_KEY_CACHE if k[0] == p_str]:
        _FAMILY_KEY_CACHE.pop(k, None)

    path_obj.parent.mkdir(parents=True, exist_ok=True)
    from db.schema_migrations import upgrade_to_head

    upgrade_to_head(path_obj)

    _DB_INIT_CACHE.add(p_str)

    try:
        from db import data_migration
        data_migration.migrate_encrypted_store_to_relational(path_obj)
    except Exception:
        pass


def validate_vault_snapshot_file(tmp_path: Union[str, Path]) -> Tuple[bool, str]:
    """Validates that an uploaded .fovault SQLite snapshot passes integrity check and contains families table."""
    return validate_vault_snapshot_sqlite(tmp_path)


def _resolve_pending_user_fek(
    conn: Any,
    fid: int,
    root_kek: bytes,
    cache_key: Optional[Tuple[str, int]],
    support_enabled: bool,
    is_local: bool,
    enc_key_str: str,
) -> Optional[bytes]:
    """Resolves a pending user FEK from users.pending_fek_enc when authenticated for the family."""
    try:
        from flask import session
        uid = session.get("user_id")
        pending_enc = fetch_pending_user_fek_enc(conn, fid, int(uid) if uid else None)
        if pending_enc:
            dek = _get_fernet(root_kek).decrypt(pending_enc.encode("utf-8"))
            stash_request_vault_fek(fid, dek)
            if (support_enabled or is_local) and cache_key is not None:
                _FAMILY_KEY_CACHE[cache_key] = dek
            if is_local and (not enc_key_str or not support_enabled):
                enc_dek = _get_fernet(root_kek).encrypt(dek).decode("utf-8")
                update_family_escrowed_fek(conn, fid, enc_dek, support_enabled=1)
            return dek
    except Exception:
        pass
    return None


def _resolve_family_key_on_conn(
    conn: Any, family_id: int, root_kek: bytes, cache_key: Optional[Tuple[str, int]] = None
) -> bytes:
    """Resolves or generates the family FEK using an active database connection."""
    fid = int(family_id)
    db_file = cache_key[0] if cache_key else ""
    is_non_public = _is_non_public_db_path(db_file)
    if _is_demo_db_path(db_file):
        req_fek = None
    elif _is_sandbox_db_path(db_file):
        req_fek = get_request_vault_fek(fid, allow_sandbox=True, require_sandbox=True)
    elif _is_public_db_path(db_file):
        req_fek = get_request_vault_fek(fid, allow_sandbox=False)
    else:
        req_fek = get_request_vault_fek(fid, allow_sandbox=True)

    row = fetch_family_key_row(conn, fid)
    enc_key_str = str(row[0]) if row and row[0] else ""
    support_enabled = bool(int(row[1] or 0)) if row else False
    fam_name = row[2] if row else ""

    import config
    is_local = config.is_local_mode()

    if req_fek is not None:
        if (support_enabled or is_local) and cache_key is not None:
            _FAMILY_KEY_CACHE[cache_key] = req_fek
        elif cache_key is not None:
            _FAMILY_KEY_CACHE.pop(cache_key, None)

        if is_local:
            enc_dek = _get_fernet(root_kek).encrypt(req_fek).decode("utf-8")
            update_family_escrowed_fek(conn, fid, enc_dek, support_enabled=1)
        return req_fek

    if not is_non_public and _is_authenticated_for_family(fid):
        pending_dek = _resolve_pending_user_fek(
            conn, fid, root_kek, cache_key, support_enabled, is_local, enc_key_str
        )
        if pending_dek is not None:
            return pending_dek

    if row and enc_key_str and (support_enabled or is_local or is_non_public or _is_initial_vault_setup(conn, fid)):
        dek = _get_fernet(root_kek).decrypt(enc_key_str.encode("utf-8"))
        if not is_non_public and _is_authenticated_for_family(fid):
            stash_request_vault_fek(fid, dek)
        if cache_key is not None and (support_enabled or is_local or is_non_public):
            _FAMILY_KEY_CACHE[cache_key] = dek
        return dek

    if row and not support_enabled and _is_household_vault_initialized(conn, fid, fam_name):
        raise PermissionError(
            f"Household {fid} local vault is locked. Please enter your Master Passphrase or PIN to unlock."
            if is_local
            else f"Household {fid} vault is cryptographically locked (support_access_enabled=0 and FEK is not escrowed on server)."
        )

    new_dek = Fernet.generate_key()
    enc_dek = _get_fernet(root_kek).encrypt(new_dek).decode("utf-8")
    # A new key keeps the household's own support-access choice (e.g. a seeded demo persona's 1); only a household with
    # no row yet starts locked in cloud mode. Local vaults are always escrowed.
    upsert_family_key_row(conn, fid, enc_dek, 1 if (is_local or support_enabled) else 0)
    if not is_non_public and _is_authenticated_for_family(fid):
        stash_request_vault_fek(fid, new_dek)
    if cache_key is not None:
        _FAMILY_KEY_CACHE[cache_key] = new_dek
    return new_dek


def _cached_fek_still_valid(support_flag: Optional[bool], db_file: str) -> bool:
    """
    A cached FEK stays usable while its household row exists and, for public households,
    support access is still on: another worker may have locked the vault since it was cached.
    """
    if support_flag is None:
        return False
    import config
    return support_flag or config.is_local_mode() or _is_non_public_db_path(db_file)


_REKEY_ATTEMPTED: set[Tuple[str, int]] = set()


def _ensure_root_kek_rows_rekeyed(db_path: Any, family_id: int, fam_key: bytes) -> None:
    """
    F-SEC-11: the first time this process resolves a household's FEK for a database file, any ciphertext in it
    that is still under the root KEK is rewritten under the FEK (`db.vault_rekey`), so every later read opens
    with the household key alone. A household whose `families.settings` already records a pass is skipped.
    A failed pass is logged and retried on the next process start; the rows stay recoverable until then.
    """
    cache_key = (str(db_path), int(family_id))
    if cache_key in _REKEY_ATTEMPTED:
        return
    _REKEY_ATTEMPTED.add(cache_key)
    try:
        root_ring = _get_fernet(get_or_create_key())
        if fam_key in _parse_fernet_keys(get_or_create_key()):
            return
        from db.vault_rekey import is_rekeyed, rekey_household_db

        if isinstance(db_path, (str, Path)):
            path = Path(db_path)
        else:
            from db.session import resolve_db_path

            path = Path(resolve_db_path(db_path, family_id=int(family_id)))
        # Only the file whose own `families` row produced `fam_key`. Its peer (global.db <-> families/{fid}.db) can hold
        # a different valid FEK for the same household, so rewriting it under this one would make its rows unreadable;
        # the peer is rekeyed under its own key when it is resolved itself.
        if path.exists() and not is_rekeyed(path, family_id):
            rekey_household_db(path, family_id, _get_fernet(fam_key), root_ring)
    except Exception as exc:
        logger.warning("Root-KEK re-encryption pass failed for %s (household %s): %s", db_path, family_id, exc)


def get_family_key(db_path: Any, family_id: int) -> bytes:
    """
    Retrieves or derives the dedicated Data Encryption Key (DEK) for a family and, once per process and database,
    re-encrypts any legacy root-KEK ciphertext under it (`_ensure_root_kek_rows_rekeyed`).
    Accepts either a database Path/str or an active sqlite3.Connection / _PooledConnection.
    """
    fam_key = _resolve_family_key(db_path, family_id)
    if not is_sqlite_connection(db_path):
        _ensure_root_kek_rows_rekeyed(db_path, family_id, fam_key)
    return fam_key


def _resolve_family_key(db_path: Any, family_id: int) -> bytes:
    if not family_id or int(family_id) <= 0:
        raise ValueError("A household id (> 0) is required to resolve a household key; the server root key is never a fallback.")

    fid = int(family_id)
    import config
    is_local = config.is_local_mode()
    root_kek = get_or_create_key()

    if is_sqlite_connection(db_path):
        return resolve_family_key_on_sqlite_conn(
            db_path, fid, root_kek, _FAMILY_KEY_CACHE, _resolve_family_key_on_conn, _cached_fek_still_valid
        )

    try:
        from db.session import resolve_db_path
        db_path = resolve_db_path(db_path, family_id=fid)
    except Exception:
        pass

    db_str = str(db_path)
    cache_key = (db_str, fid)
    cached = _FAMILY_KEY_CACHE.get(cache_key)
    if cached is not None:
        if _cached_fek_still_valid(read_family_support_flag_at_path(db_path, fid), db_str):
            return cached
        _FAMILY_KEY_CACHE.pop(cache_key, None)

    if is_local:
        for (k_path, k_fid), k_fek in list(_FAMILY_KEY_CACHE.items()):
            if k_fid == fid and k_fek and not _is_non_public_db_path(k_path):
                return k_fek

    init_db(Path(db_path))
    return resolve_family_key_on_db_path(
        db_path, fid, root_kek, cache_key, _resolve_family_key_on_conn
    )


def rotate_family_keys(
    db_path: Path,
    new_kek: Optional[Union[bytes, str]] = None,
    old_keks: Optional[List[Union[bytes, str]]] = None,
) -> Dict[str, Any]:
    """Re-encrypts every family's Data Encryption Key under the new primary KEK."""
    path_obj = Path(db_path)
    init_db(path_obj)

    ordered_keys: List[bytes] = []
    if new_kek is not None:
        for k in _parse_fernet_keys(new_kek):
            if k not in ordered_keys:
                ordered_keys.append(k)
        if old_keks is not None:
            for raw_old in old_keks:
                for k in _parse_fernet_keys(raw_old):
                    if k not in ordered_keys:
                        ordered_keys.append(k)
        else:
            for k in _parse_fernet_keys(get_or_create_key()):
                if k not in ordered_keys:
                    ordered_keys.append(k)
    else:
        for k in _parse_fernet_keys(get_or_create_key()):
            if k not in ordered_keys:
                ordered_keys.append(k)

    if not ordered_keys:
        raise ValueError("At least one valid Fernet key is required for key rotation")

    multi = MultiFernet([Fernet(k) for k in ordered_keys])
    rotated_family_ids = rotate_family_keys_in_db(path_obj, multi)
    _clear_security_caches()

    return {
        "rotated_count": len(rotated_family_ids),
        "family_ids": rotated_family_ids,
    }


def db_save_encrypted(db_path: Path, key: str, category: str, data: Any, family_id: int = 0) -> None:
    """Saves arbitrary data encrypted at rest in SQLite, strictly scoped by family_id."""
    from db import data_migration
    if not family_id:
        if key in data_migration.MIGRATED_STORE_KEYS:
            raise ValueError(f"Cannot save {key!r} without a family_id")
        return
    try:
        from db.session import resolve_db_path
        path_obj = resolve_db_path(db_path, family_id=family_id)
    except Exception:
        path_obj = Path(db_path)
    init_db(path_obj)
    if key in data_migration.MIGRATED_STORE_KEYS:
        # Migrated keys live only in relational tables (reads go there first); a failure
        # propagates instead of falling back to a legacy blob that reads would ignore.
        data_migration.try_relational_save(path_obj, key, data, family_id)
        _notify_encrypted_key_mutation(family_id, key, category, path_obj)
        return

    fam_key = get_family_key(path_obj, family_id)
    ciphertext = encrypt_data(data, key=fam_key)
    upsert_encrypted_store_payload(path_obj, family_id, key, category, ciphertext)
    _notify_encrypted_key_mutation(family_id, key, category, path_obj)


def _notify_encrypted_key_mutation(family_id: int, key: str, category: str, path_obj: Path) -> None:
    try:
        from db import store as _store
        from forecast.cache import resolve_domains_for_encrypted_key
        _store.notify_family_mutation(family_id, domains=resolve_domains_for_encrypted_key(key, category), db_path=path_obj)
    except Exception:
        pass


def db_load_encrypted(db_path: Path, key: str, family_id: int = 0) -> Any | None:
    """Loads and decrypts a record from the encrypted SQLite store, strictly scoped by family_id."""
    if not family_id:
        return None
    try:
        from db.session import resolve_db_path
        path_obj = resolve_db_path(db_path, family_id=family_id)
    except Exception:
        path_obj = Path(db_path)
    if not path_obj.exists():
        return None
    init_db(path_obj)
    from db import data_migration
    handled, val = data_migration.try_relational_load(path_obj, key, family_id)
    if handled:
        return val

    fam_key = get_family_key(path_obj, family_id)
    ciphertext = fetch_encrypted_store_payload(path_obj, family_id, key)
    if ciphertext:
        return decrypt_data(ciphertext, key=fam_key)
    return None


from db.vault_support_access import read_family_support_flag_at_path  # noqa: E402
from db.vault import (  # noqa: E402
    check_household_vault_initialized,
    check_initial_vault_setup,
    fetch_encrypted_store_payload,
    fetch_family_key_row,
    fetch_pending_user_fek_enc,
    insert_default_family_row,
    is_alembic_at_head,
    is_sqlite_connection,
    resolve_family_key_on_db_path,
    resolve_family_key_on_sqlite_conn,
    rotate_family_keys_in_db,
    update_family_escrowed_fek,
    upsert_encrypted_store_payload,
    upsert_family_key_row,
    validate_vault_snapshot_sqlite,
)

