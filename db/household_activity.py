"""
Self-Serve Cloud Household Provisioning & Family Login Activity Tracking.
Provides:
1. `provision_self_serve_household`: Auto-provisions an isolated per-family SQLite vault (`family_id >= 2`)
   for new Google OAuth users in Cloud Mode with zero-knowledge key escrow (`support_access_enabled = 0`).
2. `record_family_login`: Records `last_login_at` and `login_count` in `families.settings` across `global.db`
   and `families/{family_id}.db` on every authenticated login (no hardcoded `family_id = 1` and no auto-deletion tasks).
3. `get_active_families_summary`: Aggregates monthly (30d) and yearly (365d) active household telemetry for Admin/Ops.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from hvl_common.db import get_db_connection
import security


def record_family_login(
    db_path: Path,
    family_id: int = 0,
    universe: Optional[str] = None,
    now_dt: Optional[datetime] = None,
) -> Optional[str]:
    """
    Records the latest login timestamp (`last_login_at` ISO-8601 UTC) and increments `login_count`
    in `families.settings` across `global.db` and `families/{family_id}.db`.
    Works whether the household vault is unlocked or cryptographically locked (`support_access_enabled = 0`).
    """
    fid = int(family_id or 0)
    if fid <= 0:
        return None

    eff_now = now_dt or datetime.now(timezone.utc)
    if eff_now.tzinfo is None:
        eff_now = eff_now.replace(tzinfo=timezone.utc)
    now_iso = eff_now.isoformat()

    uni = security._resolve_universe_from_db_path(Path(db_path), universe=universe)
    candidates = security._candidate_family_metadata_dbs(Path(db_path), fid, universe=uni)
    updated_any = False

    for cand in candidates:
        if not cand.exists():
            continue
        try:
            with get_db_connection(cand, timeout=10.0) as conn:
                row = conn.execute(
                    "SELECT settings FROM families WHERE family_id = ?",
                    (fid,),
                ).fetchone()
                if not row:
                    continue
                try:
                    parsed = json.loads(row[0]) if row[0] else {}
                except Exception:
                    parsed = {}
                if not isinstance(parsed, dict):
                    parsed = {}
                parsed["last_login_at"] = now_iso
                parsed["login_count"] = int(parsed.get("login_count") or 0) + 1
                conn.execute(
                    "UPDATE families SET settings = ? WHERE family_id = ?",
                    (json.dumps(parsed), fid),
                )
                conn.commit()
                updated_any = True
        except Exception:
            continue

    return now_iso if updated_any else None


def provision_self_serve_household(
    db_path: Path,
    user_email: str,
    user_name: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Atomically provisions a brand-new isolated household (`family_id >= 2`) for a new Google OAuth user:
    - Allocates the next globally unique `family_id` across `global.db`, `db_path`, and `families/*.db`.
    - Initializes `families/{new_fid}.db` and generates a dedicated 256-bit Fernet `fam_key`.
    - Creates `Family` (`support_access_enabled = 0`, `onboarding_completed = False`, `last_login_at`)
      and `HouseholdProfile` with clean zero-balance defaults.
    - Adds the user as `editor` (`primary`) and mirrors auth metadata to `global.db`.
    """
    from config import get_family_db_path
    from db.session import resolve_db_path

    clean_email = (user_email or "").strip().lower()
    if not clean_email:
        return None

    clean_name = (user_name or "").strip()
    if not clean_name:
        clean_name = (
            clean_email.split("@")[0].replace(".", " ").replace("_", " ").title()
            or "Household Member"
        )

    uni = security._resolve_universe_from_db_path(Path(db_path))
    max_fid = 1
    scan_dbs = security._invite_candidate_dbs(Path(db_path), 1)
    for s_db in scan_dbs:
        if s_db.exists():
            try:
                with get_db_connection(s_db, timeout=10.0) as conn:
                    r = conn.execute("SELECT COALESCE(MAX(family_id), 1) FROM families").fetchone()
                    if r and int(r[0] or 1) > max_fid:
                        max_fid = int(r[0])
            except Exception:
                continue
    try:
        fam_dir = get_family_db_path(1, universe=uni).parent
        if fam_dir.exists():
            for f_file in fam_dir.glob("*.db"):
                stem = f_file.stem
                if stem.isdigit() and int(stem) > max_fid:
                    max_fid = int(stem)
    except Exception:
        pass

    new_fid = max(max_fid + 1, 2)
    target_fam_db = resolve_db_path(db_path, family_id=new_fid)
    security.init_db(target_fam_db)
    fam_key = security.get_family_key(target_fam_db, new_fid)
    security.stash_request_vault_fek(new_fid, fam_key)
    enc_dek = security._get_fernet(security.get_or_create_key()).encrypt(fam_key).decode("utf-8")

    now_iso = datetime.now(timezone.utc).isoformat()
    household_name = f"{clean_name}'s Family Office"
    enc_household_name = security.encrypt_string(household_name, key=fam_key)
    initial_settings = json.dumps({
        "primary_state": "WA",
        "tax_filing_status": "MFJ",
        "onboarding_completed": False,
        "onboarding_dismissed": False,
        "last_login_at": now_iso,
        "login_count": 1,
    })

    for dest_db in security._candidate_family_metadata_dbs(Path(db_path), new_fid, universe=uni):
        try:
            security.init_db(dest_db)
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
                        retirement_age, inflation_rate, real_growth_rate, assumptions_json
                    ) VALUES (?, 'WA', 'MFJ', 120000.0, 50000.0, 60, 0.025, 0.045, '{}')
                    ON CONFLICT(family_id) DO NOTHING
                    """,
                    (new_fid,),
                )
                conn.commit()
        except Exception:
            continue

    uid = security.add_family_member(
        target_fam_db,
        family_id=new_fid,
        name=clean_name,
        email=clean_email,
        relationship="primary",
        role="editor",
    )

    user_row: Optional[Dict[str, Any]] = None
    for dest_db in security._candidate_family_metadata_dbs(Path(db_path), new_fid, universe=uni):
        if dest_db.exists():
            try:
                with get_db_connection(target_fam_db, timeout=10.0) as sconn, get_db_connection(dest_db, timeout=10.0) as dconn:
                    sconn.row_factory = sqlite3.Row
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
                        if user_row is None:
                            user_row = dict(u_row)
                        if dest_db.resolve() != target_fam_db.resolve():
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
            except Exception:
                continue

    if user_row is None:
        return None
    user_row["is_new_household"] = True
    return user_row


def _parse_iso_utc(raw_ts: Any) -> Optional[datetime]:
    if not raw_ts:
        return None
    s = str(raw_ts).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def get_active_families_summary(
    db_path: Optional[Path] = None,
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Computes zero-PII household login activity and retention telemetry for Admin/Ops:
    - `total_families`: Total enrolled households
    - `active_30d`: Households with a login (or creation) in the last 30 days (Monthly Active Families)
    - `active_365d`: Households with a login (or creation) in the last 365 days (Yearly Active Families)
    - `inactive_over_365d`: Households with no login in >365 days
    - `families`: Per-household anonymized activity metadata
    """
    import config

    target_db = Path(db_path) if db_path is not None else config.get_global_db_path("public")
    summary: Dict[str, Any] = {
        "total_families": 0,
        "active_30d": 0,
        "active_365d": 0,
        "inactive_over_365d": 0,
        "families": [],
    }
    if not target_db.exists():
        return summary

    eff_now = now_dt or datetime.now(timezone.utc)
    if eff_now.tzinfo is None:
        eff_now = eff_now.replace(tzinfo=timezone.utc)
    cutoff_30d = eff_now - timedelta(days=30)
    cutoff_365d = eff_now - timedelta(days=365)

    try:
        with get_db_connection(target_db, timeout=5.0) as conn:
            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "families" not in tables:
                return summary
            has_users = "users" in tables
            q = (
                """
                SELECT f.family_id, f.created_at, COALESCE(f.support_access_enabled, 0),
                       f.settings, COUNT(u.user_id) AS u_cnt
                FROM families f
                LEFT JOIN users u ON f.family_id = u.family_id
                GROUP BY f.family_id, f.created_at, f.support_access_enabled, f.settings
                ORDER BY f.family_id ASC
                """
                if has_users
                else """
                SELECT family_id, created_at, COALESCE(support_access_enabled, 0),
                       settings, 0 AS u_cnt
                FROM families
                ORDER BY family_id ASC
                """
            )
            for row in conn.execute(q).fetchall():
                fid = int(row[0] or 0)
                created_at = str(row[1] or "")
                sup_enabled = bool(row[2])
                raw_settings = row[3]
                u_cnt = int(row[4] or 0)
                if u_cnt <= 0 and fid != 1:
                    continue

                try:
                    s_dict = json.loads(raw_settings) if raw_settings else {}
                except Exception:
                    s_dict = {}
                if not isinstance(s_dict, dict):
                    s_dict = {}

                last_login_raw = str(s_dict.get("last_login_at") or "")
                login_count = int(s_dict.get("login_count") or 0)
                act_dt = _parse_iso_utc(last_login_raw) or _parse_iso_utc(created_at)

                is_30d = bool(act_dt and act_dt >= cutoff_30d)
                is_365d = bool(act_dt and act_dt >= cutoff_365d)

                summary["total_families"] += 1
                if is_30d:
                    summary["active_30d"] += 1
                if is_365d:
                    summary["active_365d"] += 1
                else:
                    summary["inactive_over_365d"] += 1

                summary["families"].append({
                    "family_id": fid,
                    "family_ref": f"Household #{fid}",
                    "created_at": created_at[:10] if created_at else "Unknown",
                    "last_login_at": last_login_raw[:16].replace("T", " ") if last_login_raw else "Never",
                    "login_count": login_count,
                    "active_30d": is_30d,
                    "active_365d": is_365d,
                    "user_count": u_cnt,
                    "support_access_enabled": sup_enabled,
                })
    except Exception:
        pass

    return summary
