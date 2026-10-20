"""
Magic invite tokens and self-service household/member provisioning.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
from typing import Optional
from hvl_common.db import get_db_connection

_INVITE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _generate_invite_code() -> str:
    part1 = "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(4))
    part2 = "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(4))
    return f"FO-{part1}-{part2}"


def _format_invite_row(row: tuple) -> dict:
    invite_id, code, created_by_fid, created_by_email, invite_type, target_role, label, max_uses, uses_count, expires_at, revoked, created_at = row
    max_u = int(max_uses or 1)
    uses_c = int(uses_count or 0)
    is_revoked = bool(int(revoked or 0))
    is_expired = False
    try:
        exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        is_expired = exp_dt <= datetime.now(timezone.utc)
    except Exception:
        is_expired = False

    if is_revoked:
        status = "revoked"
    elif uses_c >= max_u:
        status = "redeemed"
    elif is_expired:
        status = "expired"
    else:
        status = "active"

    return {
        "invite_id": int(invite_id),
        "code": str(code),
        "created_by_family_id": int(created_by_fid),
        "created_by_email": str(created_by_email or ""),
        "invite_type": str(invite_type or "new_household"),
        "target_role": str(target_role or "editor"),
        "label": str(label or ""),
        "max_uses": max_u,
        "uses_count": uses_c,
        "expires_at": str(expires_at or ""),
        "revoked": is_revoked,
        "is_expired": is_expired,
        "status": status,
        "created_at": str(created_at or ""),
    }


def _invite_candidate_dbs(db_path: Path, family_id: int = 0) -> list[Path]:
    import security
    from config import get_global_db_path
    from db.session import resolve_db_path

    fid = int(family_id or 0)
    uni = security._resolve_universe_from_db_path(Path(db_path))
    glob_db = get_global_db_path(universe=uni)
    resolved_zero = resolve_db_path(db_path, family_id=0)
    cands: list[Path] = []
    for p in (
        [glob_db, resolved_zero, Path(db_path)]
        + (security._candidate_family_metadata_dbs(Path(db_path), fid, universe=uni) if fid > 0 else [])
    ):
        try:
            rp = Path(p)
            if rp not in cands and not any(
                rp.exists() and c.exists() and rp.resolve() == c.resolve() for c in cands
            ):
                cands.append(rp)
        except Exception:
            if Path(p) not in cands:
                cands.append(Path(p))
    return cands


def create_invite_token(
    db_path: Path,
    family_id: int,
    created_by_email: str = "",
    invite_type: str = "new_household",
    target_role: str = "editor",
    label: str = "",
    max_uses: int = 1,
    expires_days: int = 14,
) -> dict:
    """Creates a Magic Invite token (FO-XXXX-XXXX) and synchronizes it across global and family DBs."""
    import config
    import security

    fid = int(family_id or 0)
    if fid <= 0:
        raise ValueError("Valid family_id > 0 is required to create an invite token.")

    active_invites = [inv for inv in list_invite_tokens(db_path, fid) if inv.get("status") == "active"]
    if len(active_invites) >= config.MAX_ACTIVE_INVITES_PER_FAMILY:
        raise ValueError(f"Maximum of {config.MAX_ACTIVE_INVITES_PER_FAMILY} active invite links reached.")

    norm_type = (
        "join_household"
        if str(invite_type or "").strip().lower() == "join_household"
        else "new_household"
    )
    if norm_type == "new_household":
        norm_role = "editor"
    else:
        existing_members = security.get_family_members(db_path, family_id=fid)
        if len(existing_members) >= config.MAX_HOUSEHOLD_MEMBERS:
            raise ValueError(f"Maximum of {config.MAX_HOUSEHOLD_MEMBERS} household members reached.")
        norm_role = "editor" if str(target_role or "").strip().lower() == "editor" else "viewer"

    clean_label = (label or "").strip()[:100]
    clean_email = (created_by_email or "").strip().lower()[:120]
    max_cap = 20 if norm_type == "join_household" else 100
    norm_max_uses = max(1, min(max_cap, int(max_uses or 1)))
    norm_days = max(1, min(365, int(expires_days or 14)))
    now_dt = datetime.now(timezone.utc)
    expires_iso = (now_dt + timedelta(days=norm_days)).isoformat()
    created_iso = now_dt.isoformat()

    code = _generate_invite_code()
    cands = _invite_candidate_dbs(Path(db_path), fid)
    created_row: Optional[tuple] = None

    for cand in cands:
        try:
            security.init_db(cand)
            with get_db_connection(cand, timeout=15.0) as conn:
                fam_exists = conn.execute("SELECT 1 FROM families WHERE family_id = ?", (fid,)).fetchone()
                if not fam_exists:
                    conn.execute(
                        "INSERT INTO families (family_id, name, settings) VALUES (?, ?, ?) ON CONFLICT(family_id) DO NOTHING",
                        (fid, f"Family {fid}", '{"primary_state": "WA", "tax_filing_status": "MFJ"}'),
                    )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO invite_tokens (
                        code, created_by_family_id, created_by_email, invite_type,
                        target_role, label, max_uses, uses_count, expires_at, revoked, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?)
                    """,
                    (code, fid, clean_email, norm_type, norm_role, clean_label, norm_max_uses, expires_iso, created_iso),
                )
                conn.commit()
                if created_row is None:
                    created_row = conn.execute(
                        """
                        SELECT invite_id, code, created_by_family_id, created_by_email,
                               invite_type, target_role, label, max_uses, uses_count,
                               expires_at, revoked, created_at
                        FROM invite_tokens WHERE code = ?
                        """,
                        (code,),
                    ).fetchone()
        except Exception:
            continue

    if created_row is not None:
        return _format_invite_row(created_row)

    return {
        "invite_id": 1, "code": code, "created_by_family_id": fid, "created_by_email": clean_email,
        "invite_type": norm_type, "target_role": norm_role, "label": clean_label,
        "max_uses": norm_max_uses, "uses_count": 0, "expires_at": expires_iso,
        "revoked": False, "is_expired": False, "status": "active", "created_at": created_iso,
    }


