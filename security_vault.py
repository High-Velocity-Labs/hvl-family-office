"""
Vault access lifecycle, server FEK escrow, and local passphrase vault management.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Optional
from hvl_common.db import get_db_connection


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

    if enabled:
        if not security._is_authenticated_for_family(fid):
            with get_db_connection(path_obj, timeout=30.0) as conn:
                row = conn.execute(
                    "SELECT encryption_key_enc FROM families WHERE family_id = ?",
                    (fid,),
                ).fetchone()
                if not row or not row[0]:
                    raise PermissionError(
                        f"Cannot enable support access for household {fid} without an authenticated member session."
                    )
        fam_key = security.get_family_key(path_obj, fid)
        enc_dek = fernet_kek.encrypt(fam_key).decode("utf-8")
        with get_db_connection(path_obj, timeout=30.0) as conn:
            conn.execute(
                "UPDATE families SET support_access_enabled = 1, encryption_key_enc = ? WHERE family_id = ?",
                (enc_dek, fid),
            )
            conn.commit()
        security._FAMILY_KEY_CACHE[(str(path_obj), fid)] = fam_key
    else:
        fam_key_opt: Optional[bytes] = None
        try:
            fam_key_opt = security.get_family_key(path_obj, fid)
        except PermissionError:
            with get_db_connection(path_obj, timeout=30.0) as conn:
                p_row = conn.execute(
                    "SELECT pending_fek_enc FROM users WHERE family_id = ? AND pending_fek_enc IS NOT NULL AND pending_fek_enc != '' LIMIT 1",
                    (fid,),
                ).fetchone()
                if p_row and p_row[0]:
                    try:
                        fam_key_opt = fernet_kek.decrypt(str(p_row[0]).encode("utf-8"))
                    except Exception:
                        fam_key_opt = None

        with get_db_connection(path_obj, timeout=30.0) as conn:
            if fam_key_opt is not None:
                if security._is_authenticated_for_family(fid):
                    security.stash_request_vault_fek(fid, fam_key_opt)
                enc_dek = fernet_kek.encrypt(fam_key_opt).decode("utf-8")
                conn.execute(
                    """
                    UPDATE users SET pending_fek_enc = ? WHERE family_id = ?
                    AND (google_vault_synced IS NULL OR google_vault_synced = 0)
                    AND (pending_fek_enc IS NULL OR pending_fek_enc = '')
                    """,
                    (enc_dek, fid),
                )
                fam_row = conn.execute("SELECT name FROM families WHERE family_id = ?", (fid,)).fetchone()
                if fam_row and fam_row[0] and not str(fam_row[0]).startswith("gAAAAA"):
                    enc_name = security.encrypt_string(str(fam_row[0]), key=fam_key_opt)
                    conn.execute("UPDATE families SET name = ? WHERE family_id = ?", (enc_name, fid))
            conn.execute(
                "UPDATE families SET support_access_enabled = 0, encryption_key_enc = NULL WHERE family_id = ?",
                (fid,),
            )
            conn.commit()

        for k in [k for k in security._FAMILY_KEY_CACHE if k[1] == fid]:
            security._FAMILY_KEY_CACHE.pop(k, None)

    try:
        p_name = path_obj.name
        peers = []
        if path_obj.parent.name == "families":
            uni_dir = path_obj.parent.parent
            for cand in (uni_dir / "global.db", uni_dir / "family_office.db"):
                if cand.exists() and cand.resolve() != path_obj.resolve():
                    peers.append(cand)
        elif p_name == "global.db":
            uni_dir = path_obj.parent
            for cand in (uni_dir / "families" / f"{fid}.db", uni_dir / "family_office.db"):
                if cand.exists() and cand.resolve() != path_obj.resolve():
                    peers.append(cand)
        elif p_name.startswith("family_office") and p_name.endswith(".db"):
            uni_dir = path_obj.parent
            for cand in (uni_dir / "families" / f"{fid}.db", uni_dir / "global.db"):
                if cand.exists() and cand.resolve() != path_obj.resolve():
                    peers.append(cand)

        for peer in peers:
            with get_db_connection(peer, timeout=10.0) as pconn, get_db_connection(path_obj, timeout=10.0) as sconn:
                row = sconn.execute(
                    "SELECT support_access_enabled, encryption_key_enc, name FROM families WHERE family_id = ?",
                    (fid,),
                ).fetchone()
                if row:
                    pconn.execute(
                        "UPDATE families SET support_access_enabled = ?, encryption_key_enc = ?, name = ? WHERE family_id = ?",
                        (row[0], row[1], row[2], fid),
                    )
                    pconn.commit()
    except Exception:
        pass

    try:
        from db import store as _store
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
        with get_db_connection(target_db) as conn:
            u_row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
            if int(u_row[0] if u_row else 0) > 0:
                return False

            fam1_cand = target_db.parent / "families" / "1.db"
            if fam1_cand.exists():
                try:
                    with get_db_connection(fam1_cand) as fconn:
                        fu_row = fconn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()
                        if int(fu_row[0] if fu_row else 0) > 0:
                            u_records = fconn.execute("SELECT * FROM users WHERE family_id = 1").fetchall()
                            cols = [c[1] for c in fconn.execute("PRAGMA table_info(users)").fetchall()]
                            if u_records and cols:
                                col_str = ", ".join(f'"{c}"' for c in cols)
                                placeholders = ", ".join("?" for _ in cols)
                                conn.execute("DELETE FROM users WHERE family_id = 1")
                                conn.executemany(
                                    f"INSERT OR REPLACE INTO users ({col_str}) VALUES ({placeholders})",
                                    [tuple(r) for r in u_records],
                                )
                                conn.commit()
                            return False
                except Exception:
                    pass

            fam_rows = conn.execute("SELECT family_id, settings FROM families WHERE family_id > 0").fetchall()
            for fid, settings_str in fam_rows:
                if settings_str:
                    try:
                        s = json.loads(settings_str) if isinstance(settings_str, str) else {}
                        if s.get("local_passphrase_fek_enc") or s.get("onboarding_completed"):
                            return False
                    except Exception:
                        pass
    except Exception:
        pass
    return True


def has_local_passphrase_configured(db_path: Path, family_id: int = 0) -> bool:
    """Returns True if Household has a PBKDF2-wrapped Master Passphrase/PIN configured."""
    target_db = Path(db_path)
    target_fid = int(family_id) if int(family_id) > 0 else 1
    cand_dbs = []
    if target_db.exists():
        cand_dbs.append(target_db)
    fam_db = target_db.parent / "families" / f"{target_fid}.db"
    if fam_db.exists() and fam_db not in cand_dbs:
        cand_dbs.append(fam_db)

    for cand in cand_dbs:
        try:
            with get_db_connection(cand) as conn:
                row = conn.execute("SELECT settings FROM families WHERE family_id = ?", (target_fid,)).fetchone()
                if row and row[0]:
                    parsed = json.loads(row[0]) if isinstance(row[0], str) else {}
                    if isinstance(parsed, dict) and parsed.get("local_passphrase_fek_enc"):
                        return True
        except Exception:
            continue
    return False


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

    primary_fid = 1
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
        "primary_state": "WA",
        "tax_filing_status": "MFJ",
        "onboarding_completed": False,
        "onboarding_dismissed": False,
    }
    if wrapped_passphrase_fek:
        settings_dict["local_passphrase_fek_enc"] = wrapped_passphrase_fek
    settings_json = json.dumps(settings_dict)

    for db_target in (global_db, family_db):
        with get_db_connection(db_target) as conn:
            existing_fam = conn.execute(
                "SELECT family_id FROM families WHERE family_id = ?",
                (primary_fid,),
            ).fetchone()
            if existing_fam:
                conn.execute(
                    "UPDATE families SET name = ?, settings = ? WHERE family_id = ?",
                    (enc_hh_name, settings_json, primary_fid),
                )
            else:
                enc_dek = security._get_fernet(security.get_or_create_key()).encrypt(raw_fek).decode("utf-8")
                conn.execute(
                    "INSERT INTO families (family_id, name, settings, encryption_key_enc, support_access_enabled) VALUES (?, ?, ?, ?, 1)",
                    (primary_fid, enc_hh_name, settings_json, enc_dek),
                )

            conn.execute("DELETE FROM users WHERE family_id = ?", (primary_fid,))
            conn.execute(
                """
                INSERT INTO users (user_id, family_id, name, email, email_hash, relationship, role, google_vault_synced)
                VALUES (?, ?, ?, ?, ?, 'primary', 'editor', 0)
                """,
                (primary_uid, primary_fid, enc_user_name, enc_email, em_hash),
            )
            conn.commit()
        security._FAMILY_KEY_CACHE[(str(db_target), primary_fid)] = raw_fek

    return primary_fid, primary_uid, raw_fek


def get_local_login_record(global_db: Path, family_id: int = 0) -> Dict[str, Any]:
    """Loads wrapped local passphrase FEK blob and primary user metadata."""
    primary_fid = int(family_id) if int(family_id) > 0 else 1
    wrapped_blob: Optional[str] = None
    enc_user_name = ""
    user_role = "editor"
    uid = primary_fid
    cand_dbs = []
    if global_db.exists():
        cand_dbs.append(global_db)
    fam_db = global_db.parent / "families" / f"{primary_fid}.db"
    if fam_db.exists() and fam_db not in cand_dbs:
        cand_dbs.append(fam_db)

    for db_target in cand_dbs:
        try:
            with get_db_connection(db_target) as conn:
                if not wrapped_blob:
                    fam_row = conn.execute("SELECT settings FROM families WHERE family_id = ?", (primary_fid,)).fetchone()
                    if fam_row and fam_row[0]:
                        try:
                            parsed = json.loads(fam_row[0]) if isinstance(fam_row[0], str) else {}
                            if isinstance(parsed, dict) and parsed.get("local_passphrase_fek_enc"):
                                wrapped_blob = parsed.get("local_passphrase_fek_enc")
                        except Exception:
                            pass
                if not enc_user_name:
                    u_row = conn.execute(
                        "SELECT user_id, name, role FROM users WHERE family_id = ? ORDER BY user_id ASC LIMIT 1",
                        (primary_fid,),
                    ).fetchone()
                    if u_row:
                        uid = int(u_row[0])
                        enc_user_name = str(u_row[1] or "")
                        user_role = str(u_row[2] or "editor")
        except Exception:
            continue

    return {
        "family_id": primary_fid,
        "user_id": uid,
        "wrapped_blob": wrapped_blob,
        "enc_user_name": enc_user_name,
        "user_role": user_role,
    }


def update_local_passphrase_fek(
    global_db: Path,
    family_db: Path,
    wrapped_passphrase_fek: str,
    family_id: int = 0,
) -> None:
    """Updates settings['local_passphrase_fek_enc'] in both global_db and family_db."""
    primary_fid = int(family_id) if int(family_id) > 0 else 1
    for db_target in (global_db, family_db):
        if not db_target.exists():
            continue
        with get_db_connection(db_target) as conn:
            row = conn.execute("SELECT settings FROM families WHERE family_id = ?", (primary_fid,)).fetchone()
            settings_dict: Dict[str, Any] = {}
            if row and row[0]:
                try:
                    parsed = json.loads(row[0]) if isinstance(row[0], str) else {}
                    if isinstance(parsed, dict):
                        settings_dict = parsed
                except Exception:
                    settings_dict = {}
            settings_dict["local_passphrase_fek_enc"] = wrapped_passphrase_fek
            conn.execute(
                "UPDATE families SET settings = ? WHERE family_id = ?",
                (json.dumps(settings_dict), primary_fid),
            )
            conn.commit()


def escrow_local_vault_key(
    global_db: Path,
    family_db: Path,
    raw_fek: bytes,
    family_id: int = 0,
) -> None:
    """Escrows local household encryption key (FEK) into families table."""
    import security

    fid = int(family_id) if int(family_id) > 0 else 1
    root_kek = security.get_or_create_key()
    enc_dek = security._get_fernet(root_kek).encrypt(raw_fek).decode("utf-8")
    for db_target in (global_db, family_db):
        if db_target.exists():
            with get_db_connection(db_target) as conn:
                conn.execute(
                    "UPDATE families SET encryption_key_enc = ?, support_access_enabled = 1 WHERE family_id = ?",
                    (enc_dek, fid),
                )
                conn.commit()
            security._FAMILY_KEY_CACHE[(str(db_target), fid)] = raw_fek
