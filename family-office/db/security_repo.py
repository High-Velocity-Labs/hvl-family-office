"""
SQLite repository functions for household audit/deletion quarantine,
invited household provisioning, and user metadata synchronization (invite tokens: `db/invite_repo.py`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple

from hvl_common.db import get_db_connection
from hvl_common.db.sqlite import quote_ident

logger = logging.getLogger(__name__)

# The database error callers outside db/ catch at a SQLite boundary.
DatabaseError = sqlite3.Error


def parse_settings_json(raw: Any) -> Dict[str, Any]:
    """Parses a `families.settings` JSON object; text that is not an object reads as `{}` and is logged."""
    if not raw or not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("families.settings is not valid JSON; reading it as empty")
        return {}
    return parsed if isinstance(parsed, dict) else {}

_TENANT_CLEANUP_TABLES = (
    "advisor_messages", "advisor_conversations", "monarch_holdings", "monarch_accounts", "account_balance_snapshots",
    "account_roles", "equity_grants", "equity_events", "equity_companies", "compensation",
    "tax_transcripts", "estate_trusts", "estate_beneficiaries", "gifting_records",
    "philanthropy_donations", "philanthropy_daf_accounts", "tuition_records",
    "forecast_scenarios", "family_encrypted_store", "family_state_versions", "household_profile",
    "household_assumption_sections",
)

_TENANT_CLEANUP_STATEMENTS: tuple[str, ...] = (
    "UPDATE families SET encryption_key_enc = NULL, support_access_enabled = 0 WHERE family_id = ?",
    "UPDATE users SET pending_fek_enc = NULL WHERE family_id = ?",
    *[f"DELETE FROM {quote_ident(t)} WHERE family_id = ?" for t in _TENANT_CLEANUP_TABLES],
    "DELETE FROM invite_tokens WHERE created_by_family_id = ?",
    "DELETE FROM users WHERE family_id = ?",
    "DELETE FROM families WHERE family_id = ?",
)


# `(deletion_scheduled_at, deletion_purge_after, deletion_requested_by)` of one household; all None while active.
DeletionQuarantine = Tuple[Optional[str], Optional[str], Optional[str]]


def fetch_family_deletion_quarantine(cand: Path, fid: int, timeout: float = 10.0) -> Optional[DeletionQuarantine]:
    """The deletion quarantine columns of `fid` in `cand`, or None when `cand` has no row for it."""
    with get_db_connection(cand, timeout=timeout) as conn:
        row = conn.execute(
            "SELECT deletion_scheduled_at, deletion_purge_after, deletion_requested_by FROM families "
            "WHERE family_id = ?",
            (fid,),
        ).fetchone()
        return (row[0], row[1], row[2]) if row else None


def write_family_deletion_quarantine(
    cand: Path, fid: int, quarantine: DeletionQuarantine, timeout: float = 15.0
) -> bool:
    """Sets (or with all None, clears) the deletion quarantine of `fid` in `cand`; False when it has no row."""
    with get_db_connection(cand, timeout=timeout) as conn:
        cur = conn.execute(
            "UPDATE families SET deletion_scheduled_at = ?, deletion_purge_after = ?, deletion_requested_by = ? "
            "WHERE family_id = ?",
            (*quarantine, fid),
        )
        conn.commit()
        return cur.rowcount > 0


def shred_family_in_shared_dbs(shared_dbs: List[Path], fam_db: Path, fid: int) -> None:
    """Executes tenant cleanup statements across shared DBs and nulls keys in `fam_db`."""
    # Shredding fails closed: any error other than a table this database does not have aborts the deletion, so
    # a household is never reported shredded while its key or rows survive.
    for s_db in shared_dbs:
        with get_db_connection(s_db, timeout=15.0) as conn:
            for stmt in _TENANT_CLEANUP_STATEMENTS:
                try:
                    conn.execute(stmt, (fid,))
                except sqlite3.OperationalError as exc:
                    if "no such table" not in str(exc):
                        raise
            conn.commit()

    if fam_db.exists():
        with get_db_connection(fam_db, timeout=10.0) as conn:
            conn.execute(
                "UPDATE families SET encryption_key_enc = NULL, support_access_enabled = 0 WHERE family_id = ?",
                (fid,),
            )
            conn.execute("UPDATE users SET pending_fek_enc = NULL WHERE family_id = ?", (fid,))
            conn.commit()


def fetch_quarantined_families(target_db: Path) -> List[Tuple[int, DeletionQuarantine]]:
    """`(family_id, quarantine)` of every household in `target_db` scheduled for deletion."""
    with get_db_connection(target_db, timeout=10.0) as conn:
        rows = conn.execute(
            "SELECT family_id, deletion_scheduled_at, deletion_purge_after, deletion_requested_by FROM families "
            "WHERE deletion_scheduled_at IS NOT NULL"
        ).fetchall()
    return [(int(r[0]), (r[1], r[2], r[3])) for r in rows if r[0]]


def fetch_family_metadata_fallback(
    db_path: Path, family_id: int
) -> Optional[Tuple[int, Any, Any, Any, DeletionQuarantine]]:
    """Fetches `(family_id, settings, support_access_enabled, created_at, quarantine)` without decrypting `name`."""
    with get_db_connection(db_path, timeout=30.0) as conn:
        row = conn.execute(
            "SELECT family_id, settings, support_access_enabled, created_at, deletion_scheduled_at, "
            "deletion_purge_after, deletion_requested_by FROM families WHERE family_id = ?",
            (int(family_id),),
        ).fetchone()
        if not row:
            return None
        return int(row[0]), row[1], row[2], row[3], (row[4], row[5], row[6])


def upsert_invited_household_metadata(
    dest_db: Path,
    new_fid: int,
    enc_household_name: str,
    initial_settings: str,
    enc_dek: str,
    state: str = "",
) -> None:
    """Upserts `families` and default `household_profile` rows for a newly provisioned invited household ("" state = not set)."""
    with get_db_connection(dest_db, timeout=15.0) as conn:
        conn.execute(
            """
            INSERT INTO families (family_id, name, settings, encryption_key_enc, support_access_enabled)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(family_id) DO UPDATE SET
                name = excluded.name,
                settings = excluded.settings,
                encryption_key_enc = excluded.encryption_key_enc
            """,
            (new_fid, enc_household_name, initial_settings, enc_dek),
        )
        conn.execute(
            """
            INSERT INTO household_profile (
                family_id, state, filing_status, annual_spending, annual_savings,
                retirement_age, inflation_rate, real_growth_rate
            ) VALUES (?, ?, 'MFJ', 120000.0, 50000.0, 60, 0.025, 0.045)
            ON CONFLICT(family_id) DO NOTHING
            """,
            (new_fid, state),
        )
        conn.commit()


def sync_user_row_between_dbs(
    src_db: Path,
    dest_db: Path,
    uid: int,
    mode: str = "timestamps",
) -> None:
    """Copies a `users` row for `uid` from `src_db` into `dest_db`."""
    with get_db_connection(src_db, timeout=10.0) as sconn, get_db_connection(dest_db, timeout=10.0) as dconn:
        if mode == "permissions":
            sconn.row_factory = sqlite3.Row
            u_row = sconn.execute(
                "SELECT user_id, family_id, name, email, email_hash, birthdate, relationship, role, permissions, pending_fek_enc, google_vault_synced FROM users WHERE user_id = ?",
                (uid,),
            ).fetchone()
            if u_row:
                dconn.execute(
                    "INSERT OR REPLACE INTO users (user_id, family_id, name, email, email_hash, birthdate, relationship, role, permissions, pending_fek_enc, google_vault_synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(u_row),
                )
                dconn.commit()
        elif mode == "core":
            u_row = sconn.execute(
                "SELECT user_id, family_id, name, email, email_hash, birthdate, relationship, role, pending_fek_enc, google_vault_synced FROM users WHERE user_id = ?",
                (uid,),
            ).fetchone()
            if u_row:
                dconn.execute(
                    "INSERT OR REPLACE INTO users (user_id, family_id, name, email, email_hash, birthdate, relationship, role, pending_fek_enc, google_vault_synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(u_row),
                )
                dconn.commit()
        else:
            u_row = sconn.execute(
                """
                SELECT user_id, family_id, name, email, email_hash, birthdate,
                       relationship, role, pending_fek_enc, google_vault_synced,
                       created_at, updated_at
                FROM users WHERE user_id = ?
                """,
                (uid,),
            ).fetchone()
            if u_row:
                dconn.execute(
                    """
                    INSERT OR REPLACE INTO users (
                        user_id, family_id, name, email, email_hash, birthdate,
                        relationship, role, pending_fek_enc, google_vault_synced,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tuple(u_row),
                )
                dconn.commit()