def list_invite_tokens(db_path: Path, family_id: int) -> list[dict]:
    """Lists all Magic Invite tokens created by family_id, merging latest usage counts."""
    import security

    fid = int(family_id or 0)
    if fid <= 0:
        return []

    by_code: dict[str, dict] = {}
    for cand in _invite_candidate_dbs(Path(db_path), fid):
        if not cand.exists():
            continue
        try:
            security.init_db(cand)
            with get_db_connection(cand, timeout=10.0) as conn:
                rows = conn.execute(
                    """
                    SELECT invite_id, code, created_by_family_id, created_by_email,
                           invite_type, target_role, label, max_uses, uses_count,
                           expires_at, revoked, created_at
                    FROM invite_tokens WHERE created_by_family_id = ? ORDER BY invite_id DESC
                    """,
                    (fid,),
                ).fetchall()
                for r in rows:
                    item = _format_invite_row(r)
                    c = item["code"]
                    if c not in by_code:
                        by_code[c] = item
                    elif item["uses_count"] > by_code[c]["uses_count"] or (item["revoked"] and not by_code[c]["revoked"]):
                        by_code[c] = item
        except Exception:
            continue

    return sorted(by_code.values(), key=lambda x: (x.get("created_at") or "", x.get("invite_id") or 0), reverse=True)


def revoke_invite_token(db_path: Path, family_id: int, code: str) -> bool:
    """Revokes an invite token created by family_id across all candidate DBs."""
    import security

    fid = int(family_id or 0)
    clean_code = (code or "").strip().upper()
    if fid <= 0 or not clean_code:
        return False

    updated = False
    for cand in _invite_candidate_dbs(Path(db_path), fid):
        if not cand.exists():
            continue
        try:
            security.init_db(cand)
            with get_db_connection(cand, timeout=10.0) as conn:
                cur = conn.execute(
                    "UPDATE invite_tokens SET revoked = 1 WHERE UPPER(code) = ? AND created_by_family_id = ?",
                    (clean_code, fid),
                )
                conn.commit()
                if (cur.rowcount or 0) > 0:
                    updated = True
        except Exception:
            continue
    return updated


