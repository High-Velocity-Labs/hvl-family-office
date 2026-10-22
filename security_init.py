"""
Family metadata CRUD, universe resolution, and invited household provisioning.
"""

from __future__ import annotations
import json
from pathlib import Path
import sqlite3
from typing import Optional
from hvl_common.db import get_db_connection


def _resolve_universe_from_db_path(db_path: Path, universe: Optional[str] = None) -> str:
    """Resolves universe string from database path."""
    from config import normalize_universe
    if universe:
        return normalize_universe(universe)
    parts = [pt.lower() for pt in Path(db_path).parts]
    for u in ("demo", "sandbox", "test", "public"):
        if u in parts:
            return u
    p_name = Path(db_path).name.lower()
    if "_beta" in p_name or "_demo" in p_name or "families_beta" in parts:
        return "demo"
    if "_sandbox" in p_name or "families_sandbox" in parts:
        return "sandbox"
    if "_test" in p_name or "families_test" in parts:
        return "test"
    try:
        from routes.helpers import get_current_universe
        return normalize_universe(get_current_universe())
    except Exception:
        return "public"


def _candidate_family_metadata_dbs(db_path: Path, family_id: int, universe: Optional[str] = None) -> list[Path]:
    """Returns candidate database paths where family metadata may reside."""
    from config import get_db_path_for_universe, get_family_db_path, get_global_db_path
    from db.session import resolve_db_path

    fid = int(family_id or 0)
    uni = _resolve_universe_from_db_path(db_path, universe=universe)
    resolved = resolve_db_path(db_path, family_id=fid)
    fam_db = get_family_db_path(fid, universe=uni) if fid > 0 else resolved
    candidates: list[Path] = []
    for p in (resolved, fam_db, get_global_db_path(universe=uni), Path(db_path), get_db_path_for_universe(uni)):
        try:
            rp = Path(p)
            if rp not in candidates and not any(
                rp.resolve() == c.resolve() for c in candidates if c.exists() and rp.exists()
            ):
                candidates.append(rp)
        except Exception:
            if Path(p) not in candidates:
                candidates.append(Path(p))
    return candidates


def get_family(db_path: Path, family_id: int) -> Optional[dict]:
    """Retrieves family group metadata and settings, strictly scoped by family_id."""
    from db.models import Family
    from db.session import get_orm_session
    import security

    security.init_db(db_path)
    try:
        with get_orm_session(db_path, family_id=family_id) as session:
            fam = session.get(Family, family_id)
            if not fam:
                return None
            try:
                parsed_settings = json.loads(fam.settings) if fam.settings else {}
            except Exception:
                parsed_settings = {}
            return {
                "family_id": fam.family_id,
                "name": fam.name or "Family Office",
                "settings": parsed_settings,
                "deletion_status": security._parse_deletion_status_from_settings(parsed_settings),
                "support_access_enabled": bool(fam.support_access_enabled),
                "created_at": fam.created_at,
            }
    except PermissionError:
        with get_db_connection(db_path, timeout=30.0) as conn:
            row = conn.execute(
                "SELECT family_id, settings, support_access_enabled, created_at FROM families WHERE family_id = ?",
                (int(family_id),),
            ).fetchone()
            if not row:
                return None
            try:
                parsed_settings = json.loads(row[1]) if row[1] else {}
            except Exception:
                parsed_settings = {}
            return {
                "family_id": int(row[0]),
                "name": "Family Office",
                "settings": parsed_settings,
                "deletion_status": security._parse_deletion_status_from_settings(parsed_settings),
                "support_access_enabled": bool(int(row[2] or 0)),
                "created_at": row[3],
            }


def update_family(
    db_path: Path,
    family_id: int,
    name: str = "",
    settings: Optional[dict] = None,
    support_access_enabled: Optional[bool] = None,
) -> bool:
    """Updates family name, optional settings, and optional support_access_enabled flag."""
    from db.models import Family
    from db.session import get_orm_session
    import security

    if name or settings is not None:
        with get_orm_session(db_path, family_id=family_id, commit=True) as session:
            fam = session.get(Family, family_id)
            if fam is not None:
                if name:
                    fam.name = name
                if settings is not None:
                    merged_settings = dict(settings)
                    try:
                        existing_s = json.loads(fam.settings) if fam.settings else {}
                    except Exception:
                        existing_s = {}
                    for del_key in ("deletion_scheduled_at", "deletion_purge_after", "deletion_requested_by"):
                        if del_key in existing_s and del_key not in merged_settings:
                            merged_settings[del_key] = existing_s[del_key]
                    fam.settings = json.dumps(merged_settings)
                if support_access_enabled is not None and bool(support_access_enabled):
                    fam.support_access_enabled = 1
    if support_access_enabled is not None:
        security.set_family_support_access(db_path, family_id=int(family_id), enabled=bool(support_access_enabled))
    return True


