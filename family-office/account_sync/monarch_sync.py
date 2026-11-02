"""
account_sync/monarch_sync.py: Upstream account refresh, token persistence, and balance snapshot helpers
for Monarch Money GraphQL synchronization.
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import security
from account_sync.categorizer import get_db_path

logger = logging.getLogger(__name__)

# Network, HTTP and login failures a Monarch call can raise; anything else is a programming error and
# propagates to the job's error state.
MONARCH_REQUEST_ERRORS: tuple = (OSError, asyncio.TimeoutError)
try:
    import aiohttp
    from gql.transport.exceptions import TransportError
    from monarchmoney.monarchmoney import LoginFailedException, RequestFailedException, RequireMFAException
    MONARCH_REQUEST_ERRORS += (
        aiohttp.ClientError, TransportError, LoginFailedException, RequestFailedException, RequireMFAException,
    )
except ImportError:
    logger.warning("monarchmoney library is not installed; Monarch sync is unavailable")

MONARCH_UPSTREAM_REFRESH_STALE_HOURS = 72
MONARCH_UPSTREAM_REFRESH_TIMEOUT_SECS = 12
MONARCH_UPSTREAM_REFRESH_POLL_SECS = 2
MONARCH_UPSTREAM_REFRESH_COOLDOWN_HOURS = 12

SESSION_DIR = Path(__file__).resolve().parent.parent / ".mm"
SESSION_FILE = SESSION_DIR / "mm_session.pickle"


def get_family_session_file(family_id: int = 0) -> Path:
    """Returns legacy path to Monarch session pickle for a specific family."""
    return SESSION_DIR / f"session_family_{family_id}.pickle"


class MonarchTokenPersistError(RuntimeError):
    """The Monarch session token could not be durably saved to the encrypted vault."""


def _persist_vault_token(
    db_path: Any,
    family_id: int,
    token: Optional[str],
    source: str = "monarch_sync",
) -> None:
    """Persists a Monarch bearer token into the encrypted vault.

    The legacy session pickle is deleted only after the token is read back from the vault and matches.
    A failed or mismatching save, or a missing household DB, keeps the pickle and raises `MonarchTokenPersistError`.
    """
    if not token or not family_id:
        return
    is_global_or_missing = (
        db_path is None
        or not getattr(db_path, "exists", lambda: False)()
        or getattr(db_path, "name", "").startswith("global")
    )
    target_db = get_db_path(family_id=family_id) if is_global_or_missing else db_path
    if not target_db.exists():
        logger.error("Monarch token vault DB missing for family %s; legacy session file kept", family_id)
        raise MonarchTokenPersistError("Household database not found; Monarch token not saved and legacy session file kept.")
    try:
        creds = security.db_load_encrypted(target_db, "monarch_credentials", family_id=family_id) or {}
        if creds.get("token") != token:
            creds["token"] = token
            creds["updated_at"] = datetime.now(timezone.utc).isoformat()
            security.db_save_encrypted(target_db, "monarch_credentials", source, creds, family_id=family_id)
        confirmed = security.db_load_encrypted(target_db, "monarch_credentials", family_id=family_id) or {}
    except Exception as exc:
        logger.error("Monarch token save failed for family %s; legacy session file kept: %s", family_id, exc)
        raise MonarchTokenPersistError(f"Could not save the Monarch session token: {exc}") from exc
    if confirmed.get("token") != token:
        logger.error("Monarch token read-back mismatch for family %s; legacy session file kept", family_id)
        raise MonarchTokenPersistError("Monarch session token read-back did not match; legacy session file kept.")
    legacy_file = get_family_session_file(family_id)
    legacy_file.unlink(missing_ok=True)


async def _refresh_stale_monarch_accounts_if_needed(
    mm: Any,
    accounts: list[Dict[str, Any]],
    last_upstream_refresh_ts: Optional[str] = None,
) -> tuple[list[Dict[str, Any]], int]:
    """Triggers an upstream Monarch bank refresh for active linked accounts older than MONARCH_UPSTREAM_REFRESH_STALE_HOURS."""
    now_utc = datetime.now(timezone.utc)
    if isinstance(last_upstream_refresh_ts, str) and last_upstream_refresh_ts.strip():
        try:
            last_dt = datetime.fromisoformat(last_upstream_refresh_ts.strip().replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if (now_utc - last_dt) < timedelta(hours=MONARCH_UPSTREAM_REFRESH_COOLDOWN_HOURS):
                return accounts, 0
        except ValueError:
            logger.warning("Ignoring unparseable last_upstream_refresh_ts %r", last_upstream_refresh_ts)

    stale_threshold = timedelta(hours=MONARCH_UPSTREAM_REFRESH_STALE_HOURS)
    stale_ids: list[str] = []

    for acc in accounts or []:
        if not isinstance(acc, dict) or not acc.get("id"):
            continue
        if acc.get("isManual") or acc.get("syncDisabled") or acc.get("deactivatedAt"):
            continue
        cred = acc.get("credential")
        if isinstance(cred, dict):
            if cred.get("updateRequired") or cred.get("disconnectedFromDataProviderAt"):
                continue

        raw_ts = acc.get("displayLastUpdatedAt") or acc.get("updatedAt")
        is_stale = False
        if isinstance(raw_ts, str) and raw_ts.strip():
            try:
                parsed_dt = datetime.fromisoformat(raw_ts.strip().replace("Z", "+00:00"))
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                is_stale = (now_utc - parsed_dt) > stale_threshold
            except ValueError:
                is_stale = False
        elif isinstance(cred, dict) and cred and not acc.get("displayLastUpdatedAt"):
            is_stale = True

        if is_stale:
            stale_ids.append(str(acc["id"]))

    if not stale_ids or not hasattr(mm, "request_accounts_refresh"):
        return accounts, 0

    try:
        refresh_ok = await mm.request_accounts_refresh(stale_ids)
        if refresh_ok is False:
            return accounts, 0
    except MONARCH_REQUEST_ERRORS as exc:
        logger.warning("Monarch upstream refresh request skipped: %s", exc)
        return accounts, 0

    if hasattr(mm, "is_accounts_refresh_complete"):
        elapsed = 0
        while elapsed < MONARCH_UPSTREAM_REFRESH_TIMEOUT_SECS:
            try:
                if await mm.is_accounts_refresh_complete(stale_ids):
                    break
            except MONARCH_REQUEST_ERRORS as exc:
                logger.warning("Monarch refresh-status poll failed (%s); using accounts as is", type(exc).__name__)
                break
            await asyncio.sleep(MONARCH_UPSTREAM_REFRESH_POLL_SECS)
            elapsed += MONARCH_UPSTREAM_REFRESH_POLL_SECS

    try:
        refreshed_resp = await mm.get_accounts()
        if isinstance(refreshed_resp, dict) and isinstance(refreshed_resp.get("accounts"), list):
            accounts = refreshed_resp["accounts"]
    except MONARCH_REQUEST_ERRORS as exc:
        logger.warning("Failed re-fetching Monarch accounts after upstream refresh: %s", exc)

    return accounts, len(stale_ids)


async def _record_monarch_balance_snapshots(mm: Any, family_id: int, db_path: Any) -> None:
    """Fetches and persists 3-year historical account balance snapshots from Monarch Money."""
    import db

    today_dt = datetime.now(timezone.utc).date()
    start_dt = today_dt - timedelta(days=365 * 3)
    start_str = start_dt.isoformat()
    hist_snapshots = []

    if hasattr(mm, "get_recent_account_balances"):
        try:
            rec_resp = await mm.get_recent_account_balances(start_date=start_str)
            raw_snaps = (rec_resp or {}).get("accounts") or (rec_resp or {}).get("recentAccountBalances") or []
            if isinstance(raw_snaps, list):
                for item in raw_snaps:
                    if not isinstance(item, dict):
                        continue
                    aid = str(item.get("id") or item.get("accountId") or "").strip()
                    if isinstance(item.get("balances"), list) and aid:
                        for b_entry in item["balances"]:
                            if (
                                isinstance(b_entry, dict)
                                and b_entry.get("date") is not None
                                and b_entry.get("balance") is not None
                            ):
                                hist_snapshots.append({
                                    "account_id": aid,
                                    "date": str(b_entry["date"]),
                                    "balance": float(b_entry["balance"] or 0.0),
                                })
                    elif (
                        aid
                        and item.get("date") is not None
                        and (item.get("balance") is not None or item.get("signedBalance") is not None)
                    ):
                        signed = item.get("signedBalance")
                        val = signed if signed is not None else item.get("balance")
                        hist_snapshots.append({
                            "account_id": aid,
                            "date": str(item["date"]),
                            "balance": float(val or 0.0),
                        })
        except (*MONARCH_REQUEST_ERRORS, ValueError, TypeError) as exc:
            logger.warning("Monarch recent balance history unavailable (%s)", type(exc).__name__)

    if not hist_snapshots and hasattr(mm, "get_aggregate_snapshots"):
        try:
            agg_resp = await mm.get_aggregate_snapshots(start_date=start_dt, end_date=today_dt)
            agg_list = (agg_resp or {}).get("aggregateSnapshots") or []
            if isinstance(agg_list, list):
                for snap in agg_list:
                    if (
                        isinstance(snap, dict)
                        and snap.get("date")
                        and snap.get("balance") is not None
                        and snap.get("accountId")
                    ):
                        hist_snapshots.append({
                            "account_id": str(snap["accountId"]),
                            "date": str(snap["date"]),
                            "balance": float(snap["balance"] or 0.0),
                        })
        except (*MONARCH_REQUEST_ERRORS, ValueError, TypeError) as exc:
            logger.warning("Monarch aggregate balance history unavailable (%s)", type(exc).__name__)

    if hist_snapshots:
        db.accounts.record_account_balance_snapshots(family_id=family_id, snapshots=hist_snapshots, db_path=db_path)