def validate_invite_token(db_path: Path, code: str) -> Optional[dict]:
    """Validates a Magic Invite token code (FO-XXXX-XXXX)."""
    import security

    clean_code = (code or "").strip().upper()
    if not clean_code:
        return None

    matched: Optional[dict] = None
    for cand in _invite_candidate_dbs(Path(db_path), 0):
        if not cand.exists():
            continue
        try:
            security.init_db(cand)
            with get_db_connection(cand, timeout=10.0) as conn:
                row = conn.execute(
                    """
                    SELECT invite_id, code, created_by_family_id, created_by_email,
                           invite_type, target_role, label, max_uses, uses_count,
                           expires_at, revoked, created_at
                    FROM invite_tokens WHERE UPPER(code) = ?
                    """,
                    (clean_code,),
                ).fetchone()
                if row:
                    item = _format_invite_row(row)
                    if matched is None or item["uses_count"] > matched["uses_count"] or item["revoked"]:
                        matched = item
        except Exception:
            continue

    if not matched:
        return None
    if matched.get("revoked") or matched.get("is_expired"):
        return None
    if int(matched.get("uses_count") or 0) >= int(matched.get("max_uses") or 1):
        return None

    matched["valid"] = True
    if matched.get("invite_type") == "join_household":
        creator_fid = int(matched.get("created_by_family_id") or 0)
        fam = security.get_family(Path(db_path), creator_fid) if creator_fid > 0 else None
        matched["family_name"] = (fam or {}).get("name") or "Household Vault"
    else:
        matched["family_name"] = "New Isolated Household Vault"
    return matched


def redeem_invite_token(
    db_path: Path,
    code: str,
    user_email: str,
    user_name: str = "",
) -> Optional[dict]:
    """Atomically validates and redeems a Magic Invite token for user_email."""
    from config import get_family_db_path
    import security

    token = validate_invite_token(db_path, code)
    if not token:
        return None

    clean_email = (user_email or "").strip().lower()
    if not clean_email:
        return None

    clean_name = (user_name or "").strip()
    if not clean_name:
        clean_name = clean_email.split("@")[0].replace(".", " ").replace("_", " ").title() or "Household Member"

    clean_code = str(token["code"]).strip().upper()
    invite_type = str(token.get("invite_type") or "new_household").strip().lower()
    creator_fid = int(token.get("created_by_family_id") or 1)
    uni = security._resolve_universe_from_db_path(Path(db_path))

    if invite_type == "new_household":
        max_fid = 1
        for s_db in _invite_candidate_dbs(Path(db_path), creator_fid):
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
                    if f_file.stem.isdigit() and int(f_file.stem) > max_fid:
                        max_fid = int(f_file.stem)
        except Exception:
            pass

        new_fid = max(max_fid + 1, 2)
        uid = security._provision_invited_household(db_path, new_fid, clean_name, clean_email, uni)
        result_fid = new_fid
        assigned_role = "editor"
        is_new_household = True
    else:
        target_fid = creator_fid
        if target_fid <= 0:
            return None
        uid, assigned_role = security._join_invited_household(
            db_path, target_fid, clean_name, clean_email, str(token.get("target_role") or "viewer"), uni
        )
        result_fid = target_fid
        is_new_household = False

    for cand in _invite_candidate_dbs(Path(db_path), creator_fid):
        if cand.exists():
            try:
                with get_db_connection(cand, timeout=10.0) as conn:
                    conn.execute("UPDATE invite_tokens SET uses_count = uses_count + 1 WHERE UPPER(code) = ?", (clean_code,))
                    conn.commit()
            except Exception:
                continue

    return {
        "family_id": result_fid,
        "user_id": uid,
        "role": assigned_role,
        "is_new_household": is_new_household,
        "invite_type": invite_type,
        "code": clean_code,
    }
