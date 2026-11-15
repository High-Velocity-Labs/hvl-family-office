"""
Self-Serve Cloud Household Provisioning & Family Login Activity Tracking.
Provides:
1. `provision_self_serve_household`: Auto-provisions an isolated per-family SQLite vault (`family_id >= 2`)
   for new Google OAuth users in Cloud Mode with zero-knowledge key escrow (`support_access_enabled = 0`).
2. `record_family_login`: Records `families.last_login_at` and `login_count` across `global.db`
   and `families/{family_id}.db` on every authenticated login (no hardcoded `family_id = 1` and no auto-deletion tasks).
3. `get_active_families_summary`: Aggregates monthly (30d) and yearly (365d) active household telemetry for Admin/Ops.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from hvl_common.db import get_db_connection
from hvl_common.db.timestamps import parse_iso_utc
import security


logger = logging.getLogger(__name__)


def record_family_login(
    db_path: Path,
    family_id: int = 0,
    universe: Optional[str] = None,
    now_dt: Optional[datetime] = None,
) -> Optional[str]:
    """
    Records the latest login timestamp (`families.last_login_at`, ISO-8601 UTC) and increments
    `families.login_count` in one statement across `global.db` and `families/{family_id}.db`.
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
            security.init_db(cand)  # last_login_at / login_count exist only from alembic 0010 on
            with get_db_connection(cand, timeout=10.0) as conn:
                cur = conn.execute(
                    "UPDATE families SET last_login_at = ?, login_count = login_count + 1 WHERE family_id = ?",
                    (now_iso, fid),
                )
                conn.commit()
                updated_any = updated_any or cur.rowcount > 0
        except (sqlite3.Error, SQLAlchemyError) as exc:
            logger.warning("Login activity not recorded: %s", exc)
            continue

    return now_iso if updated_any else None


def provision_self_serve_household(
    db_path: Path,
    user_email: str,
    user_name: str = "",
    state: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Atomically provisions a brand-new isolated household (`family_id >= 2`) for a new Google OAuth user:
    - `state` is the starting state of residence (from the visitor's location), or "" so onboarding asks.
    - Allocates the next globally unique `family_id` across `global.db`, `db_path`, and `families/*.db`.
    - Initializes `families/{new_fid}.db` and generates a dedicated 256-bit Fernet `fam_key`.
    - Creates `Family` (`support_access_enabled = 0`, `onboarding_completed = False`, `last_login_at`)
      and `HouseholdProfile` with clean zero-balance defaults.
    - Adds the user as `editor` (`primary`) and mirrors auth metadata to `global.db`.
    """
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
    new_fid = security.allocate_household_id(Path(db_path), 0)
    target_fam_db = resolve_db_path(db_path, family_id=new_fid)
    security.init_db(target_fam_db)
    fam_key = security.get_family_key(target_fam_db, new_fid)
    security.stash_request_vault_fek(new_fid, fam_key)
    enc_dek = security._get_fernet(security.get_or_create_key()).encrypt(fam_key).decode("utf-8")

    now_iso = datetime.now(timezone.utc).isoformat()
    household_name = f"{clean_name}'s Family Office"
    enc_household_name = security.encrypt_string(household_name, key=fam_key)

    for dest_db in security._candidate_family_metadata_dbs(Path(db_path), new_fid, universe=uni):
        try:
            security.init_db(dest_db)
            with get_db_connection(dest_db, timeout=15.0) as conn:
                conn.execute(
                    """
                    INSERT INTO families (
                        family_id, name, primary_state, last_login_at, login_count,
                        encryption_key_enc, support_access_enabled
                    )
                    VALUES (?, ?, ?, ?, 1, ?, 0)
                    ON CONFLICT(family_id) DO UPDATE SET
                        name = excluded.name,
                        primary_state = excluded.primary_state,
                        tax_filing_status = 'MFJ',
                        is_demo = 0,
                        onboarding_completed = 0,
                        onboarding_dismissed = 0,
                        onboarding_wizard_dismissed = 0,
                        overview_widgets = NULL,
                        scenarios_widgets = NULL,
                        collapsed_charts = NULL,
                        last_login_at = excluded.last_login_at,
                        login_count = 1,
                        root_kek_rekeyed = 0,
                        local_passphrase_fek_enc = NULL,
                        portable_vault_fek = NULL,
                        encryption_key_enc = excluded.encryption_key_enc
                    """,
                    (new_fid, enc_household_name, state, now_iso, enc_dek),
                )
                conn.execute(
                    """
                    INSERT INTO household_profile (
                        family_id, state, filing_status, annual_spending, annual_savings,
                        retirement_age, inflation_rate, real_growth_rate
                    ) VALUES (?, ?, 'MFJ', 0.0, 0.0, 60, 0.025, 0.045)
                    ON CONFLICT(family_id) DO NOTHING
                    """,
                    (new_fid, state),
                )
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Invited household profile not written: %s", exc)
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
            except sqlite3.Error as exc:
                logger.warning("User row not mirrored: %s", exc)
                continue

    if user_row is None:
        return None
    user_row["is_new_household"] = True
    return user_row


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
    from services.request_context import get_current_universe

    target_db = Path(db_path) if db_path is not None else config.get_global_db_path(get_current_universe())
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
                   f.last_login_at, f.login_count, COUNT(u.user_id) AS u_cnt
            FROM families f
            LEFT JOIN users u ON f.family_id = u.family_id
            GROUP BY f.family_id, f.created_at, f.support_access_enabled, f.last_login_at, f.login_count
            ORDER BY f.family_id ASC
            """
            if has_users
            else """
            SELECT family_id, created_at, COALESCE(support_access_enabled, 0),
                   last_login_at, login_count, 0 AS u_cnt
            FROM families
            ORDER BY family_id ASC
            """
        )
        for row in conn.execute(q).fetchall():
            fid = int(row[0] or 0)
            created_at = str(row[1] or "")
            sup_enabled = bool(row[2])
            last_login_raw = str(row[3] or "")
            login_count = int(row[4] or 0)
            u_cnt = int(row[5] or 0)
            if u_cnt <= 0 and fid != 1:
                continue

            act_dt = parse_iso_utc(last_login_raw) or parse_iso_utc(created_at)

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

    return summary
