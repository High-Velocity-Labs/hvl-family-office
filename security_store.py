"""
Per-family envelope encryption key resolution, rotation, schema migrations, and encrypted SQLite store.
"""

from __future__ import annotations
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union
from cryptography.fernet import Fernet, MultiFernet
from hvl_common.db import get_db_connection

from security_crypto import (
    ALEMBIC_DIR,
    ALEMBIC_HEAD_REVISION,
    ALEMBIC_INI_PATH,
    MIGRATIONS_DIR,
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
from security_store_helpers import (
    _is_household_vault_initialized,
    _is_initial_vault_setup,
    _is_non_public_db_path,
    _is_demo_db_path,
    _is_sandbox_db_path,
    _is_public_db_path,
    _resolve_pending_user_fek,
    run_alembic_migrations,
    init_db,
    validate_vault_snapshot_file,
)


def _resolve_family_key_on_conn(
    conn: Any, family_id: int, root_kek: bytes, cache_key: Optional[Tuple[str, int]] = None
) -> bytes:
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
    row = conn.execute(
        "SELECT encryption_key_enc, support_access_enabled, name FROM families WHERE family_id = ?",
        (fid,),
    ).fetchone()
    enc_key_str = str(row[0]) if row and row[0] else ""
    support_enabled = bool(int(row[1] or 0)) if row and len(row) > 1 else False
    fam_name = row[2] if row and len(row) > 2 else ""

    import config
    is_local = config.is_local_mode()

    if req_fek is not None:
        if row is None:
            was_in_tx = conn.in_transaction
            conn.execute(
                "INSERT INTO families (family_id, name, encryption_key_enc, support_access_enabled) VALUES (?, ?, NULL, 0) ON CONFLICT(family_id) DO NOTHING",
                (fid, f"Family {fid}"),
            )
            if not was_in_tx:
                conn.commit()
        if (support_enabled or is_local) and cache_key is not None:
            _FAMILY_KEY_CACHE[cache_key] = req_fek
        elif cache_key is not None:
            _FAMILY_KEY_CACHE.pop(cache_key, None)

        if is_local:
            enc_dek = _get_fernet(root_kek).encrypt(req_fek).decode("utf-8")
            was_in_tx = conn.in_transaction
            conn.execute(
                "UPDATE families SET encryption_key_enc = ?, support_access_enabled = 1 WHERE family_id = ?",
                (enc_dek, fid),
            )
            if not was_in_tx:
                conn.commit()
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
    was_in_tx = conn.in_transaction
    conn.execute(
        "INSERT INTO families (family_id, name, encryption_key_enc, support_access_enabled) VALUES (?, ?, ?, ?) ON CONFLICT(family_id) DO UPDATE SET encryption_key_enc = excluded.encryption_key_enc, support_access_enabled = excluded.support_access_enabled",
        (fid, f"Family {fid}", enc_dek, 1 if is_local else 0),
    )
    if not was_in_tx:
        conn.commit()
    if not is_non_public and _is_authenticated_for_family(fid):
        stash_request_vault_fek(fid, new_dek)
    if cache_key is not None:
        _FAMILY_KEY_CACHE[cache_key] = new_dek
    return new_dek


def get_family_key(db_path: Any, family_id: int) -> bytes:
    """
    Retrieves or derives the dedicated Data Encryption Key (DEK) for a family.
    Accepts either a database Path/str or an active sqlite3.Connection / _PooledConnection.
    """
    if not family_id or int(family_id) <= 0:
        return get_or_create_key()

    fid = int(family_id)
    import config
    is_local = config.is_local_mode()
    root_kek = get_or_create_key()

    if isinstance(db_path, sqlite3.Connection) or hasattr(db_path, "raw_connection"):
        try:
            db_list = db_path.execute("PRAGMA database_list").fetchone()
            db_file = str(db_list[2]) if db_list and len(db_list) > 2 and db_list[2] else ""
            c_key = (db_file, fid) if db_file else None
            if c_key and c_key in _FAMILY_KEY_CACHE:
                exists = db_path.execute("SELECT 1 FROM families WHERE family_id = ?", (fid,)).fetchone()
                if exists:
                    return _FAMILY_KEY_CACHE[c_key]
            return _resolve_family_key_on_conn(db_path, fid, root_kek, c_key)
        except PermissionError:
            raise
        except Exception:
            return root_kek

    try:
        from db.session import resolve_db_path
        db_path = resolve_db_path(db_path, family_id=fid)
    except Exception:
        pass

    db_str = str(db_path)
    cache_key = (db_str, fid)
    cached = _FAMILY_KEY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if is_local:
        for (k_path, k_fid), k_fek in list(_FAMILY_KEY_CACHE.items()):
            if k_fid == fid and k_fek and not _is_non_public_db_path(k_path):
                return k_fek

    try:
        init_db(Path(db_path))
        with get_db_connection(db_path, timeout=30.0) as conn:
            return _resolve_family_key_on_conn(conn, fid, root_kek, cache_key)
    except PermissionError:
        raise
    except Exception:
        return root_kek


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
    rotated_family_ids: List[int] = []

    with get_db_connection(path_obj, timeout=30.0) as conn:
        rows = conn.execute(
            "SELECT family_id, encryption_key_enc, name FROM families ORDER BY family_id ASC"
        ).fetchall()
        for row in rows:
            fid = int(row[0])
            enc_dek = row[1]
            fam_name = row[2]
            if not enc_dek:
                continue
            rotated_dek = multi.rotate(str(enc_dek).encode("utf-8")).decode("utf-8")
            new_name = fam_name
            if isinstance(fam_name, str) and fam_name.startswith("gAAAAA"):
                try:
                    new_name = multi.rotate(fam_name.encode("utf-8")).decode("utf-8")
                except Exception:
                    new_name = fam_name
            conn.execute(
                "UPDATE families SET encryption_key_enc = ?, name = ? WHERE family_id = ?",
                (rotated_dek, new_name, fid),
            )
            rotated_family_ids.append(fid)

        try:
            u_rows = conn.execute(
                "SELECT user_id, pending_fek_enc FROM users WHERE pending_fek_enc IS NOT NULL AND pending_fek_enc != ''"
            ).fetchall()
            for u_row in u_rows:
                uid = int(u_row[0])
                p_fek = str(u_row[1])
                try:
                    rot_p_fek = multi.rotate(p_fek.encode("utf-8")).decode("utf-8")
                    conn.execute(
                        "UPDATE users SET pending_fek_enc = ? WHERE user_id = ?",
                        (rot_p_fek, uid),
                    )
                except Exception:
                    pass
        except Exception:
            pass
        conn.commit()

    _clear_security_caches()

    return {
        "rotated_count": len(rotated_family_ids),
        "family_ids": rotated_family_ids,
    }


def db_save_encrypted(db_path: Path, key: str, category: str, data: Any, family_id: int = 0) -> None:
    """Saves arbitrary data encrypted at rest in SQLite, strictly scoped by family_id."""
    if not family_id:
        return
    try:
        from db.session import resolve_db_path
        path_obj = resolve_db_path(db_path, family_id=family_id)
    except Exception:
        path_obj = Path(db_path)
    init_db(path_obj)
    try:
        from db import data_migration
        if data_migration.try_relational_save(path_obj, key, data, family_id):
            try:
                from db import store as _store
                from forecast_cache_helpers import resolve_domains_for_encrypted_key
                _store.notify_family_mutation(family_id, domains=resolve_domains_for_encrypted_key(key, category), db_path=path_obj)
            except Exception:
                pass
            return
    except PermissionError:
        raise
    except Exception:
        pass

    fam_key = get_family_key(path_obj, family_id)
    ciphertext = encrypt_data(data, key=fam_key)
    with get_db_connection(path_obj, timeout=30.0) as conn:
        conn.execute("""
            INSERT INTO family_encrypted_store (family_id, key, category, updated_at, encrypted_payload)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(family_id, key) DO UPDATE SET
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP,
                encrypted_payload = excluded.encrypted_payload
        """, (family_id, key, category, ciphertext))
        conn.commit()
    try:
        from db import store as _store
        from forecast_cache_helpers import resolve_domains_for_encrypted_key
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
    try:
        from db import data_migration
        handled, val = data_migration.try_relational_load(path_obj, key, family_id)
        if handled:
            return val
    except PermissionError:
        raise
    except Exception:
        pass

    fam_key = get_family_key(path_obj, family_id)
    with get_db_connection(path_obj, timeout=30.0) as conn:
        try:
            cur = conn.execute(
                "SELECT encrypted_payload FROM family_encrypted_store WHERE family_id = ? AND key = ?",
                (family_id, key)
            )
            row = cur.fetchone()
            if row:
                return decrypt_data(row[0], key=fam_key)
        except sqlite3.OperationalError:
            pass

        return None
