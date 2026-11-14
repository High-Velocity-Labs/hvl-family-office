"""
One-time re-encryption of household values stored before their columns became `Encrypted*`.

`household_profile.annual_spending` / `annual_savings`, `equity_companies.current_fmv`, `fmv_history.share_price`,
`equity_grants.vesting_schedule_json` and `gift_recipients.recipient_group_name` were plain columns. The models now
encrypt them, and reads still accept the old plaintext (`decrypt_field` returns a non-token value as it is), but rows
already on disk stay readable in the clear until something rewrites them. `encrypt_plaintext_columns` rewrites them
once: it runs from `security.init_db`, so a database is swept the first time a process opens it. A household whose
vault is locked (Support Access off) cannot be swept server-side and is skipped; the next process start tries again.
"""

from __future__ import annotations

import sqlite3
from sqlalchemy.exc import SQLAlchemyError
import logging
from pathlib import Path
from typing import Any, Iterable

from hvl_common.db import get_db_connection
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from db.models import EquityCompany, EquityGrantRecord, FmvHistoryRecord, GiftRecipient
from db.models_core import HouseholdProfile
from db.session import get_orm_session

logger = logging.getLogger(__name__)

_TOKEN_PREFIX = "gAAAAA"


def _is_plain(raw: Any) -> bool:
    """A value stored in the clear. A zero amount or an empty `{}` schedule is the column default, not household data,
    and is left as it is: `db.sandbox_repo` reads an untouched profile keylessly by its plain zeros."""
    if raw is None or raw in ("", "{}") or str(raw).startswith(_TOKEN_PREFIX):
        return False
    try:
        return float(raw) != 0.0
    except (TypeError, ValueError):
        return True


def _households_with_plaintext(db_path: Path) -> list[int]:
    """The households in `db_path` with at least one value still stored in the clear."""
    with get_db_connection(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        found: set[int] = set()
        if "household_profile" in tables:
            rows = conn.execute("SELECT family_id, annual_spending, annual_savings FROM household_profile").fetchall()
            found.update(int(r[0]) for r in rows if _is_plain(r[1]) or _is_plain(r[2]))
        if "equity_companies" in tables:
            rows = conn.execute("SELECT family_id, current_fmv FROM equity_companies").fetchall()
            found.update(int(r[0]) for r in rows if _is_plain(r[1]))
            if "fmv_history" in tables:
                rows = conn.execute(
                    "SELECT c.family_id, h.share_price FROM fmv_history h "
                    "JOIN equity_companies c ON c.company_id = h.company_id"
                ).fetchall()
                found.update(int(r[0]) for r in rows if _is_plain(r[1]))
        if "equity_grants" in tables:
            rows = conn.execute("SELECT family_id, vesting_schedule_json FROM equity_grants").fetchall()
            found.update(int(r[0]) for r in rows if _is_plain(r[1]))
        if "gift_recipients" in tables:
            rows = conn.execute("SELECT family_id, recipient_group_name FROM gift_recipients").fetchall()
            found.update(int(r[0]) for r in rows if _is_plain(r[1]))
    return sorted(fid for fid in found if fid > 0)


def _rewrite(rows: Iterable[Any], columns: tuple[str, ...]) -> int:
    """Marks each column holding a value dirty so the flush writes it back through its `Encrypted*` type."""
    count = 0
    for row in rows:
        held = [col for col in columns if getattr(row, col) not in (None, "", "{}", 0, 0.0)]
        for col in held:
            flag_modified(row, col)
        count += 1 if held else 0
    return count


def _encrypt_household(db_path: Path, family_id: int) -> int:
    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        count = _rewrite(
            session.scalars(select(HouseholdProfile).where(HouseholdProfile.family_id == family_id)).all(),
            ("annual_spending", "annual_savings"),
        )
        companies = session.scalars(select(EquityCompany).where(EquityCompany.family_id == family_id)).all()
        count += _rewrite(companies, ("current_fmv",))
        company_ids = [c.company_id for c in companies]
        if company_ids:
            count += _rewrite(
                session.scalars(select(FmvHistoryRecord).where(FmvHistoryRecord.company_id.in_(company_ids))).all(),
                ("share_price",),
            )
        count += _rewrite(
            session.scalars(select(EquityGrantRecord).where(EquityGrantRecord.family_id == family_id)).all(),
            ("vesting_schedule_json",),
        )
        count += _rewrite(
            session.scalars(select(GiftRecipient).where(GiftRecipient.family_id == family_id)).all(),
            ("recipient_group_name",),
        )
    return count


def encrypt_plaintext_columns(db_path: Path) -> int:
    """Encrypts every value of the formerly plain columns still stored in the clear; returns the rows rewritten."""
    path = Path(db_path)
    if not path.exists():
        return 0
    total = 0
    for family_id in _households_with_plaintext(path):
        try:
            total += _encrypt_household(path, family_id)
        except PermissionError:
            logger.info("Household %s vault is locked; its plaintext columns are encrypted once it unlocks", family_id)
        except (sqlite3.Error, SQLAlchemyError):
            # A sweep failure must not fail opening the database; the values stay readable and the next start retries.
            logger.exception("Encrypting plaintext columns of household %s failed", family_id)
    if total:
        logger.info("Encrypted %d rows of formerly plaintext columns in %s", total, path.name)
    return total
