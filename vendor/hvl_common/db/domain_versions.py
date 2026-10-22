"""
Shared Reactive Domain-Version Persistence & Table-to-Domain Mapping Engine.
Provides SQLAlchemy 2.0 ORM key-value domain version persistence (`orm_get_domain_versions`,
`orm_bump_domains`), `DomainVersionTracker` with thread-safe in-memory fallback, and
JSON-row domain version snapshots (`family_domain_versions` table).
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import threading
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Set, Tuple
from sqlalchemy import select
from hvl_common.db.sqlite import _resolve_db_key, get_db_connection

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DOMAIN_DB_LOCK = threading.RLock()
_DOMAIN_DB_INIT: Set[str] = set()


def _validate_ident(ident: str) -> str:
    if not _IDENT_RE.match(ident):
        raise ValueError(f"Invalid SQL identifier: {ident!r}")
    return ident


@contextmanager
def _enter_session_ctx(session_ctx_fn: Any, *, commit: bool = False) -> Iterator[Any]:
    """Opens a SQLAlchemy Session context from either a `commit`-aware factory or a 0-arg factory."""
    fell_back = not callable(session_ctx_fn)
    if callable(session_ctx_fn):
        try:
            ctx = session_ctx_fn(commit=commit)
        except TypeError:
            ctx, fell_back = session_ctx_fn(), True
    else:
        ctx = session_ctx_fn
    with ctx as session:
        yield session
        if commit and fell_back and hasattr(session, "commit"):
            session.commit()


def orm_get_domain_versions(
    session_ctx_fn: Callable[..., Any],
    model_cls: Any,
    tenant_id: int = 1,
    default_domains: Sequence[str] = (),
    *,
    tenant_col: str = "household_id",
) -> dict[str, int]:
    """Reads per-tenant domain version counters from a key-value SQLAlchemy ORM model."""
    tid, col = int(tenant_id or 1), getattr(model_cls, tenant_col)
    with _enter_session_ctx(session_ctx_fn, commit=False) as session:
        rows = session.scalars(select(model_cls).where(col == tid)).all()
        versions: dict[str, int] = {str(d): 1 for d in default_domains}
        for r in rows:
            versions[str(r.domain)] = int(r.version)
        return versions


def orm_bump_domains(
    session_ctx_fn: Callable[..., Any],
    model_cls: Any,
    tenant_id: int = 1,
    domains: Sequence[str] = (),
    default_domains: Sequence[str] = (),
    *,
    tenant_col: str = "household_id",
) -> dict[str, int]:
    """Upserts and increments specified domain version rows in SQLite via SQLAlchemy ORM."""
    tid, col = int(tenant_id or 1), getattr(model_cls, tenant_col)
    clean_domains = [str(dom).strip() for dom in domains if (dom or "").strip()]
    with _enter_session_ctx(session_ctx_fn, commit=bool(clean_domains)) as session:
        for dom in clean_domains:
            existing = session.get(model_cls, (tid, dom))
            if existing is not None:
                existing.version = int(existing.version or 1) + 1
            else:
                session.add(model_cls(**{tenant_col: tid, "domain": dom, "version": 2}))
        if clean_domains:
            session.flush()
        rows = session.scalars(select(model_cls).where(col == tid)).all()
        versions: dict[str, int] = {str(d): 1 for d in default_domains}
        for r in rows:
            versions[str(r.domain)] = int(r.version)
        return versions


class DomainVersionTracker:
    """Thread-safe reactive domain version tracker with DB persistence and in-memory fallback (`_versions_cache`)."""

    def __init__(
        self,
        all_domains: Sequence[str],
        table_to_domains: Mapping[str, Sequence[str]],
        db_get_fn: Optional[Callable[..., dict[str, int]]] = None,
        db_bump_fn: Optional[Callable[..., dict[str, int]]] = None,
    ) -> None:
        self.all_domains: tuple[str, ...] = tuple(str(d) for d in all_domains)
        self.table_to_domains: dict[str, tuple[str, ...]] = {
            str(k): tuple(str(d) for d in v) for k, v in table_to_domains.items()
        }
        self.db_get_fn = db_get_fn
        self.db_bump_fn = db_bump_fn
        self._lock = threading.Lock()
        self._versions_cache: dict[int, dict[str, int]] = {}

    def get_domain_versions(self, tenant_id: int = 1, db_path: Path | str | None = None) -> dict[str, int]:
        """Returns a snapshot of domain version counters for a tenant."""
        tid = int(tenant_id or 1)
        if self.db_get_fn is not None:
            try:
                try:
                    return self.db_get_fn(tid, default_domains=self.all_domains, db_path=db_path)
                except TypeError:
                    return self.db_get_fn(tid, db_path=db_path)
            except Exception:
                pass
        with self._lock:
            if tid not in self._versions_cache:
                self._versions_cache[tid] = {d: 1 for d in self.all_domains}
            return dict(self._versions_cache[tid])

    def bump_domains(self, tenant_id: int = 1, *domains: str, db_path: Path | str | None = None) -> dict[str, int]:
        """Increments the specified domain version counters for a tenant."""
        tid = int(tenant_id or 1)
        clean_domains = [str(dom).strip() for dom in domains if (dom or "").strip()]
        if self.db_bump_fn is not None:
            try:
                try:
                    versions = self.db_bump_fn(tid, domains=clean_domains, default_domains=self.all_domains, db_path=db_path)
                except TypeError:
                    versions = self.db_bump_fn(tid, clean_domains, db_path=db_path)
                with self._lock:
                    self._versions_cache[tid] = dict(versions)
                return versions
            except Exception:
                pass
        with self._lock:
            if tid not in self._versions_cache:
                self._versions_cache[tid] = {d: 1 for d in self.all_domains}
            table = self._versions_cache[tid]
            for dom in clean_domains:
                table[dom] = int(table.get(dom, 1)) + 1
            return dict(table)

    def bump_domains_for_tables(
        self, tenant_id: int, tables: Iterable[str], _db_path: Path | str | None = None
    ) -> dict[str, int]:
        """SQLAlchemy `after_commit` callback mapping mutated table names to reactive domains."""
        domains: list[str] = []
        for tbl in tables:
            for dom in self.table_to_domains.get(str(tbl), ()):
                if dom not in domains:
                    domains.append(dom)
        if domains:
            return self.bump_domains(tenant_id, *domains, db_path=_db_path)
        return self.get_domain_versions(tenant_id, db_path=_db_path)


def ensure_json_domain_versions_schema(
    state_db: Path, table_name: str = "family_domain_versions", id_col: str = "family_id"
) -> None:
    """Ensures the JSON-row domain version table exists in `state_db`."""
    tbl, col, db_path = _validate_ident(table_name), _validate_ident(id_col), Path(state_db)
    init_key = f"{_resolve_db_key(db_path)}:{tbl}"
    if init_key in _DOMAIN_DB_INIT and db_path.exists():
        return
    with _DOMAIN_DB_LOCK:
        if init_key in _DOMAIN_DB_INIT and db_path.exists():
            return
        with get_db_connection(db_path, timeout=5.0) as conn:
            with conn:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {tbl} ("
                    f"{col} INTEGER PRIMARY KEY, state_version INTEGER NOT NULL DEFAULT 1, "
                    f"domains_json TEXT NOT NULL DEFAULT '{{}}', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
                )
            _DOMAIN_DB_INIT.add(init_key)


def load_json_domain_versions_row(
    state_db: Path, tenant_id: int, table_name: str = "family_domain_versions", id_col: str = "family_id"
) -> Optional[Tuple[int, Dict[str, int]]]:
    """Loads `(state_version, domain_map)` for `tenant_id` from the JSON domain versions table."""
    if state_db is None or not Path(state_db).parent.exists():
        return None
    try:
        tbl, col, db_path = _validate_ident(table_name), _validate_ident(id_col), Path(state_db)
        ensure_json_domain_versions_schema(db_path, table_name=tbl, id_col=col)
        with get_db_connection(db_path, timeout=5.0) as conn:
            row = conn.execute(f"SELECT state_version, domains_json FROM {tbl} WHERE {col} = ?", (int(tenant_id),)).fetchone()
            if row is None:
                return None
            parsed = json.loads(row[1] or "{}")
            return int(row[0] or 1), (parsed if isinstance(parsed, dict) else {})
    except Exception:
        return None


def save_json_domain_versions_row(
    state_db: Path, tenant_id: int, state_version: int, domain_map: Dict[str, int], table_name: str = "family_domain_versions", id_col: str = "family_id"
) -> None:
    """Upserts `(state_version, domain_map)` for `tenant_id` into the JSON domain versions table."""
    if state_db is None or not Path(state_db).parent.exists():
        return
    try:
        tbl, col, db_path = _validate_ident(table_name), _validate_ident(id_col), Path(state_db)
        ensure_json_domain_versions_schema(db_path, table_name=tbl, id_col=col)
        sql = (
            f"INSERT INTO {tbl} ({col}, state_version, domains_json, updated_at) "
            f"VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT({col}) DO UPDATE SET "
            f"state_version = excluded.state_version, domains_json = excluded.domains_json, updated_at = CURRENT_TIMESTAMP"
        )
        with get_db_connection(db_path, timeout=5.0) as conn:
            with conn:
                conn.execute(sql, (int(tenant_id), int(state_version), json.dumps(domain_map, separators=(",", ":"))))
    except Exception:
        pass


def delete_all_json_domain_versions(state_db: Path, table_name: str = "family_domain_versions") -> None:
    """Deletes all rows from the JSON domain versions table in `state_db`."""
    if state_db is None or not Path(state_db).exists():
        return
    try:
        tbl, db_path = _validate_ident(table_name), Path(state_db)
        ensure_json_domain_versions_schema(db_path, table_name=tbl)
        with get_db_connection(db_path, timeout=5.0) as conn:
            with conn:
                conn.execute(f"DELETE FROM {tbl}")
    except Exception:
        pass


__all__ = [
    "orm_get_domain_versions", "orm_bump_domains", "DomainVersionTracker",
    "ensure_json_domain_versions_schema", "load_json_domain_versions_row",
    "save_json_domain_versions_row", "delete_all_json_domain_versions",
]
