"""
Cloud Vault `.fovault` Restore, Cross-Key Fernet Rotation, and Sandbox-to-Cloud-Vault Migration Repository.
Enables seamless migration of encrypted household SQLite vaults from Anonymous Workspace (Sandbox)
or Standalone Desktop `.fovault` files into an authenticated Google OAuth Cloud Vault.
"""

from __future__ import annotations

from cryptography.fernet import InvalidToken
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, MultiFernet
from hvl_common.db import get_db_connection

import config
import security
from hvl_common.db.sqlite import quote_ident
from db.vault_restore_identity import (
    collect_verified_members,
    reinstate_verified_members,
    strip_archive_identities,
    sync_restored_household_to_global,
)

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
        except InvalidToken:
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
            qtbl = quote_ident(tbl)
            col_info = conn.execute("PRAGMA table_info(" + qtbl + ")").fetchall()
            cols = [c[1] for c in col_info if c[1] not in skip_cols]
            if not cols:
                continue
            col_select = ", ".join(quote_ident(c) for c in cols)
            select_sql = "SELECT rowid, " + col_select + " FROM " + qtbl
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
                    set_clause = ", ".join(quote_ident(k) + " = ?" for k in updates)
                    update_sql = "UPDATE " + qtbl + " SET " + set_clause + " WHERE rowid = ?"
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
            except PermissionError:
                cloud_fek = None

    fam_meta: dict[str, Any] = {"support_access_enabled": 0, "encryption_key_enc": None, "last_login_at": None}
    for db_candidate in (global_db, dst_db):
        if not db_candidate.exists():
            continue
        security.init_db(db_candidate)  # families.last_login_at exists only from alembic 0010 on
        try:
            with get_db_connection(db_candidate) as conn:
                conn.row_factory = sqlite3.Row
                f_row = conn.execute(
                    "SELECT name, encryption_key_enc, support_access_enabled, last_login_at FROM families "
                    "WHERE family_id = ?",
                    (fid,),
                ).fetchone()
                if f_row and fam_meta.get("encryption_key_enc") is None:
                    fam_meta = dict(f_row)
        except sqlite3.Error:
            continue

    auth_users = collect_verified_members(global_db, dst_db, fid)
    return {"cloud_fek": cloud_fek, "fam_meta": fam_meta, "auth_users": auth_users}


def reconcile_cloud_vault_auth_after_restore(
    global_db: Path,
    dst_db: Path,
    family_id: int,
    active_fek: bytes,
    auth_snapshot: dict[str, Any],
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
        f_row = conn.execute("SELECT name FROM families WHERE family_id = ?", (fid,)).fetchone()
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

        # The archive's portable key wrap is dropped; the household's last login survives a backup without one.
        conn.execute(
            "UPDATE families SET name = ?, encryption_key_enc = ?, support_access_enabled = ?, "
            "portable_vault_fek = NULL, last_login_at = COALESCE(last_login_at, ?) WHERE family_id = ?",
            (final_fam_name, enc_key_val, supp_enabled, fam_meta.get("last_login_at"), fid),
        )

        # The archive's users are untrusted: the caller's real login rows (captured before the restore) are the
        # only identities kept, the archive's owner rows fold into the caller, the rest become login-less members.
        imported_primary = None
        for iu in (dict(r) for r in conn.execute("SELECT * FROM users WHERE family_id = ?", (fid,)).fetchall()):
            if str(iu.get("relationship") or "primary").lower() in ("primary", "owner", ""):
                imported_primary = iu
                break

        strip_archive_identities(
            conn,
            fid,
            global_db=global_db,
            reserved_user_ids=tuple(int(a["user_id"]) for a in auth_users),
            fold_owner_into=int(auth_users[0]["user_id"]) if auth_users else None,
        )

        if auth_users:
            imp_name_dec = ""
            imp_birth = ""
            if imported_primary:
                raw_n = str(imported_primary.get("name") or "")
                imp_name_dec = security.decrypt_field(raw_n, default=raw_n, key=active_fek).strip()
                imp_birth = str(imported_primary.get("birthdate") or "")
            members = [dict(au) for au in auth_users]
            if imp_name_dec and imp_name_dec.lower() not in _PLACEHOLDER_NAMES:
                members[0]["name"] = security.encrypt_string(imp_name_dec, key=active_fek)
            if imp_birth:
                members[0]["birthdate"] = (
                    security.encrypt_string(imp_birth, key=active_fek) if not imp_birth.startswith("gAAAAA") else imp_birth
                )
            if not members[0].get("relationship"):
                members[0]["relationship"] = "primary"
            reinstate_verified_members(conn, fid, members)
        conn.commit()

    if global_db.exists() and global_db.resolve() != dst_db.resolve():
        try:
            sync_restored_household_to_global(global_db, dst_db, fid, auth_users)
        except sqlite3.Error as e:
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
    # An unreadable database is never reported as holding no financial data (a restore would overwrite it).
    with get_db_connection(fam_db) as conn:
        for q in queries:
            try:
                row = conn.execute(q, (fid,)).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                continue
            if row and int(row[0] or 0) > 0:
                return True
    return False
