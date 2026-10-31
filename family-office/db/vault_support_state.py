"""
Point-in-time snapshot/restore of one household's support-access state (`families` row + each user's escrow
columns) in one database file, so a support-access toggle that spans global.db and families/{id}.db can be
undone on every file when any step of it fails (F-SEC-10).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

from hvl_common.db import get_db_connection


class SupportAccessSnapshot(NamedTuple):
    db_path: Path
    family_row: tuple[Any, ...] | None
    user_rows: tuple[tuple[Any, ...], ...]


def snapshot_support_access_state(db_path: Path, fid: int) -> SupportAccessSnapshot:
    """Captures the support flag, escrowed key, name and per-user escrow/sync columns for `fid`."""
    with get_db_connection(db_path, timeout=10.0) as conn:
        fam = conn.execute(
            "SELECT support_access_enabled, encryption_key_enc, name FROM families WHERE family_id = ?", (fid,)
        ).fetchone()
        users = conn.execute(
            "SELECT user_id, pending_fek_enc, google_vault_synced FROM users WHERE family_id = ?", (fid,)
        ).fetchall()
    return SupportAccessSnapshot(
        Path(db_path), tuple(fam) if fam is not None else None, tuple(tuple(r) for r in users)
    )


def restore_support_access_state(snap: SupportAccessSnapshot, fid: int) -> None:
    """Writes a snapshot back; the inverse of whatever toggle ran since it was taken."""
    with get_db_connection(snap.db_path, timeout=10.0) as conn:
        if snap.family_row is not None:
            conn.execute(
                "UPDATE families SET support_access_enabled = ?, encryption_key_enc = ?, name = ? WHERE family_id = ?",
                (*snap.family_row, fid),
            )
        conn.executemany(
            "UPDATE users SET pending_fek_enc = ?, google_vault_synced = ? WHERE user_id = ? AND family_id = ?",
            [(r[1], r[2], r[0], fid) for r in snap.user_rows],
        )
        conn.commit()
