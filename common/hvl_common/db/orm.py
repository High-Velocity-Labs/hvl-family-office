"""
Shared SQLAlchemy 2.0 ORM `Session` Scope & Unit-of-Work Domain Invalidation Hooks.

Binds `hvl_common.db.get_engine(db_path)` (`QueuePool`) with `hvl_common.db.types.encryption_context`
and invokes registered `after_commit` callbacks whenever ORM models or bulk DML statements mutate
domain tables.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional, Set, Union

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session

from hvl_common.db.sqlite import get_engine
from hvl_common.db.types import KeyResolverFn, encryption_context

CommitCallbackFn = Callable[[int, Set[str], Optional[Path]], None]


def _extract_object_household_id(obj: object, default_hid: int) -> int:
    for attr in ("household_id", "family_id"):
        val = getattr(obj, attr, None)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    if getattr(obj, "__tablename__", None) in ("households", "families"):
        for pk_attr in ("id", "family_id"):
            val = getattr(obj, pk_attr, None)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass
    return default_hid


@event.listens_for(Session, "before_flush")
def _hvl_capture_orm_uow_mutations(session: Session, _flush_context: object, _instances: object) -> None:
    if not session.info.get("_hvl_managed"):
        return
    default_hid = int(session.info.get("household_id", 0) or 0)
    excluded: Set[str] = session.info.get("_excluded_tables") or set()
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        tbl = getattr(obj, "__tablename__", None)
        if not tbl or tbl in excluded:
            continue
        hid = _extract_object_household_id(obj, default_hid)
        if hid > 0:
            session.info.setdefault("_hvl_mutated_tables", {}).setdefault(hid, set()).add(str(tbl))


@event.listens_for(Session, "do_orm_execute")
def _hvl_capture_bulk_dml_mutations(orm_execute_state: ORMExecuteState) -> None:
    session = orm_execute_state.session
    if not session.info.get("_hvl_managed"):
        return
    if not (
        orm_execute_state.is_insert
        or orm_execute_state.is_update
        or orm_execute_state.is_delete
    ):
        return
    table = getattr(orm_execute_state.statement, "table", None)
    tbl_name = getattr(table, "name", None) if table is not None else None
    excluded: Set[str] = session.info.get("_excluded_tables") or set()
    if tbl_name and tbl_name in excluded:
        return
    hid = int(session.info.get("household_id", 0) or 0)
    if hid > 0 and tbl_name:
        session.info.setdefault("_hvl_mutated_tables", {}).setdefault(hid, set()).add(str(tbl_name))


@event.listens_for(Session, "after_commit")
def _hvl_dispatch_after_commit(session: Session) -> None:
    if not session.info.get("_hvl_managed"):
        return
    mutated_map: dict[int, Set[str]] = session.info.pop("_hvl_mutated_tables", {})
    if not mutated_map or not session.info.get("invalidate_cache", True):
        return
    cb: Optional[CommitCallbackFn] = session.info.get("_on_commit_tables")
    if cb is None:
        return
    db_path: Optional[Path] = session.info.get("db_path")
    for hid, tables in sorted(mutated_map.items()):
        if hid > 0 and tables:
            cb(hid, tables, db_path)


@event.listens_for(Session, "after_rollback")
def _hvl_clear_on_rollback(session: Session) -> None:
    if not session.info.get("_hvl_managed"):
        return
    session.info.pop("_hvl_mutated_tables", None)


@contextmanager
def orm_session_scope(
    db_path: Union[str, Path],
    household_id: int = 1,
    *,
    key: Optional[bytes] = None,
    key_resolver: Optional[KeyResolverFn] = None,
    commit: bool = False,
    invalidate_cache: bool = True,
    excluded_tables: Optional[Set[str]] = None,
    on_commit_tables: Optional[CommitCallbackFn] = None,
) -> Iterator[Session]:
    """
    Context manager yielding a SQLAlchemy 2.0 `Session` bound to the pooled `QueuePool` engine
    for `db_path` and wrapped in `encryption_context(db_path, household_id)`.
    """
    resolved_path = Path(db_path)
    hid = int(household_id or 0)
    eff_key = key
    if eff_key is None and key_resolver is not None and hid > 0:
        eff_key = key_resolver(resolved_path, hid)

    engine = get_engine(resolved_path)
    session = Session(engine, expire_on_commit=False)
    session.info["_hvl_managed"] = True
    session.info["household_id"] = hid
    session.info["family_id"] = hid
    session.info["db_path"] = resolved_path
    session.info["invalidate_cache"] = bool(invalidate_cache)
    if excluded_tables:
        session.info["_excluded_tables"] = set(excluded_tables)
    if on_commit_tables is not None:
        session.info["_on_commit_tables"] = on_commit_tables

    with encryption_context(resolved_path, hid, key=eff_key, key_resolver=key_resolver):
        committed = False
        try:
            yield session
            if commit:
                session.commit()
                committed = True
        except Exception:
            if commit and not committed:
                session.rollback()
            raise
        finally:
            session.close()
