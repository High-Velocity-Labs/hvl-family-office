"""
SQLAlchemy 2.0 ORM `Session` factory and automatic `after_commit` cache invalidation hooks.

Binds `hvl_common.db.get_engine(db_path)` (`QueuePool`) with `db.types.encryption_context`
and automatically triggers `db.store.notify_family_mutation(family_id)` whenever a domain
transaction commits.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
from typing import Iterator, Optional, Set, Union

logger = logging.getLogger(__name__)

from hvl_common.db import get_engine
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session

from db.types import encryption_context
import security

# Tables whose mutations do not affect financial/forecast domain state
_EXCLUDED_INVALIDATION_TABLES: Set[str] = {
    "advisor_conversations",
    "advisor_messages",
    "family_state_versions",
}


_AUTH_SYNC_TABLES: Set[str] = {"families", "users", "account_roles"}


def resolve_db_path(
    db_path: Optional[Union[str, Path]] = None,
    family_id: Optional[int] = None,
) -> Path:
    """
    Resolves the active SQLite database path for the current request/universe/family context.
    - If family_id > 0 is passed or resolved from context, routes to the dedicated family database.
    - If family_id is 0 or absent, routes to the global database.
    - Explicit non-monolithic test/mock paths are preserved.
    """
    from config import VALID_UNIVERSES, get_family_db_path, get_global_db_path
    from routes.helpers import _DbPathProxy, get_current_family_id, get_current_universe

    fid = int(family_id if family_id is not None else get_current_family_id() or 0)
    uni = get_current_universe()

    if db_path is not None and not isinstance(db_path, _DbPathProxy) and not hasattr(db_path, "_path"):
        p = Path(db_path)
        p_name = p.name
        if (p_name.startswith("family_office") or p_name.startswith("global")) and p_name.endswith(".db"):
            if p.parent.name in VALID_UNIVERSES:
                if fid > 0:
                    fam_dir = p.parent / "families"
                    fam_dir.mkdir(parents=True, exist_ok=True)
                    return fam_dir / f"{fid}.db"
                return p.parent / "global.db"
            if "_beta" in p_name or "_demo" in p_name:
                u = "demo"
            elif "_sandbox" in p_name:
                u = "sandbox"
            elif "_test" in p_name:
                u = "test"
            else:
                u = "public"
            if fid > 0:
                return get_family_db_path(fid, universe=u)
            return get_global_db_path(universe=u)
        return p

    if fid > 0:
        return get_family_db_path(fid, universe=uni)
    return get_global_db_path(universe=uni)


def mark_session_mutated(session: Session, family_id: Optional[int] = None) -> None:
    """Explicitly records a mutated `family_id` on `session.info` for post-commit cache invalidation."""
    fid = int(family_id if family_id is not None else session.info.get("family_id", 0) or 0)
    if fid > 0:
        mutated: Set[int] = session.info.setdefault("_mutated_family_ids", set())
        mutated.add(fid)


def _upsert_sql(table: str, cols: list[str], conflict_cols: tuple[str, ...]) -> str:
    """Builds an SQLite `INSERT INTO ... ON CONFLICT(...) DO UPDATE SET ...` statement that never triggers ON DELETE CASCADE."""
    col_str = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    conflict_str = ", ".join(f'"{c}"' for c in conflict_cols)
    update_cols = [c for c in cols if c not in conflict_cols]
    if not update_cols:
        return f'INSERT INTO "{table}" ({col_str}) VALUES ({placeholders}) ON CONFLICT({conflict_str}) DO NOTHING'
    update_str = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols)
    return f'INSERT INTO "{table}" ({col_str}) VALUES ({placeholders}) ON CONFLICT({conflict_str}) DO UPDATE SET {update_str}'


def _ensure_peer_family_row(sconn: object, pconn: object, fid: int) -> None:
    """Ensures parent family row exists in peer DB using non-destructive ON CONFLICT DO UPDATE."""
    if not pconn.execute("SELECT 1 FROM families WHERE family_id = ?", (fid,)).fetchone():
        fam_row = sconn.execute("SELECT * FROM families WHERE family_id = ?", (fid,)).fetchone()
        if fam_row:
            fcols = [c[1] for c in sconn.execute("PRAGMA table_info(families)").fetchall()]
            pconn.execute(_upsert_sql("families", fcols, ("family_id",)), tuple(fam_row))
            pconn.commit()


def _sync_auth_records_to_peer_db(session: Session, mutated_tables: Set[tuple[str, int]], deleted_records: Set[tuple[str, int, Any]]) -> None:
    """Synchronizes mutated auth tables (families, users, account_roles) between family.db and global.db within the same universe directory."""
    from hvl_common.db import get_db_connection

    src_db = Path(session.info.get("db_path", ""))
    if not src_db.exists():
        return

    for tbl, fid in mutated_tables:
        if fid <= 0:
            continue
        peers = []
        try:
            if src_db.parent.name == "families":
                uni_dir = src_db.parent.parent
                global_db = uni_dir / "global.db"
                peers.append(global_db)
            elif src_db.name == "global.db":
                uni_dir = src_db.parent
                family_db = uni_dir / "families" / f"{fid}.db"
                family_db.parent.mkdir(parents=True, exist_ok=True)
                peers.append(family_db)
            elif src_db.name.startswith("family_office") and src_db.name.endswith(".db"):
                uni_dir = src_db.parent
                family_db = uni_dir / "families" / f"{fid}.db"
                family_db.parent.mkdir(parents=True, exist_ok=True)
                global_db = uni_dir / "global.db"
                peers.extend([family_db, global_db])
        except Exception:
            continue

        for peer in peers:
            security.init_db(peer)
            try:
                with get_db_connection(src_db, timeout=10.0) as sconn, get_db_connection(peer, timeout=10.0) as pconn:
                    if tbl == "families":
                        row = sconn.execute("SELECT * FROM families WHERE family_id = ?", (fid,)).fetchone()
                        if row:
                            cols = [c[1] for c in sconn.execute("PRAGMA table_info(families)").fetchall()]
                            pconn.execute(_upsert_sql("families", cols, ("family_id",)), tuple(row))
                            pconn.commit()
                    elif tbl == "users":
                        _ensure_peer_family_row(sconn, pconn, fid)
                        rows = sconn.execute("SELECT * FROM users WHERE family_id = ?", (fid,)).fetchall()
                        cols = [c[1] for c in sconn.execute("PRAGMA table_info(users)").fetchall()]
                        uid_idx = cols.index("user_id") if "user_id" in cols else 0
                        explicit_del_uids = [
                            pk for (dtbl, dfid, pk) in deleted_records
                            if dtbl == "users" and dfid == fid and pk is not None
                        ]
                        if rows:
                            keep_uids = [r[uid_idx] for r in rows]
                            ph = ", ".join("?" for _ in keep_uids)
                            pconn.execute(f"DELETE FROM users WHERE family_id = ? AND user_id NOT IN ({ph})", (fid, *keep_uids))
                            pconn.executemany(_upsert_sql("users", cols, ("user_id",)), [tuple(r) for r in rows])
                        elif explicit_del_uids:
                            ph = ", ".join("?" for _ in explicit_del_uids)
                            pconn.execute(f"DELETE FROM users WHERE family_id = ? AND user_id IN ({ph})", (fid, *explicit_del_uids))
                        pconn.commit()
                    elif tbl == "account_roles":
                        _ensure_peer_family_row(sconn, pconn, fid)
                        rows = sconn.execute("SELECT * FROM account_roles WHERE family_id = ?", (fid,)).fetchall()
                        cols = [c[1] for c in sconn.execute("PRAGMA table_info(account_roles)").fetchall()]
                        upsert_cols = [c for c in cols if c != "role_id"]
                        col_indices = [cols.index(c) for c in upsert_cols]
                        acct_idx = cols.index("monarch_account_id") if "monarch_account_id" in cols else -1
                        if rows and acct_idx >= 0:
                            keep_accts = [r[acct_idx] for r in rows]
                            ph = ", ".join("?" for _ in keep_accts)
                            pconn.execute(
                                f"DELETE FROM account_roles WHERE family_id = ? AND monarch_account_id NOT IN ({ph})",
                                (fid, *keep_accts),
                            )
                            pconn.executemany(
                                _upsert_sql("account_roles", upsert_cols, ("family_id", "monarch_account_id")),
                                [tuple(r[i] for i in col_indices) for r in rows],
                            )
                        elif not rows and any(dtbl == "account_roles" and dfid == fid for (dtbl, dfid, _) in deleted_records):
                            pconn.execute("DELETE FROM account_roles WHERE family_id = ?", (fid,))
                        pconn.commit()
            except Exception as e:
                logger.error("Peer sync failed for %s to %s (tbl=%s, fid=%s): %s", src_db, peer, tbl, fid, e, exc_info=True)


@event.listens_for(Session, "before_flush")
def _capture_orm_unit_of_work_mutations(session: Session, flush_context: object, instances: object) -> None:
    """Records `family_id` and mutated table names for any ORM model added, modified, or deleted during flush."""
    default_fid = int(session.info.get("family_id", 0) or 0)
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        tbl = getattr(obj, "__tablename__", None)
        if not tbl or tbl in _EXCLUDED_INVALIDATION_TABLES:
            continue
        fid = getattr(obj, "family_id", None)
        if fid is None:
            comp = getattr(obj, "company", None)
            if comp is not None:
                fid = getattr(comp, "family_id", None)
        eff_fid = int(fid if fid is not None else default_fid or 0)
        if eff_fid > 0:
            session.info.setdefault("_mutated_family_ids", set()).add(eff_fid)
            session.info.setdefault("_mutated_family_tables", {}).setdefault(eff_fid, set()).add(str(tbl))

    # Track auth table mutations for cross-DB synchronization
    for obj in list(session.new) + list(session.dirty):
        tbl = getattr(obj, "__tablename__", None)
        if tbl in _AUTH_SYNC_TABLES:
            fid = getattr(obj, "family_id", default_fid) or default_fid
            if fid > 0:
                session.info.setdefault("_auth_sync_mutations", set()).add((tbl, int(fid)))

    for obj in list(session.deleted):
        tbl = getattr(obj, "__tablename__", None)
        if tbl in _AUTH_SYNC_TABLES:
            fid = getattr(obj, "family_id", default_fid) or default_fid
            pk_val = getattr(obj, "user_id", None) or getattr(obj, "family_id", None)
            if fid > 0:
                session.info.setdefault("_auth_sync_deletes", set()).add((tbl, int(fid), pk_val))
                session.info.setdefault("_auth_sync_mutations", set()).add((tbl, int(fid)))


@event.listens_for(Session, "do_orm_execute")
def _capture_bulk_dml_mutations(orm_execute_state: ORMExecuteState) -> None:
    """Records `family_id` and table name when bulk `insert()`, `update()`, or `delete()` statements execute."""
    if not (
        orm_execute_state.is_insert
        or orm_execute_state.is_update
        or orm_execute_state.is_delete
    ):
        return
    session = orm_execute_state.session
    stmt = orm_execute_state.statement
    tbl_name: Optional[str] = None
    table = getattr(stmt, "table", None)
    if table is not None:
        tbl_name = getattr(table, "name", None)
    if tbl_name and tbl_name in _EXCLUDED_INVALIDATION_TABLES:
        return
    fid = int(session.info.get("family_id", 0) or 0)
    if fid > 0:
        session.info.setdefault("_mutated_family_ids", set()).add(fid)
        if tbl_name:
            session.info.setdefault("_mutated_family_tables", {}).setdefault(fid, set()).add(str(tbl_name))
    if tbl_name and tbl_name in _AUTH_SYNC_TABLES and fid > 0:
        session.info.setdefault("_auth_sync_mutations", set()).add((tbl_name, fid))


@event.listens_for(Session, "after_commit")
def _invalidate_caches_after_commit(session: Session) -> None:
    """Automatically invalidates L1/L2 forecast and domain caches after a committed write."""
    mutated_auth = session.info.pop("_auth_sync_mutations", None)
    deleted_auth = session.info.pop("_auth_sync_deletes", None)
    if mutated_auth or deleted_auth:
        _sync_auth_records_to_peer_db(session, mutated_auth or set(), deleted_auth or set())

    mutated_fids: Set[int] = session.info.pop("_mutated_family_ids", set())
    mutated_tables: dict = session.info.pop("_mutated_family_tables", {})
    if not mutated_fids or not session.info.get("invalidate_cache", True):
        return
    from db import store as _store
    from forecast_cache_helpers import resolve_domains_for_tables

    src_db = Path(session.info.get("db_path", "")) if session.info.get("db_path") else None
    for fid in sorted(mutated_fids):
        if fid > 0:
            domains = resolve_domains_for_tables(mutated_tables.get(fid))
            _store.notify_family_mutation(fid, domains=domains or None, db_path=src_db)


@event.listens_for(Session, "after_rollback")
def _clear_mutated_families_on_rollback(session: Session) -> None:
    """Discards pending cache invalidations if the transaction rolls back."""
    session.info.pop("_mutated_family_ids", None)
    session.info.pop("_mutated_family_tables", None)
    session.info.pop("_auth_sync_mutations", None)
    session.info.pop("_auth_sync_deletes", None)


@contextmanager
def get_orm_session(
    db_path: Optional[Union[str, Path]] = None,
    family_id: int = 0,
    *,
    commit: bool = False,
    invalidate_cache: bool = True,
) -> Iterator[Session]:
    """
    Context manager yielding a SQLAlchemy 2.0 `Session` bound to the pooled engine for
    `db_path` and wrapped in `encryption_context(db_path, family_id)`.
    """
    resolved_path = resolve_db_path(db_path, family_id=family_id)
    fid = int(family_id or 0)
    pre_resolved_key: Optional[bytes] = None

    if not resolved_path.exists() or commit:
        security.init_db(resolved_path)
        if commit and fid > 0:
            pre_resolved_key = security.get_family_key(resolved_path, fid)
    elif resolved_path.exists():
        security.init_db(resolved_path)

    engine = get_engine(resolved_path)
    session = Session(engine, expire_on_commit=False)
    session.info["family_id"] = fid
    session.info["db_path"] = resolved_path
    session.info["invalidate_cache"] = bool(invalidate_cache)

    with encryption_context(resolved_path, fid, key=pre_resolved_key):
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
