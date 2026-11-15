"""
SQLite repository functions for magic invite tokens: create, list, revoke, and the atomic use claim.
Every write bumps the owning household's `settings.invites` domain after it commits.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from hvl_common.db import get_db_connection


def _bump_invites(cand: Path, fid: int) -> None:
    """Bumps the `settings.invites` domain of the household that owns the invite, after the write has committed."""
    from db.domain_versions import bump_domain_rows

    bump_domain_rows(cand, int(fid), ("settings.invites",))


def _bump_invites_for_code(cand: Path, clean_code: str) -> None:
    row = fetch_invite_token_by_code(cand, clean_code)
    if row is not None:
        _bump_invites(cand, int(row[2]))


def insert_invite_token_in_db(
    cand: Path,
    code: str,
    fid: int,
    clean_email: str,
    norm_type: str,
    norm_role: str,
    clean_label: str,
    norm_max_uses: int,
    expires_iso: str,
    created_iso: str,
    fetch_created: bool = False,
) -> Optional[tuple]:
    """Inserts a magic invite token into `cand` (ensuring parent family row exists) and optionally returns the row."""
    with get_db_connection(cand, timeout=15.0) as conn:
        fam_exists = conn.execute("SELECT 1 FROM families WHERE family_id = ?", (fid,)).fetchone()
        if not fam_exists:
            conn.execute(
                "INSERT INTO families (family_id, name) VALUES (?, ?) ON CONFLICT(family_id) DO NOTHING",
                (fid, f"Family {fid}"),
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
        created = None
        if fetch_created:
            created = conn.execute(
                """
                SELECT invite_id, code, created_by_family_id, created_by_email,
                       invite_type, target_role, label, max_uses, uses_count,
                       expires_at, revoked, created_at
                FROM invite_tokens WHERE code = ?
                """,
                (code,),
            ).fetchone()
    _bump_invites(cand, fid)
    return created


def fetch_invite_tokens_for_family(cand: Path, fid: int) -> List[tuple]:
    """Fetches all `invite_tokens` rows created by `fid` in `cand`."""
    with get_db_connection(cand, timeout=10.0) as conn:
        return conn.execute(
            """
            SELECT invite_id, code, created_by_family_id, created_by_email,
                   invite_type, target_role, label, max_uses, uses_count,
                   expires_at, revoked, created_at
            FROM invite_tokens WHERE created_by_family_id = ? ORDER BY invite_id DESC
            """,
            (fid,),
        ).fetchall()


def revoke_invite_token_in_db(cand: Path, fid: int, clean_code: str) -> bool:
    """Marks `invite_tokens.revoked = 1` for `(clean_code, fid)` in `cand`."""
    with get_db_connection(cand, timeout=10.0) as conn:
        cur = conn.execute(
            "UPDATE invite_tokens SET revoked = 1 WHERE UPPER(code) = ? AND created_by_family_id = ?",
            (clean_code, fid),
        )
        conn.commit()
        revoked = (cur.rowcount or 0) > 0
    if revoked:
        _bump_invites(cand, fid)
    return revoked


def fetch_invite_token_by_code(cand: Path, clean_code: str) -> Optional[tuple]:
    """Fetches a single `invite_tokens` row matching `UPPER(code) = clean_code`."""
    with get_db_connection(cand, timeout=10.0) as conn:
        return conn.execute(
            """
            SELECT invite_id, code, created_by_family_id, created_by_email,
                   invite_type, target_role, label, max_uses, uses_count,
                   expires_at, revoked, created_at
            FROM invite_tokens WHERE UPPER(code) = ?
            """,
            (clean_code,),
        ).fetchone()


def claim_invite_token_use(cand: Path, clean_code: str, now_iso: str) -> bool:
    """Atomically consumes one use of `clean_code` in `cand`; False when used up, revoked, expired or absent."""
    with get_db_connection(cand, timeout=15.0) as conn:
        cur = conn.execute(
            "UPDATE invite_tokens SET uses_count = uses_count + 1 "
            "WHERE UPPER(code) = ? AND uses_count < max_uses AND revoked = 0 AND expires_at > ?",
            (clean_code, now_iso),
        )
        conn.commit()
        claimed = (cur.rowcount or 0) == 1
    if claimed:
        _bump_invites_for_code(cand, clean_code)
    return claimed


def release_invite_token_use(cand: Path, clean_code: str) -> None:
    """Gives back one use claimed by `claim_invite_token_use` when provisioning failed."""
    with get_db_connection(cand, timeout=15.0) as conn:
        conn.execute(
            "UPDATE invite_tokens SET uses_count = uses_count - 1 WHERE UPPER(code) = ? AND uses_count > 0",
            (clean_code,),
        )
        conn.commit()
    _bump_invites_for_code(cand, clean_code)


def mirror_invite_token_use(cand: Path, clean_code: str) -> None:
    """Copies a claimed use onto a mirror copy of the invite, never past `max_uses`."""
    with get_db_connection(cand, timeout=15.0) as conn:
        conn.execute(
            "UPDATE invite_tokens SET uses_count = uses_count + 1 WHERE UPPER(code) = ? AND uses_count < max_uses",
            (clean_code,),
        )
        conn.commit()
    _bump_invites_for_code(cand, clean_code)
