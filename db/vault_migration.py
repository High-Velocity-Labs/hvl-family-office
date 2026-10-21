"""
Cloud Vault `.fovault` Restore, Cross-Key Fernet Rotation, and Sandbox-to-Cloud-Vault Migration Repository.
Enables seamless migration of encrypted household SQLite vaults from Anonymous Workspace (Sandbox)
or Standalone Desktop `.fovault` files into an authenticated Google OAuth Cloud Vault.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, MultiFernet
from hvl_common.db import get_db_connection

import config
import security

logger = logging.getLogger(__name__)

_FERNET_TOKEN_RE = re.compile(r"gAAAAA[A-Za-z0-9_\-=]+")
_PLACEHOLDER_NAMES = {"", "sandbox guest", "household owner", "owner", "user", "member"}


def rotate_sqlite_fernet_tokens(db_path: Path, old_fek: bytes, new_fek: bytes) -> None:
    """
    Re-encrypts all FEK-encrypted Fernet ciphertexts (`gAAAAA...`) across all domain tables
    in `db_path` from `old_fek` to `new_fek` (including tokens embedded inside JSON columns),
    skipping KEK-wrapped columns (`encryption_key_enc`, `pending_fek_enc`, `passphrase_fek_enc`).
    """
    if not old_fek or not new_fek or old_fek == new_fek:
        return

    multi = MultiFernet([Fernet(new_fek), Fernet(old_fek)])

    def _replace_match(match: re.Match[str]) -> str:
        token_str = match.group(0)
        try:
            return multi.rotate(token_str.encode("utf-8")).decode("utf-8")
        except Exception:
            return token_str

    skip_cols = {"encryption_key_enc", "pending_fek_enc", "passphrase_fek_enc"}
    with get_db_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'alembic_%'"
            ).fetchall()
        ]
        for tbl in tables:
            pragma_sql = 'PRAGMA table_info("' + tbl + '")'
            col_info = conn.execute(pragma_sql).fetchall()
            cols = [c[1] for c in col_info if c[1] not in skip_cols]
            if not cols:
                continue
            col_select = ", ".join('"' + c + '"' for c in cols)
            select_sql = 'SELECT rowid, ' + col_select + ' FROM "' + tbl + '"'
            rows = conn.execute(select_sql).fetchall()
            for row in rows:
                rowid = row[0]
                updates: dict[str, Any] = {}
                for idx, col_name in enumerate(cols, start=1):
                    val = row[idx]
                    if isinstance(val, str) and "gAAAAA" in val:
                        new_val = _FERNET_TOKEN_RE.sub(_replace_match, val)
                        if new_val != val:
                            updates[col_name] = new_val
                if updates:
                    set_clause = ", ".join('"' + k + '" = ?' for k in updates)
                    update_sql = 'UPDATE "' + tbl + '" SET ' + set_clause + " WHERE rowid = ?"
                    params = list(updates.values()) + [rowid]
                    conn.execute(update_sql, params)
        conn.commit()


def snapshot_cloud_vault_auth_state(global_db: Path, dst_db: Path, family_id: int) -> dict[str, Any]:
    """Captures existing Cloud Vault FEK, family escrow flags, and authenticated Google user rows prior to restore."""
    fid = int(family_id)
    cloud_fek = security.get_request_vault_fek(fid)
    if not cloud_fek:
        probe_db = dst_db if dst_db.exists() else global_db
        if probe_db.exists():
            try:
                cloud_fek = security.get_family_key(probe_db, fid)
            except Exception:
                cloud_fek = None

    fam_meta: dict[str, Any] = {"support_access_enabled": 0, "encryption_key_enc": None, "settings": "{}"}
    auth_users: list[dict[str, Any]] = []

    for db_candidate in (global_db, dst_db):
        if not db_candidate.exists():
            continue
        try:
            with get_db_connection(db_candidate) as conn:
                conn.row_factory = sqlite3.Row
                f_row = conn.execute(
                    "SELECT name, encryption_key_enc, support_access_enabled, settings FROM families WHERE family_id = ?",
                    (fid,),
                ).fetchone()
                if f_row and fam_meta.get("encryption_key_enc") is None:
                    fam_meta = dict(f_row)

                u_rows = conn.execute(
                    "SELECT * FROM users WHERE family_id = ? AND email_hash IS NOT NULL AND email_hash != ''",
                    (fid,),
                ).fetchall()
                if u_rows and not auth_users:
                    auth_users = [dict(r) for r in u_rows]
        except Exception:
            continue

    return {"cloud_fek": cloud_fek, "fam_meta": fam_meta, "auth_users": auth_users}


def reconcile_cloud_vault_auth_after_restore(
    global_db: Path,
    dst_db: Path,
    family_id: int,
    active_fek: bytes,
    auth_snapshot: dict[str, Any],
    portable_fek_key: str = "_portable_vault_fek_b64",
) -> None:
    """
    Restores authenticated Google user credentials (`email_hash`, `email`, `user_id`, `google_vault_synced`)
    and Cloud Vault family settings after importing a `.fovault` into `dst_db`, then syncs `global.db`.
    """
    fid = int(family_id)
    fam_meta = auth_snapshot.get("fam_meta") or {}
    auth_users: list[dict[str, Any]] = auth_snapshot.get("auth_users") or []

    with get_db_connection(dst_db) as conn:
        conn.row_factory = sqlite3.Row
        f_row = conn.execute("SELECT name, settings FROM families WHERE family_id = ?", (fid,)).fetchone()
        imported_settings: dict[str, Any] = {}
        if f_row and f_row["settings"]:
            try:
                parsed = json.loads(f_row["settings"]) if isinstance(f_row["settings"], str) else {}
                if isinstance(parsed, dict):
                    imported_settings = parsed
            except Exception:
                imported_settings = {}
        imported_settings.pop(portable_fek_key, None)

        prev_settings: dict[str, Any] = {}
        if fam_meta.get("settings"):
            try:
                p_prev = json.loads(fam_meta["settings"]) if isinstance(fam_meta["settings"], str) else {}
                if isinstance(p_prev, dict):
                    prev_settings = p_prev
            except Exception:
                prev_settings = {}
        if "last_login_at" in prev_settings and "last_login_at" not in imported_settings:
            imported_settings["last_login_at"] = prev_settings["last_login_at"]

        imported_fam_name = str(f_row["name"] or "") if f_row else ""
        dec_fam_name = security.decrypt_field(imported_fam_name, default=imported_fam_name, key=active_fek).strip()
        if not dec_fam_name or dec_fam_name in ("Sandbox Household", "Restored Sandbox Household"):
            fallback_name = str(fam_meta.get("name") or "Family Office")
            final_fam_name = fallback_name
        else:
            final_fam_name = security.encrypt_string(dec_fam_name, key=active_fek)

        supp_enabled = int(fam_meta.get("support_access_enabled") or 0)
        enc_key_val = fam_meta.get("encryption_key_enc") if supp_enabled else None
        if supp_enabled and not enc_key_val and active_fek:
            kek = security.get_or_create_key()
            enc_key_val = security._get_fernet(kek).encrypt(active_fek).decode("utf-8")

        conn.execute(
            "UPDATE families SET name = ?, encryption_key_enc = ?, support_access_enabled = ?, settings = ? WHERE family_id = ?",
            (final_fam_name, enc_key_val, supp_enabled, json.dumps(imported_settings), fid),
        )

        # Reconcile users table: merge imported primary member name/birthdate with authenticated Google user(s)
        imported_users = [dict(r) for r in conn.execute("SELECT * FROM users WHERE family_id = ?", (fid,)).fetchall()]
        imported_primary = None
        for iu in imported_users:
            rel = str(iu.get("relationship") or "primary").lower()
            if rel in ("primary", "owner", ""):
                imported_primary = iu
                break

        if auth_users:
            imp_name_dec = ""
            imp_birth = ""
            if imported_primary:
                raw_n = str(imported_primary.get("name") or "")
                imp_name_dec = security.decrypt_field(raw_n, default=raw_n, key=active_fek).strip()
                imp_birth = str(imported_primary.get("birthdate") or "")

            # Remove unauthenticated primary/guest rows from imported snapshot
            for iu in imported_users:
                rel = str(iu.get("relationship") or "primary").lower()
                eh = str(iu.get("email_hash") or "").strip()
                if not eh and rel in ("primary", "owner", ""):
                    conn.execute("DELETE FROM users WHERE user_id = ?", (iu["user_id"],))

            u_cols = {c[1] for c in conn.execute("PRAGMA table_info(users)").fetchall()}
            for idx, au in enumerate(auth_users):
                merged = dict(au)
                merged["family_id"] = fid
                if idx == 0:
                    if imp_name_dec and imp_name_dec.lower() not in _PLACEHOLDER_NAMES:
                        merged["name"] = security.encrypt_string(imp_name_dec, key=active_fek)
                    if imp_birth:
                        merged["birthdate"] = (
                            security.encrypt_string(imp_birth, key=active_fek)
                            if not imp_birth.startswith("gAAAAA")
                            else imp_birth
                        )
                    if not merged.get("relationship"):
                        merged["relationship"] = "primary"
                valid_keys = [k for k in merged.keys() if k in u_cols]
                col_str = ", ".join('"' + k + '"' for k in valid_keys)
                placeholders = ", ".join("?" for _ in valid_keys)
                conn.execute(
                    "DELETE FROM users WHERE user_id = ? OR (email_hash = ? AND email_hash != '')",
                    (merged["user_id"], merged.get("email_hash") or ""),
                )
                ins_sql = "INSERT INTO users (" + col_str + ") VALUES (" + placeholders + ")"
                conn.execute(ins_sql, [merged[k] for k in valid_keys])
        conn.commit()

    # Sync reconciled families, users, and account_roles back to global.db
    if global_db.exists() and global_db.resolve() != dst_db.resolve():
        try:
            from db.session import _upsert_sql

            conflict_map = {
                "families": ("family_id",),
                "users": ("user_id",),
                "account_roles": ("family_id", "monarch_account_id"),
            }
            with get_db_connection(dst_db) as sconn, get_db_connection(global_db) as gconn:
                for tbl in ("families", "users", "account_roles"):
                    sel_sql = 'SELECT * FROM "' + tbl + '" WHERE family_id = ?'
                    rows = sconn.execute(sel_sql, (fid,)).fetchall()
                    s_info_sql = 'PRAGMA table_info("' + tbl + '")'
                    cols = [c[1] for c in sconn.execute(s_info_sql).fetchall()]
                    g_cols = {c[1] for c in gconn.execute(s_info_sql).fetchall()}
                    shared_cols = [c for c in cols if c in g_cols and (tbl != "account_roles" or c != "role_id")]
                    col_indices = [cols.index(c) for c in shared_cols]
                    if tbl in ("users", "account_roles"):
                        del_sql = 'DELETE FROM "' + tbl + '" WHERE family_id = ?'
                        gconn.execute(del_sql, (fid,))
                    ins_sql = _upsert_sql(tbl, shared_cols, conflict_map[tbl])
                    for r in rows:
                        vals = [r[i] for i in col_indices]
                        gconn.execute(ins_sql, vals)
                gconn.commit()
        except Exception as e:
            logger.warning(f"Failed syncing restored Cloud Vault {fid} to global.db: {e}")


def has_cloud_vault_financial_data(family_id: int, universe: str = "public") -> bool:
    """Returns True if the Cloud Vault household already has accounts, scenarios, equity grants, or compensation records."""
    fid = int(family_id or 0)
    if fid <= 0:
        return False
    fam_db = config.get_family_db_path(fid, universe)
    if not fam_db.exists():
        return False
    queries = (
        "SELECT COUNT(*) FROM monarch_accounts WHERE family_id = ?",
        "SELECT COUNT(*) FROM forecast_scenarios WHERE family_id = ?",
        "SELECT COUNT(*) FROM equity_companies WHERE family_id = ?",
        "SELECT COUNT(*) FROM equity_grants WHERE family_id = ?",
        "SELECT COUNT(*) FROM compensation WHERE family_id = ?",
    )
    try:
        with get_db_connection(fam_db) as conn:
            for q in queries:
                try:
                    row = conn.execute(q, (fid,)).fetchone()
                    if row and int(row[0] or 0) > 0:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False
