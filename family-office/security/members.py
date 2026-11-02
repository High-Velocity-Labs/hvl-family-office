"""
Family member CRUD, blind index email search, and local user resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from db.security_repo import DatabaseError
from typing import Optional

from db.security_repo import (
    fetch_local_primary_user_encrypted_name,
    fetch_max_user_id_across_dbs,
    sync_user_row_between_dbs,
)

logger = logging.getLogger(__name__)


def get_family_members(db_path: Path, family_id: int) -> list[dict]:
    """Retrieves all members of a family group with decrypted sensitive fields, strictly scoped by family_id."""
    from sqlalchemy import select
    from db.models import User
    from db.session import get_orm_session
    import security

    security.init_db(db_path)
    with get_orm_session(db_path, family_id=family_id) as session:
        rows = session.scalars(
            select(User)
            .where(User.family_id == family_id)
            .order_by(User.user_id.asc())
        ).all()
        return [u.to_dict() for u in rows]


def add_family_member(
    db_path: Path,
    family_id: int,
    name: str,
    email: str = "",
    birthdate: str = "",
    relationship: str = "child",
    role: str = "viewer",
) -> int:
    """Adds a new member to a family group with encrypted name/email and blind index hash."""
    import config
    from db.models import User
    from db.session import get_orm_session
    import security

    if family_id and int(family_id) > 0:
        existing_members = get_family_members(db_path, family_id=int(family_id))
        if len(existing_members) >= config.MAX_HOUSEHOLD_MEMBERS:
            raise ValueError(f"Maximum of {config.MAX_HOUSEHOLD_MEMBERS} household members reached.")

    raw_email = (email or "").strip().lower()
    em_hash = security.hash_email(raw_email)
    pending_fek_enc: Optional[str] = None
    if raw_email and family_id and int(family_id) > 0:
        try:
            fam_key = security.get_family_key(db_path, int(family_id))
            pending_fek_enc = security._get_fernet(security.get_or_create_key()).encrypt(fam_key).decode("utf-8")
        except PermissionError:
            pending_fek_enc = None  # a locked vault has no key to hand the new member yet

    next_uid: Optional[int] = None
    raw_p = Path(db_path._path() if callable(getattr(db_path, "_path", None)) else db_path)
    from config import get_global_db_path
    from db.session import resolve_db_path

    uni = security._resolve_universe_from_db_path(raw_p)
    glob_db = get_global_db_path(universe=uni)
    fam_db = resolve_db_path(raw_p, family_id=int(family_id or 0))
    max_uid = fetch_max_user_id_across_dbs((glob_db, fam_db, raw_p))
    if max_uid > 0:
        next_uid = max_uid + 1

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        user_kwargs = dict(
            family_id=family_id,
            name=name.strip(),
            email=raw_email,
            email_hash=em_hash,
            birthdate=birthdate.strip(),
            relationship_type=relationship,
            role=role,
            pending_fek_enc=pending_fek_enc,
            google_vault_synced=0,
        )
        if next_uid is not None:
            user_kwargs["user_id"] = next_uid
        user = User(**user_kwargs)
        session.add(user)
        session.flush()
        created_uid = int(user.user_id)

    if raw_p.exists() and fam_db.exists() and raw_p.resolve() != fam_db.resolve():
        try:
            sync_user_row_between_dbs(fam_db, raw_p, created_uid, mode="core")
        except DatabaseError as exc:
            logger.warning("User %s not mirrored into %s: %s", created_uid, raw_p, exc)

    return created_uid


def update_family_member(
    db_path: Path,
    family_id: int,
    user_id: int,
    name: str,
    email: str = "",
    birthdate: str = "",
    relationship: str = "child",
    role: str = "viewer",
) -> bool:
    """Updates an existing member's information strictly scoped by family_id with encrypted name/email."""
    from sqlalchemy import select
    from db.models import User
    from db.session import get_orm_session
    import security

    raw_email = (email or "").strip().lower()
    em_hash = security.hash_email(raw_email)
    pending_fek_enc: Optional[str] = None
    if raw_email and family_id and int(family_id) > 0:
        try:
            fam_key = security.get_family_key(db_path, int(family_id))
            pending_fek_enc = security._get_fernet(security.get_or_create_key()).encrypt(fam_key).decode("utf-8")
        except PermissionError:
            pending_fek_enc = None  # a locked vault has no key to hand the member yet

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        user = session.scalars(
            select(User).where(User.family_id == family_id, User.user_id == user_id)
        ).first()
        if user is not None:
            old_email = (user.email or "").strip().lower()
            user.name = name.strip()
            user.email = raw_email
            user.email_hash = em_hash
            user.birthdate = birthdate.strip()
            user.relationship_type = relationship
            user.role = role
            if raw_email != old_email:
                user.google_vault_synced = 0
                user.pending_fek_enc = pending_fek_enc
            elif raw_email and int(user.google_vault_synced or 0) == 0 and pending_fek_enc:
                user.pending_fek_enc = pending_fek_enc
    return True


