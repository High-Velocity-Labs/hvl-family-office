"""
Magic invite tokens and self-service household/member provisioning.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import secrets
from db.security_repo import DatabaseError
from typing import Optional

from db.invite_repo import (
    fetch_invite_token_by_code,
    fetch_invite_tokens_for_family,
    claim_invite_token_use,
    insert_invite_token_in_db,
    mirror_invite_token_use,
    release_invite_token_use,
    revoke_invite_token_in_db,
)

logger = logging.getLogger(__name__)

_INVITE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _generate_invite_code() -> str:
    """Generates a cryptographically random `FO-XXXX-XXXX` invite code."""
    part1 = "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(4))
    part2 = "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(4))
    return f"FO-{part1}-{part2}"


def _format_invite_row(row: tuple) -> dict:
    """Formats a raw `invite_tokens` tuple into a structured invite dictionary."""
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
    except ValueError:
        is_expired = True  # an unreadable expiry is never treated as still valid

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
    """Returns candidate database paths where `invite_tokens` may be stored."""
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
        except OSError:  # resolve() on an unreadable path: keep the candidate unresolved
            if Path(p) not in cands:
                cands.append(Path(p))
    return cands


def allocate_household_id(db_path: Path, creator_family_id: int) -> int:
    """Allocates a new household id for `db_path`'s universe; `creator_family_id` is 0 when there is no inviter."""
    import security
    from config import get_global_db_path, get_universe_dir
    from db.family_id_allocator import allocate_new_family_id

    uni = security._resolve_universe_from_db_path(Path(db_path))
    scan_dbs = _invite_candidate_dbs(Path(db_path), int(creator_family_id or 0))
    global_db = get_global_db_path(universe=uni)
    security.init_db(global_db)
    for cand in scan_dbs:
        if cand.exists():
            security.init_db(cand)
    return allocate_new_family_id(
        global_db, scan_dbs, Path(get_universe_dir(uni)) / "families"
    )


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
            row = insert_invite_token_in_db(
                cand,
                code,
                fid,
                clean_email,
                norm_type,
                norm_role,
                clean_label,
                norm_max_uses,
                expires_iso,
                created_iso,
                fetch_created=(created_row is None),
            )
            if created_row is None and row is not None:
                created_row = row
        except DatabaseError as exc:
            logger.warning("Invite %s not stored in %s: %s", code, cand, exc)
            continue

    if created_row is None:
        # A code no database holds can never be redeemed: report that, never a made-up invite.
        raise RuntimeError("The invite link could not be stored in any database.")
    return _format_invite_row(created_row)


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
            for r in fetch_invite_tokens_for_family(cand, fid):
                item = _format_invite_row(r)
                c = item["code"]
                if c not in by_code:
                    by_code[c] = item
                elif item["uses_count"] > by_code[c]["uses_count"] or (item["revoked"] and not by_code[c]["revoked"]):
                    by_code[c] = item
        except DatabaseError as exc:
            logger.warning("Invites of household %s not readable from %s: %s", fid, cand, exc)
            continue

    return sorted(by_code.values(), key=lambda x: (x.get("created_at") or "", x.get("invite_id") or 0), reverse=True)


def revoke_invite_token(db_path: Path, family_id: int, code: str) -> bool:
    """Revokes an invite token created by family_id across all candidate DBs."""
    import security

    fid = int(family_id or 0)
    clean_code = (code or "").strip().upper()
    if fid <= 0 or not clean_code:
        return False

    # The authoritative copy (the one redemption claims against) is revoked first and its failure
    # propagates; mirrors are best-effort afterwards.
    cands = [c for c in _invite_candidate_dbs(Path(db_path), fid) if c.exists()]
    for c in cands:
        security.init_db(c)
    authority = next((c for c in cands if fetch_invite_token_by_code(c, clean_code)), None)
    if authority is None:
        return False
    if not revoke_invite_token_in_db(authority, fid, clean_code):
        return False
    for cand in cands:
        if cand != authority:
            try:
                security.init_db(cand)
                revoke_invite_token_in_db(cand, fid, clean_code)
            except DatabaseError as exc:
                logger.warning("Could not mirror invite revocation to %s: %s", cand, exc)
    return True


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
            row = fetch_invite_token_by_code(cand, clean_code)
            if row:
                item = _format_invite_row(row)
                if matched is None or item["uses_count"] > matched["uses_count"] or item["revoked"]:
                    matched = item
        except DatabaseError as exc:
            logger.warning("Invite lookup failed in %s: %s", cand, exc)
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
    home_state: str = "",
) -> Optional[dict]:
    """Atomically validates and redeems a Magic Invite token for user_email (`home_state` starts a new household's state)."""
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
    creator_fid = int(token.get("created_by_family_id") or 0)
    if creator_fid <= 0:
        return None
    uni = security._resolve_universe_from_db_path(Path(db_path))

    # Consume the use first, atomically, on the authoritative copy (global DB first). A used-up,
    # revoked or expired invite is refused before anything is provisioned.
    cands = [c for c in _invite_candidate_dbs(Path(db_path), creator_fid) if c.exists()]
    claim_db = next((c for c in cands if fetch_invite_token_by_code(c, clean_code)), None)
    if claim_db is None or not claim_invite_token_use(claim_db, clean_code, datetime.now(timezone.utc).isoformat()):
        return None

    new_fid: Optional[int] = None
    try:
        if invite_type == "new_household":
            new_fid = allocate_household_id(Path(db_path), creator_fid)
            uid = security._provision_invited_household(db_path, new_fid, clean_name, clean_email, uni, state=home_state)
            result_fid = new_fid
            assigned_role = "editor"
            is_new_household = True
        else:
            uid, assigned_role = security._join_invited_household(
                db_path, creator_fid, clean_name, clean_email, str(token.get("target_role") or "viewer"), uni
            )
            result_fid = creator_fid
            is_new_household = False
    except BaseException:
        # Undo any partial household first; hand the use back only once nothing of it remains,
        # otherwise a retry would create a second household.
        if new_fid is not None:
            try:
                security.permanently_delete_family(Path(db_path), new_fid, universe=uni)
            except Exception:
                logger.exception("Could not undo partially provisioned household %s; invite use not released", new_fid)
                raise
        release_invite_token_use(claim_db, clean_code)
        raise

    for cand in cands:
        if cand != claim_db:
            try:
                mirror_invite_token_use(cand, clean_code)
            except DatabaseError as exc:
                logger.warning("Invite use not mirrored into %s: %s", cand, exc)
                continue

    return {
        "family_id": result_fid,
        "user_id": uid,
        "role": assigned_role,
        "is_new_household": is_new_household,
        "invite_type": invite_type,
        "code": clean_code,
    }
