"""
db/balance_snapshots.py: Per-day account balance rows (`account_balance_snapshots`) — the storage behind
balance history. One row per (family, account, day), the balance encrypted per row, so a sync adds only the
days it brings instead of rewriting the whole history. Writes go through the ORM session, which bumps only
`balance_sheet` (`forecast.cache.TABLE_DOMAIN_MAP`); the full map is cached per domain version in `db.store`.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple, Union

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from db.models import AccountBalanceSnapshot
from db.session import get_orm_session, resolve_db_path

BalanceHistoryMap = Dict[str, Dict[str, float]]

# A sync re-sends years of daily balances; only its last week can still move (pending transactions settling).
SYNC_REFRESH_DAYS = 7


def _read_all_rows(family_id: int, path: Path) -> BalanceHistoryMap:
    out: BalanceHistoryMap = {}
    with get_orm_session(path, family_id=family_id) as session:
        rows = session.execute(
            select(
                AccountBalanceSnapshot.account_id,
                AccountBalanceSnapshot.snapshot_date,
                AccountBalanceSnapshot.balance_enc,
            )
            .where(AccountBalanceSnapshot.family_id == family_id)
            .order_by(AccountBalanceSnapshot.account_id, AccountBalanceSnapshot.snapshot_date)
        ).all()
    for acc_id, snap_date, bal in rows:
        out.setdefault(str(acc_id), {})[str(snap_date)] = round(float(bal or 0.0), 2)
    return out


def load_balance_history_map(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> BalanceHistoryMap:
    """Returns `{account_id: {"YYYY-MM-DD": balance}}` (dates ascending), a copy the caller may change."""
    if not family_id or family_id <= 0:
        return {}
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return {}
    from db import store as db_store

    cached = db_store.get_or_load_entity(
        family_id, "balance_history", lambda p: _read_all_rows(family_id, p), db_path=path
    )
    return {acc_id: dict(dates) for acc_id, dates in cached.items()}


def stored_snapshot_dates(session: Session, family_id: int, account_ids: Iterable[str]) -> Dict[str, Set[str]]:
    """The days already stored for each of `account_ids` (dates are plain columns: nothing is decrypted)."""
    ids = [str(a) for a in account_ids]
    out: Dict[str, Set[str]] = {a: set() for a in ids}
    if not ids:
        return out
    rows = session.execute(
        select(AccountBalanceSnapshot.account_id, AccountBalanceSnapshot.snapshot_date).where(
            AccountBalanceSnapshot.family_id == family_id,
            AccountBalanceSnapshot.account_id.in_(ids),
        )
    ).all()
    for acc_id, snap_date in rows:
        out.setdefault(str(acc_id), set()).add(str(snap_date))
    return out


def latest_snapshot(session: Session, family_id: int, account_id: str) -> Optional[Tuple[str, float]]:
    """`(date, balance)` of the newest stored day for `account_id`, or None when it has none."""
    latest_d = session.scalar(
        select(func.max(AccountBalanceSnapshot.snapshot_date)).where(
            AccountBalanceSnapshot.family_id == family_id,
            AccountBalanceSnapshot.account_id == str(account_id),
        )
    )
    if not latest_d:
        return None
    row = session.get(AccountBalanceSnapshot, (family_id, str(account_id), str(latest_d)))
    return (str(latest_d), float(row.balance_enc or 0.0)) if row is not None else None


def _days_to_write(
    dates: Dict[str, float],
    stored: Set[str],
    refresh_recent_days: Optional[int],
) -> Dict[str, float]:
    """With `refresh_recent_days`, a day already stored is rewritten only within that many days of the batch's
    newest day (a sync re-sends years of settled history); new days are always written."""
    if refresh_recent_days is None or not dates:
        return dates
    newest = max(dates)
    try:
        cutoff = (date.fromisoformat(newest) - timedelta(days=refresh_recent_days)).isoformat()
    except ValueError:
        cutoff = newest
    return {d: v for d, v in dates.items() if d not in stored or d >= cutoff}


def write_snapshots(
    session: Session,
    family_id: int,
    points: BalanceHistoryMap,
    *,
    refresh_recent_days: Optional[int] = None,
) -> BalanceHistoryMap:
    """Upserts `points` (`{account_id: {date: balance}}`) and returns the rows it wrote."""
    clean: BalanceHistoryMap = {
        str(acc_id): {str(d): round(float(v), 2) for d, v in dates.items() if d and v is not None}
        for acc_id, dates in points.items()
        if acc_id and dates
    }
    stored = stored_snapshot_dates(session, family_id, clean.keys()) if refresh_recent_days is not None else {}
    written: BalanceHistoryMap = {}
    params = []
    for acc_id, dates in clean.items():
        todo = _days_to_write(dates, stored.get(acc_id, set()), refresh_recent_days)
        if todo:
            written[acc_id] = todo
            params.extend(
                {"family_id": family_id, "account_id": acc_id, "snapshot_date": d, "balance_enc": v}
                for d, v in todo.items()
            )
    if params:
        stmt = sqlite_insert(AccountBalanceSnapshot)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["family_id", "account_id", "snapshot_date"],
                set_={"balance_enc": stmt.excluded.balance_enc},
            ),
            params,
        )
    return written


def delete_snapshots(
    session: Session,
    family_id: int,
    account_id: str,
    dates: Optional[Iterable[str]] = None,
) -> int:
    """Deletes `account_id`'s rows for `dates` (all of its rows when None); returns the number deleted."""
    stmt = delete(AccountBalanceSnapshot).where(
        AccountBalanceSnapshot.family_id == family_id,
        AccountBalanceSnapshot.account_id == str(account_id),
    )
    if dates is not None:
        stmt = stmt.where(AccountBalanceSnapshot.snapshot_date.in_([str(d) for d in dates]))
    return int(session.execute(stmt).rowcount or 0)


def delete_snapshots_for_prefix(session: Session, family_id: int, prefix: str) -> int:
    """Deletes the rows of every account whose id starts with `prefix` (e.g. `sfin_`)."""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    stmt = delete(AccountBalanceSnapshot).where(
        AccountBalanceSnapshot.family_id == family_id,
        AccountBalanceSnapshot.account_id.like(escaped + "%", escape="\\"),
    )
    return int(session.execute(stmt).rowcount or 0)


def merge_legacy_snapshots(
    family_id: int,
    history_map: BalanceHistoryMap,
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Moves a legacy `account_balance_history` blob into rows, filling only the days with no row yet: rows a sync
    wrote while the blob still waited (a locked vault) are newer and stay."""
    path = resolve_db_path(db_path, family_id=family_id)
    params = [
        {"family_id": family_id, "account_id": str(acc_id), "snapshot_date": str(d), "balance_enc": round(float(v), 2)}
        for acc_id, dates in history_map.items()
        for d, v in dates.items()
        if acc_id and d and v is not None
    ]
    if params:
        with get_orm_session(path, family_id=family_id, commit=True) as session:
            session.execute(sqlite_insert(AccountBalanceSnapshot).on_conflict_do_nothing(), params)
    return True