def delete_family_member(db_path: Path, family_id: int, user_id: int) -> bool:
    """Deletes a member from the family group strictly scoped by family_id."""
    from sqlalchemy import delete
    from db.models import User
    from db.session import get_orm_session

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        session.execute(
            delete(User).where(User.family_id == family_id, User.user_id == user_id)
        )
    return True


def find_user_by_email(db_path: Path, email: str, family_id: Optional[int] = None) -> Optional[dict]:
    """Finds a user by blind index email hash, returning decrypted fields."""
    if not db_path.exists() or not email:
        return None
    from sqlalchemy import select
    from db.models import User
    from db.session import get_orm_session
    import security

    security.init_db(db_path)
    em_hashes = security.email_hash_candidates(email)

    target_fid = family_id
    target_uid: Optional[int] = None
    if target_fid is None:
        with get_orm_session(db_path, family_id=0) as session:
            row = session.execute(
                select(User.user_id, User.family_id).where(User.email_hash.in_(em_hashes))
            ).first()
            if not row:
                return None
            target_uid = int(row[0])
            target_fid = int(row[1])

    with get_orm_session(db_path, family_id=int(target_fid or 0)) as session:
        stmt = select(User).where(User.family_id == int(target_fid or 0))
        if target_uid is not None:
            stmt = stmt.where(User.user_id == target_uid)
        else:
            stmt = stmt.where(User.email_hash.in_(em_hashes))
        user = session.scalars(stmt).first()
        if not user:
            return None
        return {
            "user_id": user.user_id,
            "family_id": user.family_id,
            "name": user.name or "",
            "email": user.email or "",
            "birthdate": user.birthdate or "",
            "relationship": user.relationship_type or "child",
            "role": user.role or "viewer",
        }


def resolve_local_user_name(
    family_db: Path,
    global_db: Path,
    family_id: int,
    user_id: int,
    raw_fek: bytes,
) -> Optional[str]:
    """Resolves and decrypts the primary user's display name from family or global DB."""
    import security

    from config import LOCAL_HOUSEHOLD_FAMILY_ID

    fid = int(family_id) if int(family_id) > 0 else LOCAL_HOUSEHOLD_FAMILY_ID
    uid = int(user_id)
    for db_cand in (family_db, global_db):
        if db_cand.exists():
            try:
                enc_name = fetch_local_primary_user_encrypted_name(db_cand, fid, uid)
                if enc_name:
                    cand_name = security.decrypt_field(enc_name, default="", key=raw_fek).strip()
                    if (
                        cand_name
                        and cand_name not in ("Household Owner", "Owner")
                        and not cand_name.startswith("gAAAAA")
                    ):
                        return cand_name
            except DatabaseError as exc:
                logger.warning("Primary user name not readable from %s: %s", db_cand, exc)
    return None