def _provision_invited_household(
    db_path: Path,
    new_fid: int,
    clean_name: str,
    clean_email: str,
    uni: str,
) -> int:
    """Provisions a new household database, key, profile, and primary member."""
    from db.session import resolve_db_path
    import security

    target_fam_db = resolve_db_path(db_path, family_id=new_fid)
    security.init_db(target_fam_db)
    fam_key = security.get_family_key(target_fam_db, new_fid)
    security.stash_request_vault_fek(new_fid, fam_key)
    enc_dek = security._get_fernet(security.get_or_create_key()).encrypt(fam_key).decode("utf-8")

    household_name = f"{clean_name}'s Family Office"
    enc_household_name = security.encrypt_string(household_name, key=fam_key)
    initial_settings = json.dumps({
        "primary_state": "WA",
        "tax_filing_status": "MFJ",
        "onboarding_completed": False,
        "onboarding_dismissed": False,
    })

    for dest_db in _candidate_family_metadata_dbs(Path(db_path), new_fid, universe=uni):
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
    for dest_db in _candidate_family_metadata_dbs(Path(db_path), new_fid, universe=uni):
        if dest_db.exists() and dest_db.resolve() != target_fam_db.resolve():
            try:
                with get_db_connection(target_fam_db, timeout=10.0) as sconn, get_db_connection(dest_db, timeout=10.0) as dconn:
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
            except Exception:
                continue
    return uid


def _join_invited_household(
    db_path: Path,
    target_fid: int,
    clean_name: str,
    clean_email: str,
    target_role: str,
    uni: str,
) -> tuple[int, str]:
    """Adds an invited user to an existing household."""
    from db.session import resolve_db_path
    import security

    assigned_role = "editor" if str(target_role or "").strip().lower() == "editor" else "viewer"
    rel = "spouse" if assigned_role == "editor" else "relative"
    target_fam_db = resolve_db_path(db_path, family_id=target_fid)
    security.init_db(target_fam_db)

    try:
        fam_key = security.get_family_key(target_fam_db, target_fid)
        security.stash_request_vault_fek(target_fid, fam_key)
    except PermissionError:
        for cand in _candidate_family_metadata_dbs(Path(db_path), target_fid, universe=uni):
            if not cand.exists():
                continue
            try:
                with get_db_connection(cand, timeout=10.0) as conn:
                    p_row = conn.execute(
                        "SELECT pending_fek_enc FROM users WHERE family_id = ? AND pending_fek_enc IS NOT NULL AND pending_fek_enc != '' LIMIT 1",
                        (target_fid,),
                    ).fetchone()
                    if p_row and p_row[0]:
                        dek = security._get_fernet(security.get_or_create_key()).decrypt(str(p_row[0]).encode("utf-8"))
                        security.stash_request_vault_fek(target_fid, dek)
                        break
            except Exception:
                continue

    existing = security.find_user_by_email(target_fam_db, clean_email, family_id=target_fid)
    if existing:
        return int(existing["user_id"]), assigned_role

    uid = security.add_family_member(
        target_fam_db,
        family_id=target_fid,
        name=clean_name,
        email=clean_email,
        relationship=rel,
        role=assigned_role,
    )
    try:
        from db.notifications import emit_family_notification
        emit_family_notification(
            target_fam_db, family_id=target_fid, category="invite",
            dedupe_key=f"invite:accepted:{clean_email}", deep_link="/?settings=members",
            title="New household member joined",
            body=f"{clean_name or clean_email} accepted your household invite ({assigned_role}).",
            sender_email=clean_email, sender_name=clean_name,
        )
    except Exception:
        pass
    for dest_db in _candidate_family_metadata_dbs(Path(db_path), target_fid, universe=uni):
        if dest_db.exists() and dest_db.resolve() != target_fam_db.resolve():
            try:
                with get_db_connection(target_fam_db, timeout=10.0) as sconn, get_db_connection(dest_db, timeout=10.0) as dconn:
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
            except Exception:
                continue

    return uid, assigned_role
