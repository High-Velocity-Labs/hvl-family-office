"""
Monarch GraphQL client, authentication, and encrypted SQLite vault session persistence.
Eliminates unencrypted `.mm/session_family_{id}.pickle` files on disk in favor of storing
and resuming session tokens directly inside the per-family encrypted SQLite store.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
import pickle
import sys
from typing import Any, Dict, Optional

import requests
from cryptography.fernet import InvalidToken
from sqlalchemy.exc import SQLAlchemyError

import security
from account_sync.sync_outcome import combine_provider_results
from account_sync.categorizer import DATA_DIR, get_db_path
from account_sync.sync_lifecycle import run_provider_sync
from db.sync_metadata import load_provider_sync_entry, merge_provider_sync_entry
from account_sync.monarch_sync import (
    MONARCH_UPSTREAM_REFRESH_COOLDOWN_HOURS,
    MONARCH_UPSTREAM_REFRESH_POLL_SECS,
    MONARCH_UPSTREAM_REFRESH_STALE_HOURS,
    MONARCH_UPSTREAM_REFRESH_TIMEOUT_SECS,
    SESSION_DIR,
    SESSION_FILE,
    MONARCH_REQUEST_ERRORS as _MONARCH_REQUEST_ERRORS,
    MonarchTokenPersistError,
    _persist_vault_token,
    _record_monarch_balance_snapshots,
    _refresh_stale_monarch_accounts_if_needed,
    get_family_session_file,
)

logger = logging.getLogger(__name__)

for _sp in [
    os.path.expanduser("~/venv/lib/python3.9/site-packages"),
    os.path.expanduser("~/venv/lib64/python3.9/site-packages"),
]:
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.insert(0, _sp)

try:
    from monarchmoney import MonarchMoney
    try:
        from monarchmoney.monarchmoney import MonarchMoneyEndpoints
        MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"
        MonarchMoneyEndpoints.getLoginEndpoint = classmethod(lambda cls: "https://api.monarch.com/auth/login/")
        MonarchMoneyEndpoints.getGraphQL = classmethod(lambda cls: "https://api.monarch.com/graphql")
    except ImportError:
        logger.warning("monarchmoney has no MonarchMoneyEndpoints; endpoint patch skipped")

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
except ImportError:
    logger.warning("monarchmoney library is not installed; Monarch sync is unavailable")


async def _async_sync_monarch(family_id: int = 0, db_path: Any = None) -> Dict[str, Any]:
    """Headless async sync against Monarch GraphQL API scoped to a family using encrypted SQLite vault credentials."""
    try:
        from monarchmoney import MonarchMoney
    except ImportError as ie:
        return {"success": False, "error": f"Monarch library import error ({type(ie).__name__}): {str(ie)}"}

    mm = MonarchMoney()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target_db = (
        get_db_path(family_id=family_id)
        if (db_path is None or getattr(db_path, "name", "").startswith("global"))
        else db_path
    )
    db_path = target_db
    session_file = get_family_session_file(family_id)

    authenticated = False
    token_errors: list[str] = []

    def _save_token(token: Optional[str]) -> None:
        """Vault save is confirmed by read-back; on failure the legacy pickle is kept and the error is reported."""
        try:
            _persist_vault_token(db_path, family_id, token)
        except MonarchTokenPersistError:
            token_errors.append("Monarch session token could not be saved to the vault; the legacy session file was kept.")

    if db_path.exists() and family_id:
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
            except _MONARCH_REQUEST_ERRORS as exc:
                logger.info("Stored Monarch token rejected for family %s (%s)", family_id, type(exc).__name__)

        if not authenticated and email and password:
            try:
                await mm.login(
                    email=email,
                    password=password,
                    use_saved_session=False,
                    save_session=False,
                    mfa_secret_key=mfa_secret,
                )
                await mm.get_accounts()
                new_tok = getattr(mm, "_token", None) or getattr(mm, "token", "")
                _save_token(new_tok)
                authenticated = True
            except _MONARCH_REQUEST_ERRORS as exc:
                logger.warning("Monarch password login failed for family %s (%s)", family_id, type(exc).__name__)

    if not authenticated and session_file.exists():
        try:
            mm.load_session(str(session_file))
            await mm.get_accounts()
            migrated_tok = getattr(mm, "_token", None) or getattr(mm, "token", "")
            _save_token(migrated_tok)
            authenticated = True
        except (EOFError, pickle.UnpicklingError, *_MONARCH_REQUEST_ERRORS) as exc:
            logger.warning("Legacy Monarch session file unusable for family %s (%s)", family_id, type(exc).__name__)

    if not authenticated and db_path.exists() and family_id:
        cookies_or_token = security.get_stored_cookies()
        if cookies_or_token:
            try:
                if hasattr(mm, "login_with_cookies"):
                    try:
                        await mm.login_with_cookies(cookies_or_token, save_session=False, verify=False)
                    except _MONARCH_REQUEST_ERRORS as exc:
                        logger.warning("Monarch cookie login failed (%s); trying token fallback", type(exc).__name__)

                parsed_cookies = {}
                if hasattr(mm, "_parse_cookie_string"):
                    parsed_cookies = mm._parse_cookie_string(cookies_or_token)

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
                _save_token(tok or getattr(mm, "_token", None))
                authenticated = True
            except _MONARCH_REQUEST_ERRORS as e:
                err_msg = str(e)
                if "401" in err_msg or "Unauthorized" in err_msg:
                    clean_err = (
                        "Monarch session has expired or authentication failed. "
                        "Please connect with your Monarch email & password (or 2FA secret) in Settings > Monarch Connection."
                    )
                else:
                    clean_err = f"Monarch authentication failed: {err_msg}."
                return {"success": False, "error": clean_err}

    if not authenticated:
        return {
            "success": False,
            "status": "not_connected",
            "error": "No valid Monarch session or credentials found for this family. Please connect Monarch in Settings.",
        }

    try:
        acc_resp = await mm.get_accounts()
        accounts = acc_resp.get("accounts", [])
    except _MONARCH_REQUEST_ERRORS as e:
        return {"success": False, "error": f"Failed fetching accounts: {str(e)}"}

    prev_upstream_ts: Optional[str] = None
    if db_path.exists() and family_id:
        prev_upstream_ts = load_provider_sync_entry(db_path, family_id, "monarch").get("last_upstream_refresh_ts")

    accounts, refreshed_stale_count = await _refresh_stale_monarch_accounts_if_needed(
        mm, accounts, last_upstream_refresh_ts=prev_upstream_ts
    )

    holdings_by_account: Dict[str, Any] = {}
    failed_holdings_accounts: Dict[str, str] = {}
    fetched_holdings_accounts: set = set()
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
                    fetched_holdings_accounts.add(acc_id)
                    if edges:
                        holdings_by_account[acc_id] = [e.get("node", {}) for e in edges]
                except _MONARCH_REQUEST_ERRORS as exc:
                    logger.warning("Monarch holdings fetch failed for account %s: %s", acc_id, exc)
                    failed_holdings_accounts[acc_id] = f"{type(exc).__name__}: {exc}"

    await asyncio.gather(*(_fetch_holdings_for_account(acc) for acc in accounts))

    if failed_holdings_accounts and not fetched_holdings_accounts:
        return {
            "success": False,
            "status": "failed",
            "provider": "monarch",
            "error": (
                f"Monarch holdings could not be fetched for any of {len(failed_holdings_accounts)} accounts; "
                "your existing holdings were kept unchanged."
            ),
            "failed_accounts": sorted(failed_holdings_accounts),
        }

    now_str = datetime.now(timezone.utc).isoformat()
    sync_status = "partial" if failed_holdings_accounts else "success"
    import db
    db.accounts.replace_accounts_and_holdings(
        family_id=family_id,
        accounts=accounts,
        holdings_by_account=holdings_by_account,
        db_path=db_path,
        provider="monarch",
        preserve_holdings_account_ids=failed_holdings_accounts,
    )

    await _record_monarch_balance_snapshots(mm, family_id=family_id, db_path=db_path)

    merge_provider_sync_entry(
        db_path,
        family_id,
        "monarch",
        {
            "timestamp": now_str,
            "status": sync_status,
            "provider": "monarch",
            "accounts_count": len(accounts),
            "holdings_accounts_count": len(holdings_by_account),
            "failed_holdings_accounts": sorted(failed_holdings_accounts),
            "upstream_refreshed_count": refreshed_stale_count,
            "last_upstream_refresh_ts": now_str if refreshed_stale_count > 0 else prev_upstream_ts,
        },
    )

    return {
        "success": True,
        "status": sync_status,
        "failed_accounts": sorted(failed_holdings_accounts),
        "provider": "monarch",
        "timestamp": now_str,
        "accounts_count": len(accounts),
        "holdings_count": sum(len(h) for h in holdings_by_account.values()),
        "upstream_refreshed_count": refreshed_stale_count,
        "warnings": token_errors,
    }


def trigger_monarch_sync(family_id: int = 0, db_path: Any = None) -> Dict[str, Any]:
    """Synchronous entrypoint for triggering a financial account sync (Monarch Money and/or SimpleFIN Bridge) for a family."""
    if not family_id or int(family_id) <= 0:
        return {"success": False, "status": "failed", "error": "Valid family_id is required for Monarch sync."}
    target_db = get_db_path(family_id=family_id) if (db_path is None or getattr(db_path, "name", "").startswith("global")) else db_path
    def _run_monarch() -> Dict[str, Any]:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _async_sync_monarch(family_id=family_id, db_path=target_db)).result()
        return loop.run_until_complete(_async_sync_monarch(family_id=family_id, db_path=target_db))

    monarch_res = run_provider_sync(target_db, family_id, "monarch", _run_monarch)

    results: Dict[str, Dict[str, Any]] = {}
    if monarch_res.get("status") != "not_connected":
        results["monarch"] = monarch_res
    try:
        sfin_creds = (
            security.db_load_encrypted(target_db, "simplefin_credentials", family_id=family_id) or {}
            if target_db.exists()
            else {}
        )
        if sfin_creds.get("access_url"):
            from account_sync.simplefin import trigger_simplefin_sync
            results["simplefin"] = trigger_simplefin_sync(family_id=family_id, db_path=target_db)
    except (requests.RequestException, OSError, ValueError, SQLAlchemyError, InvalidToken) as exc:
        # provider isolation: Monarch's committed result must still reach the caller
        logger.warning("SimpleFIN sync raised %s for family %s", type(exc).__name__, family_id)
        results["simplefin"] = {
            "success": False,
            "status": "failed",
            "provider": "simplefin",
            "error": f"SimpleFIN sync failed unexpectedly ({type(exc).__name__}).",
        }
    if not results:
        return monarch_res
    return combine_provider_results(results)


sync_from_monarch = trigger_monarch_sync


async def _async_login_monarch(
    email: str,
    password: str,
    mfa_secret_key: Optional[str] = None,
    family_id: int = 0,
) -> Dict[str, Any]:
    """Logs into Monarch Money with email, password, and optional TOTP secret key, saving session token to encrypted SQLite vault."""
    try:
        from monarchmoney import MonarchMoney
        from monarchmoney.monarchmoney import RequireMFAException
        from monarchmoney.monarchmoney import MonarchMoneyEndpoints
        MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"
        MonarchMoneyEndpoints.getLoginEndpoint = classmethod(lambda cls: "https://api.monarch.com/auth/login/")
        MonarchMoneyEndpoints.getGraphQL = classmethod(lambda cls: "https://api.monarch.com/graphql")
        try:
            from monarchmoney.monarchmoney import CaptchaRequiredException
        except ImportError:
            class CaptchaRequiredException(Exception):
                pass
    except ImportError as ie:
        return {"success": False, "error": f"Monarch library import error ({type(ie).__name__}): {str(ie)}"}

    mm = MonarchMoney()
    db_path = get_db_path(family_id=family_id)
    try:
        await mm.login(
            email=email,
            password=password,
            use_saved_session=False,
            save_session=False,
            mfa_secret_key=mfa_secret_key,
        )
        tok = getattr(mm, "_token", None) or getattr(mm, "token", None)
        security.db_save_encrypted(
            db_path,
            "monarch_credentials",
            "settings",
            {
                "email": email,
                "password": password,
                "mfa_secret_key": mfa_secret_key,
                "token": tok,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            family_id=family_id,
        )
        _persist_vault_token(db_path, family_id, tok, source="settings")
        acc_resp = await mm.get_accounts()
        return {
            "success": True,
            "message": "Successfully authenticated with Monarch Money.",
            "accounts_count": len(acc_resp.get("accounts", [])),
        }
    except RequireMFAException:
        return {
            "success": False,
            "requires_mfa": True,
            "message": "Multi-Factor Authentication (2FA) is required. Please provide your 6-digit code from your authenticator app.",
        }
    except CaptchaRequiredException:
        return {
            "success": False,
            "error": "Monarch has requested a CAPTCHA. Turn on 2FA on Monarch Money to use TOTP secret key for permanent CAPTCHA bypass, or use a persistent session token.",
        }
    except _MONARCH_REQUEST_ERRORS as e:
        err_msg = str(e)
        if "429" in err_msg or "Too Many Requests" in err_msg:
            return {
                "success": False,
                "error": "Monarch has temporarily rate-limited login requests (HTTP 429: Too Many Requests) due to multiple recent login calls from this server IP. Please wait 5–10 minutes for Monarch's rate limit window to reset before submitting again, or connect instantly using a session token.",
            }
        if "405" in err_msg or "Method Not Allowed" in err_msg:
            return {
                "success": False,
                "error": "Monarch API login routing error (HTTP 405: Method Not Allowed). The endpoint has been patched to https://api.monarch.com/auth/login/. Please deploy changes or connect directly using a browser session token.",
            }
        return {"success": False, "error": err_msg}


async def _async_mfa_monarch(
    email: str,
    password: str,
    code: str,
    family_id: int = 0,
) -> Dict[str, Any]:
    """Completes 2FA for Monarch Money and persists the trusted device token in the encrypted SQLite vault."""
    try:
        from monarchmoney import MonarchMoney
        from monarchmoney.monarchmoney import MonarchMoneyEndpoints
        MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"
        MonarchMoneyEndpoints.getLoginEndpoint = classmethod(lambda cls: "https://api.monarch.com/auth/login/")
        MonarchMoneyEndpoints.getGraphQL = classmethod(lambda cls: "https://api.monarch.com/graphql")
    except ImportError as ie:
        return {"success": False, "error": f"Monarch library import error ({type(ie).__name__}): {str(ie)}"}

    mm = MonarchMoney()
    db_path = get_db_path(family_id=family_id)
    try:
        try:
            await mm.multi_factor_authenticate(email=email, password=password, code=code, trusted_device=True)
        except TypeError:
            await mm.multi_factor_authenticate(email=email, password=password, code=code)
        tok = getattr(mm, "_token", None) or getattr(mm, "token", None)
        security.db_save_encrypted(
            db_path,
            "monarch_credentials",
            "settings",
            {
                "email": email,
                "password": password,
                "token": tok,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            family_id=family_id,
        )
        _persist_vault_token(db_path, family_id, tok, source="settings")
        acc_resp = await mm.get_accounts()
        return {
            "success": True,
            "message": "Successfully authenticated with Monarch Money as a trusted device.",
            "accounts_count": len(acc_resp.get("accounts", [])),
        }
    except _MONARCH_REQUEST_ERRORS as e:
        err_msg = str(e)
        if "429" in err_msg or "Too Many Requests" in err_msg:
            return {
                "success": False,
                "error": "Monarch has temporarily rate-limited login requests (HTTP 429: Too Many Requests). Please wait 5–10 minutes for Monarch's rate limit window to reset.",
            }
        return {"success": False, "error": err_msg}


def login_monarch(
    email: str,
    password: str,
    mfa_secret_key: Optional[str] = None,
    family_id: int = 0,
) -> Dict[str, Any]:
    """Synchronous wrapper for Monarch login."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(
                asyncio.run,
                _async_login_monarch(email, password, mfa_secret_key, family_id=family_id),
            ).result()
    else:
        return loop.run_until_complete(
            _async_login_monarch(email, password, mfa_secret_key, family_id=family_id)
        )


def mfa_monarch(email: str, password: str, code: str, family_id: int = 0) -> Dict[str, Any]:
    """Synchronous wrapper for Monarch MFA verification."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(
                asyncio.run,
                _async_mfa_monarch(email, password, code, family_id=family_id),
            ).result()
    else:
        return loop.run_until_complete(_async_mfa_monarch(email, password, code, family_id=family_id))