def fetch_pending_fek_from_db(cand: Path, target_fid: int) -> Optional[str]:
    """Fetches a non-empty `pending_fek_enc` for `target_fid` from `cand`."""
    with get_db_connection(cand, timeout=10.0) as conn:
        p_row = conn.execute(
            "SELECT pending_fek_enc FROM users WHERE family_id = ? AND pending_fek_enc IS NOT NULL AND pending_fek_enc != '' LIMIT 1",
            (target_fid,),
        ).fetchone()
        if p_row and p_row[0]:
            return str(p_row[0])
    return None


def fetch_max_user_id_across_dbs(cand_dbs: Tuple[Path, ...]) -> int:
    """Returns the maximum `user_id` across `cand_dbs`."""
    max_uid = 0
    for cand_db in cand_dbs:
        if cand_db.exists():
            with get_db_connection(cand_db, timeout=10.0) as conn:
                r = conn.execute("SELECT COALESCE(MAX(user_id), 0) FROM users").fetchone()
                if r and int(r[0] or 0) > max_uid:
                    max_uid = int(r[0])
    return max_uid


def fetch_local_primary_user_encrypted_name(db_cand: Path, fid: int, uid: int) -> Optional[str]:
    """Fetches the primary user's raw `name` value for `(fid, uid)` from `db_cand`."""
    with get_db_connection(db_cand) as p_conn:
        p_row = p_conn.execute(
            "SELECT name FROM users WHERE family_id = ? AND (relationship = 'primary' OR user_id = ?) AND name IS NOT NULL AND name != '' ORDER BY user_id ASC LIMIT 1",
            (fid, uid),
        ).fetchone()
        if p_row and p_row[0]:
            return str(p_row[0])
    return None


