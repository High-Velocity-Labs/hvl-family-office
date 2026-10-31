"""
Household Support Access persistence: the `support_access_enabled` flag, server FEK escrow on
enable/disable, and keeping the global.db <-> families/{id}.db copies of that state in step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from hvl_common.db import get_db_connection


def read_family_support_flag(conn: Any, fid: int) -> Optional[bool]:
    """Returns `families.support_access_enabled` for `fid`, or None when the household row is missing."""
    row = conn.execute("SELECT support_access_enabled FROM families WHERE family_id = ?", (fid,)).fetchone()
    return None if row is None else bool(int(row[0] or 0))


def read_family_support_flag_at_path(db_path: Any, fid: int) -> Optional[bool]:
    """
    Opens a pooled connection to `db_path` and returns its `support_access_enabled` flag for `fid`.
    Runs during key resolution on every encrypted read, so it releases the connection explicitly.
    """
    conn = get_db_connection(db_path, timeout=30.0)
    try:
        return read_family_support_flag(conn, fid)
    finally:
        conn.close()


def enable_family_support_access_in_db(path_obj: Path, fid: int, enc_dek: str) -> None:
    """Enables `support_access_enabled = 1` and stores `encryption_key_enc` for `fid`."""
    with get_db_connection(path_obj, timeout=30.0) as conn:
        conn.execute(
            "UPDATE families SET support_access_enabled = 1, encryption_key_enc = ? WHERE family_id = ?",
            (enc_dek, fid),
        )
        conn.commit()


def disable_family_support_access_in_db(
    path_obj: Path,
    fid: int,
    enc_dek: Optional[str],
    encrypt_name_fn: Optional[Callable[[str], str]] = None,
) -> None:
    """Disables `support_access_enabled`, clears `encryption_key_enc`, and seeds `pending_fek_enc` on users."""
    with get_db_connection(path_obj, timeout=30.0) as conn:
        if enc_dek is not None:
            conn.execute(
                """
                UPDATE users SET pending_fek_enc = ? WHERE family_id = ?
                AND (pending_fek_enc IS NULL OR pending_fek_enc = '')
                AND COALESCE(google_vault_synced, 0) = 0
                """,
                (enc_dek, fid),
            )
            if encrypt_name_fn is not None:
                fam_row = conn.execute("SELECT name FROM families WHERE family_id = ?", (fid,)).fetchone()
                if fam_row and fam_row[0] and not str(fam_row[0]).startswith("gAAAAA"):
                    enc_name = encrypt_name_fn(str(fam_row[0]))
                    conn.execute("UPDATE families SET name = ? WHERE family_id = ?", (enc_name, fid))
        conn.execute(
            "UPDATE families SET support_access_enabled = 0, encryption_key_enc = NULL WHERE family_id = ?",
            (fid,),
        )
        conn.commit()


def adopt_peer_vault_sync_flags(path_obj: Path, fid: int, peers: list[Path]) -> None:
    """Marks members as Drive-synced (and drops their escrow) in `path_obj` when any peer DB records them as synced."""
    synced_uids: set[int] = set()
    for peer in peers:
        with get_db_connection(peer, timeout=10.0) as pconn:
            synced_uids.update(
                int(r[0]) for r in pconn.execute(
                    "SELECT user_id FROM users WHERE family_id = ? AND COALESCE(google_vault_synced, 0) = 1", (fid,),
                ).fetchall()
            )
    if not synced_uids:
        return
    with get_db_connection(path_obj, timeout=10.0) as conn:
        conn.executemany(
            "UPDATE users SET google_vault_synced = 1, pending_fek_enc = NULL WHERE user_id = ? AND family_id = ?",
            [(uid, fid) for uid in sorted(synced_uids)],
        )
        conn.commit()


def sync_support_access_to_peers(path_obj: Path, fid: int, peers: list[Path]) -> None:
    """
    Mirrors `families` support access state and each user's `pending_fek_enc` (including NULLs)
    from `path_obj` to peer databases, so members who already synced their FEK stay unescrowed.
    """
    for peer in peers:
        with get_db_connection(peer, timeout=10.0) as pconn, get_db_connection(path_obj, timeout=10.0) as sconn:
            row = sconn.execute(
                "SELECT support_access_enabled, encryption_key_enc, name FROM families WHERE family_id = ?",
                (fid,),
            ).fetchone()
            if row:
                pconn.execute(
                    "UPDATE families SET support_access_enabled = ?, encryption_key_enc = ?, name = ? WHERE family_id = ?",
                    (row[0], row[1], row[2], fid),
                )
            u_rows = sconn.execute(
                "SELECT user_id, pending_fek_enc FROM users WHERE family_id = ?",
                (fid,),
            ).fetchall()
            pconn.executemany(
                "UPDATE users SET pending_fek_enc = CASE WHEN COALESCE(google_vault_synced, 0) = 1 THEN NULL ELSE ? END"
                " WHERE user_id = ? AND family_id = ?",
                [(r[1] or None, r[0], fid) for r in u_rows],
            )
            pconn.commit()
