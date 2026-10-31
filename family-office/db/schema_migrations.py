"""
db/schema_migrations.py: the single place that brings a family/global SQLite file to the current schema.

- `alembic_head_revision()` derives the head from the `alembic/versions` scripts (no hand-kept constant).
- `migration_lock(db_path)` is an OS file lock (`<db>.migrate.lock`) so separate worker processes never migrate
  the same database at once; a `threading.Lock` per path covers threads inside one process.
- `upgrade_to_head(db_path)` runs Alembic under that lock and re-checks the stamp after acquiring it, so the
  worker that lost the race finds the database already at head and does nothing.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import threading
from typing import Iterator, Optional, Union

from alembic.config import Config
from alembic.script import ScriptDirectory

BASE_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI_PATH = BASE_DIR / "alembic.ini"
ALEMBIC_DIR = BASE_DIR / "alembic"

_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _alembic_config(db_path: Optional[Path] = None) -> Config:
    cfg = Config(str(ALEMBIC_INI_PATH) if ALEMBIC_INI_PATH.exists() else None)
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    if db_path is not None:
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{Path(db_path).resolve()}")
    cfg.attributes["skip_logging_config"] = True
    return cfg


def alembic_head_revision() -> str:
    """Returns the single head revision id of the `alembic/versions` chain."""
    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Alembic must have exactly one head, found {heads}")
    return heads[0]


def stamped_revision(db_path: Union[str, Path]) -> Optional[str]:
    """Returns the `alembic_version` stamp of `db_path`, or None for a database that was never stamped."""
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path), timeout=30.0)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
        return str(row[0]) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


@contextmanager
def migration_lock(db_path: Union[str, Path]) -> Iterator[None]:
    """Holds an exclusive cross-process (OS file) and cross-thread lock for migrating `db_path`."""
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _PATH_LOCKS_GUARD:
        thread_lock = _PATH_LOCKS.setdefault(str(path), threading.Lock())
    with thread_lock:
        fd = os.open(str(path) + ".migrate.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # closing the descriptor releases the lock on both platforms


# Alembic's `op` and `context` proxies are process-wide globals: two upgrades running at once in one process (on any
# two databases, e.g. a request thread and a background job) clobber each other's and fail with `op` = None. The
# per-path `migration_lock` cannot prevent that, so each process runs one Alembic upgrade at a time.
_ALEMBIC_RUN_LOCK = threading.RLock()


def _upgrade_locked(path: Path) -> bool:
    from alembic import command
    from hvl_common.db import get_engine

    if stamped_revision(path) == alembic_head_revision():
        return False
    cfg = _alembic_config(path)
    with _ALEMBIC_RUN_LOCK, get_engine(path).begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    return True


def upgrade_to_head(db_path: Union[str, Path]) -> bool:
    """
    Brings `db_path` to the Alembic head under `migration_lock`. Returns True when this call ran migrations,
    False when the database was already at head (including when another process just finished the upgrade).
    """
    path = Path(db_path)
    with migration_lock(path):
        return _upgrade_locked(path)