def check_local_passphrase_in_db(cand_dbs: list[Path], target_fid: int) -> bool:
    """Returns True if any candidate DB has `local_passphrase_fek_enc` in `families.settings`."""
    for cand in dict.fromkeys(cand_dbs):
        with get_db_connection(cand) as conn:
            row = conn.execute("SELECT settings FROM families WHERE family_id = ?", (target_fid,)).fetchone()
            if row and parse_settings_json(row[0]).get("local_passphrase_fek_enc"):
                return True
    return False


def upsert_first_local_household_in_db(
    db_target: Path,
    primary_fid: int,
    primary_uid: int,
    enc_hh_name: str,
    settings_json: str,
    enc_dek_fn: Callable[[], str],
    enc_user_name: str,
    enc_email: str,
    em_hash: str,
) -> None:
    """Upserts primary family and primary user row into `db_target`."""
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
            enc_dek = enc_dek_fn()
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


def fetch_local_login_record_from_dbs(cand_dbs: list[Path], primary_fid: int) -> Dict[str, Any]:
    """Reads `local_passphrase_fek_enc` and primary user row from `cand_dbs`."""
    wrapped_blob: Optional[str] = None
    enc_user_name = ""
    user_role = "editor"
    uid = primary_fid

    for db_target in cand_dbs:
        with get_db_connection(db_target) as conn:
            if not wrapped_blob:
                fam_row = conn.execute("SELECT settings FROM families WHERE family_id = ?", (primary_fid,)).fetchone()
                if fam_row:
                    wrapped_blob = parse_settings_json(fam_row[0]).get("local_passphrase_fek_enc") or wrapped_blob
            if not enc_user_name:
                u_row = conn.execute(
                    "SELECT user_id, name, role FROM users WHERE family_id = ? ORDER BY user_id ASC LIMIT 1",
                    (primary_fid,),
                ).fetchone()
                if u_row:
                    uid = int(u_row[0])
                    enc_user_name = str(u_row[1] or "")
                    user_role = str(u_row[2] or "editor")

    return {
        "family_id": primary_fid,
        "user_id": uid,
        "wrapped_blob": wrapped_blob,
        "enc_user_name": enc_user_name,
        "user_role": user_role,
    }


def update_local_passphrase_fek_in_dbs(
    dbs: Tuple[Path, ...],
    primary_fid: int,
    wrapped_passphrase_fek: str,
) -> None:
    """Updates `settings['local_passphrase_fek_enc']` across `dbs`."""
    for db_target in dbs:
        if not db_target.exists():
            continue
        with get_db_connection(db_target) as conn:
            row = conn.execute("SELECT settings FROM families WHERE family_id = ?", (primary_fid,)).fetchone()
            settings_dict = parse_settings_json(row[0]) if row else {}
            settings_dict["local_passphrase_fek_enc"] = wrapped_passphrase_fek
            conn.execute(
                "UPDATE families SET settings = ? WHERE family_id = ?",
                (json.dumps(settings_dict), primary_fid),
            )
            conn.commit()


def escrow_local_vault_key_in_db(db_target: Path, fid: int, enc_dek: str) -> None:
    """Writes `encryption_key_enc` and `support_access_enabled = 1` for `fid` in `db_target`."""
    with get_db_connection(db_target) as conn:
        conn.execute(
            "UPDATE families SET encryption_key_enc = ?, support_access_enabled = 1 WHERE family_id = ?",
            (enc_dek, fid),
        )
        conn.commit()

