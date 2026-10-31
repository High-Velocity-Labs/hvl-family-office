"""
Household `family_id` allocation.

New ids come from an AUTOINCREMENT table in the universe's `global.db`. SQLite's
`BEGIN IMMEDIATE` takes the file-level write lock, so threads and separate processes
serialize on the same file and always receive distinct, increasing ids. The table is
seeded from the highest id already present in any DB or `families/*.db` file, so ids of
existing households are never reused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from hvl_common.db import get_db_connection

_MIN_NEW_FAMILY_ID = 2
_MAX_ALLOCATION_ATTEMPTS = 5


def allocate_family_id(global_db: Path, floor: int) -> int:
    """Returns a fresh id strictly greater than `floor` and every id handed out before."""
    seed = max(int(floor or 0), _MIN_NEW_FAMILY_ID - 1)
    Path(global_db).parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection(global_db, timeout=30.0) as conn:
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        try:
            top = conn.execute("SELECT COALESCE(MAX(family_id), 0) FROM family_id_allocator").fetchone()[0]
            if int(top) < seed:
                conn.execute("INSERT INTO family_id_allocator (family_id) VALUES (?)", (seed,))
            new_id = conn.execute("INSERT INTO family_id_allocator DEFAULT VALUES").lastrowid
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return int(new_id)


def fetch_max_family_id_in_db(s_db: Path) -> int:
    """Returns `COALESCE(MAX(family_id), 1)` from `families` in `s_db`."""
    with get_db_connection(s_db, timeout=10.0) as conn:
        r = conn.execute("SELECT COALESCE(MAX(family_id), 1) FROM families").fetchone()
        return int(r[0] or 1) if r else 1


def _family_row_exists(s_db: Path, fid: int) -> bool:
    with get_db_connection(s_db, timeout=10.0) as conn:
        return conn.execute("SELECT 1 FROM families WHERE family_id = ?", (fid,)).fetchone() is not None


def scan_max_family_id(scan_dbs: Sequence[Path], family_dir: Path) -> int:
    """Highest family id found in `families` tables of `scan_dbs` and `family_dir/<id>.db` files.

    An unreadable database raises: guessing a lower id could hand out an existing household's id.
    """
    max_fid = 1
    for s_db in scan_dbs:
        if Path(s_db).exists():
            max_fid = max(max_fid, fetch_max_family_id_in_db(Path(s_db)))
    if family_dir.exists():
        for f_file in family_dir.glob("*.db"):
            if f_file.stem.isdigit():
                max_fid = max(max_fid, int(f_file.stem))
    return max_fid


def _id_in_use(fid: int, scan_dbs: Sequence[Path], family_dir: Path) -> bool:
    if (family_dir / f"{fid}.db").exists():
        return True
    for s_db in scan_dbs:
        if Path(s_db).exists() and _family_row_exists(Path(s_db), fid):
            return True
    return False


def family_id_taken(global_db: Path, fid: int) -> bool:
    """True when `fid` was handed out by the allocator or has a household database file next to `global_db`."""
    if (Path(global_db).parent / "families" / f"{fid}.db").exists():
        return True
    with get_db_connection(global_db, timeout=10.0) as conn:
        return conn.execute("SELECT 1 FROM family_id_allocator WHERE family_id = ?", (fid,)).fetchone() is not None


def allocate_new_family_id(global_db: Path, scan_dbs: Sequence[Path], family_dir: Path) -> int:
    """
    Allocates a household id unique across the universe (allocator + on-disk scan).
    `scan_dbs` are every database that may hold `families` rows; `family_dir` holds `<id>.db` files.
    """
    for _ in range(_MAX_ALLOCATION_ATTEMPTS):
        new_id = allocate_family_id(global_db, scan_max_family_id(scan_dbs, family_dir))
        if not _id_in_use(new_id, scan_dbs, family_dir):
            return new_id
    raise RuntimeError("Could not allocate an unused household id")
