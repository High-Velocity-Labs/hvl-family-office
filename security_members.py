"""
Family member CRUD, blind index email search, and local user resolution.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
from hvl_common.db import get_db_connection


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


def is_family_1_admin_email_hash(db_path: Path, email: str) -> bool:
    """Checks via plaintext blind index (`email_hash`) whether `email` is a primary/admin/editor of Family 1 without decrypting vault columns."""
    clean = (email or "").strip().lower()
    if not clean or not db_path.exists():
        return False
    try:
        from sqlalchemy import or_, select
        from db.models import User
        from db.session import get_orm_session
        import security

        em_hash = security.hash_email(clean)
        with get_orm_session(db_path, family_id=1) as session:
            uid = session.scalar(
                select(User.user_id).where(
                    User.family_id == 1,
                    User.email_hash == em_hash,
                    or_(User.relationship_type == "primary", User.role.in_(("admin", "editor"))),
                )
            )
            return uid is not None
    except Exception:
        return False


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
        except Exception:
            pending_fek_enc = None

    next_uid: Optional[int] = None
    raw_p = Path(db_path._path() if callable(getattr(db_path, "_path", None)) else db_path)
    fam_db: Optional[Path] = None
    try:
        from config import get_global_db_path
        from db.session import resolve_db_path
        from hvl_common.db import get_db_connection

        uni = security._resolve_universe_from_db_path(raw_p)
        glob_db = get_global_db_path(universe=uni)
        fam_db = resolve_db_path(raw_p, family_id=int(family_id or 0))
        max_uid = 0
        for cand_db in (glob_db, fam_db, raw_p):
            if cand_db.exists():
                with get_db_connection(cand_db, timeout=10.0) as conn:
                    r = conn.execute("SELECT COALESCE(MAX(user_id), 0) FROM users").fetchone()
                    if r and int(r[0] or 0) > max_uid:
                        max_uid = int(r[0])
        if max_uid > 0:
            next_uid = max_uid + 1
    except Exception:
        next_uid = None

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

    try:
        from hvl_common.db import get_db_connection

        if fam_db is not None and raw_p.exists() and fam_db.exists() and raw_p.resolve() != fam_db.resolve():
            with get_db_connection(fam_db, timeout=10.0) as sconn, get_db_connection(raw_p, timeout=10.0) as pconn:
                urow = sconn.execute(
                    "SELECT user_id, family_id, name, email, email_hash, birthdate, relationship, role, pending_fek_enc, google_vault_synced FROM users WHERE user_id = ?",
                    (created_uid,),
                ).fetchone()
                if urow:
                    pconn.execute(
                        "INSERT OR REPLACE INTO users (user_id, family_id, name, email, email_hash, birthdate, relationship, role, pending_fek_enc, google_vault_synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        tuple(urow),
                    )
                    pconn.commit()
    except Exception:
        pass

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
        except Exception:
            pending_fek_enc = None

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
    em_hash = security.hash_email(email)

    target_fid = family_id
    target_uid: Optional[int] = None
    if target_fid is None:
        with get_orm_session(db_path, family_id=0) as session:
            row = session.execute(
                select(User.user_id, User.family_id).where(User.email_hash == em_hash)
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
            stmt = stmt.where(User.email_hash == em_hash)
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

    fid = int(family_id) if int(family_id) > 0 else 1
    uid = int(user_id)
    for db_cand in (family_db, global_db):
        if db_cand.exists():
            try:
                with get_db_connection(db_cand) as p_conn:
                    p_row = p_conn.execute(
                        "SELECT name FROM users WHERE family_id = ? AND (relationship = 'primary' OR user_id = ?) AND name IS NOT NULL AND name != '' ORDER BY user_id ASC LIMIT 1",
                        (fid, uid),
                    ).fetchone()
                    if p_row and p_row[0]:
                        cand_name = security.decrypt_field(p_row[0], default="", key=raw_fek).strip()
                        if (
                            cand_name
                            and cand_name not in ("Household Owner", "Owner")
                            and not cand_name.startswith("gAAAAA")
                        ):
                            return cand_name
            except Exception:
                pass
    return None
