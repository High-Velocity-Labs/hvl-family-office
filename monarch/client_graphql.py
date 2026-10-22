"""
monarch/client_graphql.py: Low-level Monarch Money GraphQL communication and headless account synchronization.
Patches MonarchMoney endpoints and executes async accounts, holdings, and balance snapshot queries.
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

import security
from monarch.categorizer import DATA_DIR, get_db_path

MONARCH_UPSTREAM_REFRESH_STALE_HOURS = 72
MONARCH_UPSTREAM_REFRESH_TIMEOUT_SECS = 60
MONARCH_UPSTREAM_REFRESH_POLL_SECS = 3

for _sp in [
    os.path.expanduser("~/venv/lib/python3.9/site-packages"),
    os.path.expanduser("~/venv/lib64/python3.9/site-packages"),
]:
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.insert(0, _sp)

SESSION_DIR = Path(__file__).resolve().parent.parent / ".mm"
SESSION_FILE = SESSION_DIR / "mm_session.pickle"


def get_family_session_file(family_id: int = 0) -> Path:
    """Returns legacy path to Monarch session pickle for a specific family."""
    return SESSION_DIR / f"session_family_{family_id}.pickle"


try:
    from monarchmoney import MonarchMoney
    try:
        from monarchmoney.monarchmoney import MonarchMoneyEndpoints
        MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"
        MonarchMoneyEndpoints.getLoginEndpoint = classmethod(lambda cls: "https://api.monarch.com/auth/login/")
        MonarchMoneyEndpoints.getGraphQL = classmethod(lambda cls: "https://api.monarch.com/graphql")
    except Exception:
        pass

    def _safe_set_token(self, token: str) -> None:
        self._token = token
        if not hasattr(self, "_headers") or self._headers is None:
            self._headers = {}
        self._headers["Authorization"] = f"Token {token}"

    MonarchMoney.set_token = _safe_set_token

    async def _safe_gql_call(
        self, operation: str, graphql_query: Any, variables: Dict[str, Any] = {}
    ) -> Dict[str, Any]:
        client = self._get_graphql_client()
        try:
            return await client.execute_async(graphql_query, variable_values=variables, operation_name=operation)
        except TypeError:
            try:
                return await client.execute_async(
                    request=graphql_query, variable_values=variables, operation_name=operation
                )
            except TypeError:
                async with client as session:
                    return await session.execute(graphql_query, variable_values=variables, operation_name=operation)

    MonarchMoney.gql_call = _safe_gql_call
except Exception:
    pass


def _persist_vault_token(db_path: Any, family_id: int, token: Optional[str], source: str = "monarch_sync") -> None:
    """Persists a Monarch bearer token into the encrypted SQLite vault and removes any legacy pickle file."""
    if not token or not family_id:
        return
    target_db = get_db_path(family_id=family_id) if (db_path is None or not getattr(db_path, "exists", lambda: False)() or getattr(db_path, "name", "").startswith("global")) else db_path
    if not target_db.exists():
        return
    try:
        creds = security.db_load_encrypted(target_db, "monarch_credentials", family_id=family_id) or {}
        if creds.get("token") != token:
            creds["token"] = token
            creds["updated_at"] = datetime.now(timezone.utc).isoformat()
            security.db_save_encrypted(target_db, "monarch_credentials", source, creds, family_id=family_id)
    except Exception:
        pass
    try:
        legacy_file = get_family_session_file(family_id)
        if legacy_file.exists():
            legacy_file.unlink(missing_ok=True)
    except Exception:
        pass


async def _refresh_stale_monarch_accounts_if_needed(
    mm: Any, accounts: list[Dict[str, Any]]
) -> tuple[list[Dict[str, Any]], int]:
    """Triggers an upstream Monarch bank refresh for active linked accounts older than MONARCH_UPSTREAM_REFRESH_STALE_HOURS."""
    now_utc = datetime.now(timezone.utc)
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
            except Exception:
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
    except Exception as exc:
        logger.warning("Monarch upstream refresh request skipped: %s", exc)
        return accounts, 0

    if hasattr(mm, "is_accounts_refresh_complete"):
        elapsed = 0
        while elapsed < MONARCH_UPSTREAM_REFRESH_TIMEOUT_SECS:
            try:
                if await mm.is_accounts_refresh_complete(stale_ids):
                    break
            except Exception:
                break
            await asyncio.sleep(MONARCH_UPSTREAM_REFRESH_POLL_SECS)
            elapsed += MONARCH_UPSTREAM_REFRESH_POLL_SECS

    try:
        refreshed_resp = await mm.get_accounts()
        if isinstance(refreshed_resp, dict) and isinstance(refreshed_resp.get("accounts"), list):
            accounts = refreshed_resp["accounts"]
    except Exception as exc:
        logger.warning("Failed re-fetching Monarch accounts after upstream refresh: %s", exc)

    return accounts, len(stale_ids)


async def _async_sync_monarch(family_id: int = 0, db_path: Any = None) -> Dict[str, Any]:
    """Headless async sync against Monarch GraphQL API scoped to a family using encrypted SQLite vault credentials."""
    try:
        from monarchmoney import MonarchMoney
    except Exception as ie:
        return {"success": False, "error": f"Monarch library import error ({type(ie).__name__}): {str(ie)}"}

    mm = MonarchMoney()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target_db = get_db_path(family_id=family_id) if (db_path is None or getattr(db_path, "name", "").startswith("global")) else db_path
    db_path = target_db
    session_file = get_family_session_file(family_id)

    authenticated = False

    if db_path.exists() and family_id:
        try:
            creds = security.db_load_encrypted(db_path, "monarch_credentials", family_id=family_id) or {}
            tok = creds.get("token") or ""
            email = creds.get("email") or ""
            password = creds.get("password") or ""
            mfa_secret = creds.get("mfa_secret_key") or None

            if tok and hasattr(mm, "set_token"):
                try:
                    mm.set_token(tok)
                    await mm.get_accounts()
                    authenticated = True
                except Exception:
                    authenticated = False

            if not authenticated and email and password:
                try:
                    await mm.login(
                        email=email, password=password, use_saved_session=False, save_session=False, mfa_secret_key=mfa_secret
                    )
                    await mm.get_accounts()
                    new_tok = getattr(mm, "_token", None) or getattr(mm, "token", "")
                    _persist_vault_token(db_path, family_id, new_tok)
                    authenticated = True
                except Exception:
                    authenticated = False
        except Exception:
            pass

    if not authenticated and session_file.exists():
        try:
            mm.load_session(str(session_file))
            await mm.get_accounts()
            migrated_tok = getattr(mm, "_token", None) or getattr(mm, "token", "")
            _persist_vault_token(db_path, family_id, migrated_tok)
            authenticated = True
        except Exception:
            authenticated = False

    if not authenticated and db_path.exists() and family_id:
        cookies_or_token = security.get_stored_cookies()
        if cookies_or_token:
            try:
                if hasattr(mm, "login_with_cookies"):
                    try:
                        await mm.login_with_cookies(cookies_or_token, save_session=False, verify=False)
                    except Exception:
                        pass

                parsed_cookies = {}
                if hasattr(mm, "_parse_cookie_string"):
                    try:
                        parsed_cookies = mm._parse_cookie_string(cookies_or_token)
                    except Exception:
                        pass

                if not parsed_cookies and ";" in cookies_or_token:
                    for pair in cookies_or_token.split(";"):
                        pair = pair.strip()
                        if "=" in pair:
                            k, _, v = pair.partition("=")
                            parsed_cookies[k.strip()] = v.strip()

                if parsed_cookies and hasattr(mm, "set_cookies"):
                    mm.set_cookies(parsed_cookies)

                tok = os.getenv("MONARCH_TOKEN") or ""
                if not tok:
                    if "__session=" in cookies_or_token or "token=" in cookies_or_token:
                        tok = parsed_cookies.get("__session") or parsed_cookies.get("token") or ""
                    elif len(cookies_or_token) > 50 and ";" not in cookies_or_token and "=" not in cookies_or_token:
                        tok = cookies_or_token

                if tok and hasattr(mm, "set_token"):
                    mm.set_token(tok)

                await mm.get_accounts()
                _persist_vault_token(db_path, family_id, tok or getattr(mm, "_token", None))
                authenticated = True
            except Exception as e:
                err_msg = str(e)
                if "401" in err_msg or "Unauthorized" in err_msg:
                    clean_err = "Monarch session has expired or authentication failed. Please connect with your Monarch email & password (or 2FA secret) in Settings > Monarch Connection."
                else:
                    clean_err = f"Monarch authentication failed: {err_msg}."
                return {"success": False, "error": clean_err}

    if not authenticated:
        return {
            "success": False,
            "error": "No valid Monarch session or credentials found for this family. Please connect Monarch in Settings.",
        }

    try:
        acc_resp = await mm.get_accounts()
        accounts = acc_resp.get("accounts", [])
    except Exception as e:
        return {"success": False, "error": f"Failed fetching accounts: {str(e)}"}

    accounts, refreshed_stale_count = await _refresh_stale_monarch_accounts_if_needed(mm, accounts)

    holdings_by_account: Dict[str, Any] = {}
    sem = asyncio.Semaphore(5)

    async def _fetch_holdings_for_account(acc: Dict[str, Any]) -> None:
        acc_id = acc.get("id")
        if not acc_id:
            return
        acc_type = (acc.get("type") or {}).get("name", "")
        holdings_count = acc.get("holdingsCount", 0)
        if acc_type in ("brokerage", "asset", "other") or holdings_count > 0 or acc.get("isManual"):
            async with sem:
                try:
                    h_resp = await mm.get_account_holdings(acc_id)
                    edges = h_resp.get("portfolio", {}).get("aggregateHoldings", {}).get("edges", [])
                    if edges:
                        holdings_by_account[acc_id] = [e.get("node", {}) for e in edges]
                except Exception:
                    pass

    await asyncio.gather(*(_fetch_holdings_for_account(acc) for acc in accounts))

    now_str = datetime.now(timezone.utc).isoformat()
    import db
    db.accounts.replace_accounts(family_id=family_id, accounts=accounts, db_path=db_path, provider="monarch")
    db.accounts.replace_holdings(family_id=family_id, holdings_by_account=holdings_by_account, db_path=db_path, provider="monarch")

    try:
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
                                if isinstance(b_entry, dict) and b_entry.get("date") is not None and b_entry.get("balance") is not None:
                                    hist_snapshots.append({
                                        "account_id": aid,
                                        "date": str(b_entry["date"]),
                                        "balance": float(b_entry["balance"] or 0.0),
                                    })
                        elif aid and item.get("date") is not None and (item.get("balance") is not None or item.get("signedBalance") is not None):
                            val = item.get("signedBalance") if item.get("signedBalance") is not None else item.get("balance")
                            hist_snapshots.append({
                                "account_id": aid,
                                "date": str(item["date"]),
                                "balance": float(val or 0.0),
                            })
            except Exception:
                pass

        if not hist_snapshots and hasattr(mm, "get_aggregate_snapshots"):
            try:
                agg_resp = await mm.get_aggregate_snapshots(start_date=start_dt, end_date=today_dt)
                agg_list = (agg_resp or {}).get("aggregateSnapshots") or []
                if isinstance(agg_list, list):
                    for snap in agg_list:
                        if isinstance(snap, dict) and snap.get("date") and snap.get("balance") is not None and snap.get("accountId"):
                            hist_snapshots.append({
                                "account_id": str(snap["accountId"]),
                                "date": str(snap["date"]),
                                "balance": float(snap["balance"] or 0.0),
                            })
            except Exception:
                pass

        if hist_snapshots:
            db.accounts.record_account_balance_snapshots(family_id=family_id, snapshots=hist_snapshots, db_path=db_path)
    except Exception as e:
        logger.warning("Failed to record account balance snapshots during monarch sync: %s", e)

    security.db_save_encrypted(
        db_path,
        "last_sync_metadata",
        "monarch_sync",
        {
            "timestamp": now_str,
            "status": "success",
            "provider": "monarch",
            "accounts_count": len(accounts),
            "holdings_accounts_count": len(holdings_by_account),
            "upstream_refreshed_count": refreshed_stale_count,
        },
        family_id=family_id,
    )

    return {
        "success": True,
        "provider": "monarch",
        "timestamp": now_str,
        "accounts_count": len(accounts),
        "holdings_count": sum(len(h) for h in holdings_by_account.values()),
        "upstream_refreshed_count": refreshed_stale_count,
    }
