"""
Repository layer for portable `.fovault` SQLite backup/restore operations,
FEK extraction/scrubbing, and cross-instance `family_id` remapping.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from hvl_common.db import close_all_pools, get_db_connection

import security

PORTABLE_VAULT_FEK_KEY = "_portable_vault_fek_b64"


def copy_sqlite_backup(src_db: Path, dst_db: Path) -> None:
    """Performs an online SQLite `.backup()` copy from `src_db` to `dst_db`."""
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    try:
        with get_db_connection(src_db) as src_conn, get_db_connection(dst_db) as dst_conn:
            src_conn.backup(dst_conn)
    finally:
        close_all_pools(dst_db)


def remap_vault_family_id(db_path: Path, target_fid: int) -> int:
    """
    Remaps all household records inside `db_path` from their source `family_id` to `target_fid`,
    removing any conflicting placeholder rows (like `family_id = 1` created by `init_db`) so a
    `.fovault` archive can move seamlessly between Cloud Sandbox (`100000..999999`),
    Cloud Vault (`1..N`), and Local Desktop Mode (`1`). Returns the detected source `family_id`.
    """
    new_fid = int(target_fid)
    try:
        with get_db_connection(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            rows = conn.execute(
                "SELECT family_id FROM families ORDER BY CASE WHEN family_id = ? THEN 1 ELSE 0 END ASC, family_id DESC",
                (new_fid,),
            ).fetchall()
            if not rows:
                return new_fid
            source_fid = int(rows[0][0])
            if len(rows) > 1:
                non_one = [int(r[0]) for r in rows if int(r[0]) != 1]
                if non_one:
                    source_fid = non_one[0]

            all_tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for tbl in all_tables:
                info_sql = 'PRAGMA table_info("' + tbl + '")'
                cols = {c[1] for c in conn.execute(info_sql).fetchall()}
                for fk_col in ("family_id", "created_by_family_id"):
                    if fk_col in cols:
                        if source_fid != new_fid:
                            del_sql = 'DELETE FROM "' + tbl + '" WHERE "' + fk_col + '" != ?'
                            upd_sql = 'UPDATE "' + tbl + '" SET "' + fk_col + '" = ? WHERE "' + fk_col + '" = ?'
                            conn.execute(del_sql, (source_fid,))
                            conn.execute(upd_sql, (new_fid, source_fid))
                        else:
                            del_sql = 'DELETE FROM "' + tbl + '" WHERE "' + fk_col + '" != ?'
                            conn.execute(del_sql, (new_fid,))
            conn.commit()
        return source_fid
    finally:
        close_all_pools(db_path)


def _get_portable_vault_fernet(passphrase: str | None = None) -> Fernet:
    """Derives a Fernet key-wrapping cipher for portable `.fovault` archives."""
    import base64
    import hashlib
    import os

    secret = (passphrase if passphrase is not None else os.getenv("FOVAULT_EXPORT_PASSPHRASE", "")).strip()
    material = f"hvl-fovault-portable-wrap-v1:{secret}".encode("utf-8")
    digest = hashlib.pbkdf2_hmac("sha256", material, b"hvl-family-office-fovault-salt", 100_000, dklen=32)
    return Fernet(base64.urlsafe_b64encode(digest))


def inject_wrapped_fek_into_backup(
    src_db: Path, backup_path: Path, family_id: int, passphrase: str | None = None
) -> None:
    """
    Embeds both the KEK-wrapped FEK and a wrapped portable FEK into the exported `.fovault` backup file
    so the user's downloaded `.fovault` never contains the raw unwrapped FEK in plaintext.
    """
    fam_key = security.get_request_vault_fek(family_id) or security.get_family_key(src_db, family_id)
    if fam_key:
        kek = security.get_or_create_key()
        raw_fek_bytes = fam_key if isinstance(fam_key, bytes) else str(fam_key).encode("utf-8")
        enc_dek = security._get_fernet(kek).encrypt(raw_fek_bytes).decode("utf-8")
        wrapped_portable_fek = _get_portable_vault_fernet(passphrase).encrypt(raw_fek_bytes).decode("utf-8")
        try:
            with get_db_connection(backup_path) as b_conn:
                row = b_conn.execute("SELECT settings FROM families WHERE family_id = ?", (family_id,)).fetchone()
                settings_dict: dict[str, Any] = {}
                if row and row[0]:
                    try:
                        parsed = json.loads(row[0]) if isinstance(row[0], str) else {}
                        if isinstance(parsed, dict):
                            settings_dict = parsed
                    except Exception:
                        settings_dict = {}
                settings_dict[PORTABLE_VAULT_FEK_KEY] = wrapped_portable_fek
                b_conn.execute(
                    "UPDATE families SET encryption_key_enc = ?, settings = ? WHERE family_id = ?",
                    (enc_dek, json.dumps(settings_dict), family_id),
                )
                b_conn.commit()
                try:
                    b_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    b_conn.execute("PRAGMA journal_mode=DELETE")
                except Exception:
                    pass
        finally:
            close_all_pools(backup_path)


def extract_fek_from_backup_snapshot(snapshot_path: Path, passphrase: str | None = None) -> bytes | None:
    """
    Extracts the household FEK from a `.fovault` snapshot file:
    1. Checks if `families.encryption_key_enc` can be unwrapped with the local KEK.
    2. Unwraps the portable FEK embedded in `families.settings['_portable_vault_fek_b64']`.
    """
    try:
        with get_db_connection(snapshot_path) as tconn:
            rows = tconn.execute(
                "SELECT family_id, encryption_key_enc, settings FROM families ORDER BY family_id DESC"
            ).fetchall()
            for r in rows:
                enc_key = r[1]
                settings_raw = r[2]
                if enc_key:
                    try:
                        kek = security.get_or_create_key()
                        return security._get_fernet(kek).decrypt(str(enc_key).encode("utf-8"))
                    except Exception:
                        pass
                if settings_raw:
                    try:
                        parsed = json.loads(settings_raw) if isinstance(settings_raw, str) else {}
                        cand = parsed.get(PORTABLE_VAULT_FEK_KEY) if isinstance(parsed, dict) else None
                        if cand and isinstance(cand, str):
                            if cand.startswith("gAAAAA"):
                                unwrapped = _get_portable_vault_fernet(passphrase).decrypt(cand.encode("utf-8"))
                                Fernet(unwrapped)
                                return unwrapped
                            Fernet(cand.encode("utf-8"))
                            return cand.encode("utf-8")
                    except Exception:
                        pass
    except Exception:
        pass
    finally:
        close_all_pools(snapshot_path)
    return None


def scrub_escrowed_fek_in_sandbox_db(
    db_path: Path, family_id: int, raw_fek: bytes | None = None
) -> None:
    """Ensures encryption_key_enc and portable FEK are scrubbed on disk in a sandbox database."""
    with get_db_connection(db_path) as dconn:
        row = dconn.execute(
            "SELECT settings, name FROM families WHERE family_id = ?", (family_id,)
        ).fetchone()
        settings_json = None
        if row and row[0]:
            try:
                parsed = json.loads(row[0]) if isinstance(row[0], str) else {}
                if isinstance(parsed, dict) and PORTABLE_VAULT_FEK_KEY in parsed:
                    parsed.pop(PORTABLE_VAULT_FEK_KEY, None)
                    settings_json = json.dumps(parsed)
            except Exception:
                pass
        if raw_fek and row and row[1] and not str(row[1]).startswith("gAAAAA"):
            enc_name = security.encrypt_string(str(row[1]), key=raw_fek)
            dconn.execute(
                "UPDATE families SET name = ? WHERE family_id = ?",
                (enc_name, family_id),
            )
        if settings_json is not None:
            dconn.execute(
                "UPDATE families SET encryption_key_enc = NULL, support_access_enabled = 0, settings = ? WHERE family_id = ?",
                (settings_json, family_id),
            )
        else:
            dconn.execute(
                "UPDATE families SET encryption_key_enc = NULL, support_access_enabled = 0 WHERE family_id = ?",
                (family_id,),
            )
        dconn.commit()
    security._FAMILY_KEY_CACHE.pop((str(db_path), int(family_id)), None)
    security._FAMILY_KEY_CACHE.pop((str(db_path.resolve()), int(family_id)), None)


def get_vault_import_summary(db_path: Path, family_id: int, raw_fek: bytes | None = None) -> dict[str, Any]:
    """Computes a concise summary of household records restored into `db_path` for `family_id`."""
    summary: dict[str, Any] = {
        "household_name": "Restored Household",
        "accounts": 0,
        "holdings": 0,
        "members": 0,
        "scenarios": 0,
        "equity_grants": 0,
        "compensation_years": 0,
        "advisor_threads": 0,
        "summary_text": "Vault backup restored successfully.",
    }
    try:
        with get_db_connection(db_path) as conn:
            row = conn.execute("SELECT name FROM families WHERE family_id = ?", (family_id,)).fetchone()
            if row and row[0]:
                raw_name = str(row[0])
                dec_name = security.decrypt_field(raw_name, default=raw_name, key=raw_fek) if raw_fek else raw_name
                if dec_name and dec_name.strip():
                    summary["household_name"] = dec_name.strip()

            u_rows = conn.execute("SELECT name FROM users WHERE family_id = ?", (family_id,)).fetchall()
            member_count = 0
            for ur in u_rows:
                uname = str(ur[0] or "")
                dec_u = security.decrypt_field(uname, default=uname, key=raw_fek) if raw_fek else uname
                if dec_u.strip() and dec_u.strip() != "Sandbox Guest":
                    member_count += 1
            summary["members"] = max(member_count, len(u_rows) if member_count == 0 and u_rows else 0)

            count_queries = (
                ("accounts", "SELECT COUNT(*) FROM monarch_accounts WHERE family_id = ?"),
                ("holdings", "SELECT COUNT(*) FROM monarch_holdings WHERE family_id = ?"),
                ("scenarios", "SELECT COUNT(*) FROM forecast_scenarios WHERE family_id = ?"),
                ("equity_grants", "SELECT COUNT(*) FROM equity_grants WHERE family_id = ?"),
                ("compensation_years", "SELECT COUNT(*) FROM compensation WHERE family_id = ?"),
                ("advisor_threads", "SELECT COUNT(*) FROM advisor_conversations WHERE family_id = ?"),
            )
            for key, q_sql in count_queries:
                try:
                    c_row = conn.execute(q_sql, (family_id,)).fetchone()
                    summary[key] = int(c_row[0] or 0) if c_row else 0
                except Exception:
                    summary[key] = 0

        bullets: list[str] = []
        if summary["accounts"] > 0:
            bullets.append(f"• {summary['accounts']} financial account{'s' if summary['accounts'] != 1 else ''}")
        if summary["holdings"] > 0:
            bullets.append(f"• {summary['holdings']} investment holding{'s' if summary['holdings'] != 1 else ''}")
        if summary["members"] > 0:
            bullets.append(f"• {summary['members']} household member{'s' if summary['members'] != 1 else ''}")
        if summary["scenarios"] > 0:
            bullets.append(f"• {summary['scenarios']} forecast scenario{'s' if summary['scenarios'] != 1 else ''}")
        if summary["equity_grants"] > 0:
            bullets.append(f"• {summary['equity_grants']} equity grant{'s' if summary['equity_grants'] != 1 else ''}")
        if summary["compensation_years"] > 0:
            bullets.append(f"• {summary['compensation_years']} tax & compensation record{'s' if summary['compensation_years'] != 1 else ''}")
        if summary["advisor_threads"] > 0:
            bullets.append(f"• {summary['advisor_threads']} AI Advisor conversation{'s' if summary['advisor_threads'] != 1 else ''}")

        hh_label = summary["household_name"]
        header = f'Restored "{hh_label}" into your active vault.'
        summary["summary_text"] = (header + "\n\n" + "\n".join(bullets)) if bullets else header
    except Exception:
        pass
    finally:
        close_all_pools(db_path)
    return summary
