"""
SQLite Database Engine, SQLAlchemy 2.0 `QueuePool`, Online Backup, and Migration Runner.
Provides production-grade bounded thread-safe SQLite connection pooling via SQLAlchemy 2.0
`QueuePool` with WAL mode, foreign keys, busy timeout, live online snapshot backups, and
transactional schema migration management.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Union

from collections import OrderedDict
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import NullPool, QueuePool

logger = logging.getLogger(__name__)

_POOL_MAX_SIZE = 8
_POOL_MAX_OVERFLOW = 16
_MAX_CACHED_ENGINES = 64
_engines_lock = threading.Lock()
_engines: OrderedDict[str, Engine] = OrderedDict()


def _resolve_db_key(db_path: Union[str, Path]) -> str:
    raw = str(db_path)
    if raw == ":memory:" or raw.startswith("file:"):
        return raw
    return str(Path(db_path).resolve())


def get_engine(db_path: Union[str, Path], timeout: float = 30.0) -> Engine:
    """
    Returns a cached SQLAlchemy 2.0 `Engine` backed by `QueuePool` (or `NullPool` for `:memory:`)
    with automatic SQLite WAL / foreign_keys / busy_timeout pragmas on every connection.
    """
    db_key = _resolve_db_key(db_path)
    if db_key == ":memory:":
        eng = create_engine(
            "sqlite:///:memory:",
            poolclass=NullPool,
            connect_args={"check_same_thread": False, "timeout": float(timeout)},
        )
        _register_sqlite_pragmas(eng, timeout=timeout)
        return eng

    if not db_key.startswith("file:"):
        path_obj = Path(db_key)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

    with _engines_lock:
        existing = _engines.get(db_key)
        if existing is not None:
            if db_key.startswith("file:") or Path(db_key).exists():
                _engines.move_to_end(db_key)
                return existing
            try:
                existing.dispose()
            except Exception:
                pass
            _engines.pop(db_key, None)

        if db_key.startswith("file:"):
            url = f"sqlite:///{db_key}"
            connect_args = {"check_same_thread": False, "timeout": float(timeout), "uri": True}
        else:
            posix_path = Path(db_key).as_posix()
            url = f"sqlite:///{posix_path}"
            connect_args = {"check_same_thread": False, "timeout": float(timeout)}

        eng = create_engine(
            url,
            poolclass=QueuePool,
            pool_size=_POOL_MAX_SIZE,
            max_overflow=_POOL_MAX_OVERFLOW,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        _register_sqlite_pragmas(eng, timeout=timeout)
        _engines[db_key] = eng
        _engines.move_to_end(db_key)

        while len(_engines) > _MAX_CACHED_ENGINES:
            evicted_key, evicted_eng = _engines.popitem(last=False)
            try:
                evicted_eng.dispose()
            except Exception:
                pass

        return eng


def _register_sqlite_pragmas(engine: Engine, timeout: float = 30.0) -> None:
    busy_ms = max(1000, int(timeout * 1000))

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: sqlite3.Connection, _conn_record: Any) -> None:
        dbapi_conn.execute("PRAGMA journal_mode = WAL;")
        dbapi_conn.execute("PRAGMA synchronous = NORMAL;")
        dbapi_conn.execute("PRAGMA foreign_keys = ON;")
        dbapi_conn.execute("PRAGMA temp_store = MEMORY;")
        dbapi_conn.execute(f"PRAGMA busy_timeout = {busy_ms};")


class _PooledConnection:
    """
    Lightweight adapter around a SQLAlchemy `QueuePool` checked-out DBAPI connection
    that supports both:
      1) `with get_db_connection(path) as conn:` (commits/rollbacks on exit, returns to QueuePool on close/GC)
      2) Explicit `conn = get_db_connection(path); try: with conn: ... finally: conn.close()`
    Without ever double-returning a connection to `QueuePool` or leaking open handles.
    """

    __slots__ = ("_fairy", "_conn", "_db_key", "_enter_depth")

    def __init__(
        self,
        fairy: Any,
        conn: sqlite3.Connection,
        db_key: str,
    ) -> None:
        object.__setattr__(self, "_fairy", fairy)
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_db_key", db_key)
        object.__setattr__(self, "_enter_depth", 0)

    @property
    def raw_connection(self) -> Optional[sqlite3.Connection]:
        return object.__getattribute__(self, "_conn")

    def _require_conn(self) -> sqlite3.Connection:
        conn = object.__getattribute__(self, "_conn")
        if conn is None:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
        return conn

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        return self._require_conn().execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters: Any, /) -> sqlite3.Cursor:
        return self._require_conn().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        return self._require_conn().executescript(sql_script)

    def cursor(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        return self._require_conn().cursor(*args, **kwargs)

    def commit(self) -> None:
        self._require_conn().commit()

    def rollback(self) -> None:
        self._require_conn().rollback()

    def backup(self, target: Any, *args: Any, **kwargs: Any) -> None:
        raw_target = target.raw_connection if isinstance(target, _PooledConnection) else target
        self._require_conn().backup(raw_target, *args, **kwargs)

    @property
    def in_transaction(self) -> bool:
        return self._require_conn().in_transaction

    @property
    def row_factory(self) -> Any:
        return self._require_conn().row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._require_conn().row_factory = value

    @property
    def total_changes(self) -> int:
        return self._require_conn().total_changes

    def __enter__(self) -> "_PooledConnection":
        conn = self._require_conn()
        depth = object.__getattribute__(self, "_enter_depth")
        object.__setattr__(self, "_enter_depth", depth + 1)
        conn.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        conn = object.__getattribute__(self, "_conn")
        depth = object.__getattribute__(self, "_enter_depth")
        if depth > 0:
            object.__setattr__(self, "_enter_depth", depth - 1)
        if conn is not None:
            return bool(conn.__exit__(exc_type, exc_val, exc_tb))
        return False

    def close(self) -> None:
        fairy = object.__getattribute__(self, "_fairy")
        conn = object.__getattribute__(self, "_conn")
        if conn is None and fairy is None:
            return
        object.__setattr__(self, "_fairy", None)
        object.__setattr__(self, "_conn", None)

        try:
            if conn is not None and conn.in_transaction:
                conn.rollback()
        except Exception:
            pass

        if fairy is not None:
            try:
                fairy.close()
                return
            except Exception:
                pass

        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._require_conn(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _PooledConnection.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._require_conn(), name, value)


def get_db_connection(
    db_path: Union[str, Path],
    timeout: float = 5.0,
    row_factory: Optional[Any] = sqlite3.Row,
) -> _PooledConnection:
    """
    Returns a SQLite connection checked out from the SQLAlchemy 2.0 `QueuePool`
    configured with WAL mode, foreign key enforcement, MEMORY temp_store, and busy timeouts.
    """
    db_key = _resolve_db_key(db_path)
    engine = get_engine(db_path, timeout=timeout)
    fairy = engine.raw_connection()
    raw_conn: sqlite3.Connection = fairy.driver_connection  # type: ignore[assignment]
    raw_conn.row_factory = row_factory
    return _PooledConnection(fairy, raw_conn, db_key)


def close_all_pools(db_path: Optional[Union[str, Path]] = None) -> None:
    """
    Disposes SQLAlchemy `QueuePool` engine connections.
    If `db_path` is provided, disposes only the engine for that specific database path.
    Otherwise disposes all active SQLAlchemy engines across the process.
    """
    with _engines_lock:
        if db_path is not None:
            key = _resolve_db_key(db_path)
            engines_to_dispose = [_engines.pop(key)] if key in _engines else []
        else:
            engines_to_dispose = list(_engines.values())
            _engines.clear()

    for eng in engines_to_dispose:
        try:
            eng.dispose()
        except Exception:
            pass


def backup_sqlite_db(
    src_db_path: Union[str, Path],
    dest_db_path: Union[str, Path],
) -> Path:
    """
    Creates an atomic, online point-in-time backup of an active SQLite database.
    Safe against active concurrent writes from web application processes.
    """
    src = Path(src_db_path)
    dest = Path(dest_db_path)

    if not src.exists():
        raise FileNotFoundError(f"Source SQLite database not found: {src}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    close_all_pools(dest)

    src_conn = sqlite3.connect(str(src))
    dest_conn = sqlite3.connect(str(dest))
    try:
        with dest_conn:
            src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()

    return dest


def run_migrations(
    db_path: Union[str, Path],
    migrations_dir: Union[str, Path],
) -> List[str]:
    """
    Discovers and executes pending `.sql` migration files in alphabetical order.
    Maintains an audit log in the `_schema_migrations` table.
    Each migration is executed in an isolated transaction.
    Returns list of newly applied migration file names.
    """
    mig_dir = Path(migrations_dir)
    if not mig_dir.exists():
        logger.warning(f"Migrations directory does not exist: {mig_dir}")
        return []

    sql_files = sorted(
        (p for p in mig_dir.glob("*.sql") if not p.name.startswith(".")),
        key=lambda p: p.name,
    )
    if not sql_files:
        return []

    conn = get_db_connection(db_path)
    applied_versions: List[str] = []

    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

        cur = conn.execute("SELECT version FROM _schema_migrations")
        existing = {row["version"] for row in cur.fetchall()}

        for sql_file in sql_files:
            version_name = sql_file.name
            if version_name in existing:
                continue

            logger.info(f"Applying migration: {version_name}")
            sql_content = sql_file.read_text(encoding="utf-8")

            with conn:
                conn.executescript(sql_content)
                conn.execute(
                    "INSERT INTO _schema_migrations (version) VALUES (?)",
                    (version_name,),
                )

            applied_versions.append(version_name)

    finally:
        conn.close()

    return applied_versions
