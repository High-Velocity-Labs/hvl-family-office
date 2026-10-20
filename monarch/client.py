"""
Monarch GraphQL client, authentication, and encrypted SQLite vault session persistence.
Eliminates unencrypted `.mm/session_family_{id}.pickle` files on disk in favor of storing
and resuming session tokens directly inside the per-family encrypted SQLite store.
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

import security
from monarch.categorizer import get_db_path
from monarch.client_graphql import (
    SESSION_DIR,
    SESSION_FILE,
    get_family_session_file,
    _persist_vault_token,
    _async_sync_monarch,
)


def trigger_monarch_sync(family_id: int = 0, db_path: Any = None) -> Dict[str, Any]:
    """Synchronous entrypoint for triggering a financial account sync (Monarch Money and/or SimpleFIN Bridge) for a family."""
    target_db = get_db_path(family_id=family_id) if (db_path is None or getattr(db_path, "name", "").startswith("global")) else db_path
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            monarch_res = pool.submit(asyncio.run, _async_sync_monarch(family_id=family_id, db_path=target_db)).result()
    else:
        monarch_res = loop.run_until_complete(_async_sync_monarch(family_id=family_id, db_path=target_db))

    try:
        target_db = db_path if db_path is not None else get_db_path()
        if target_db.exists() and family_id:
            sfin_creds = security.db_load_encrypted(target_db, "simplefin_credentials", family_id=family_id) or {}
            if sfin_creds.get("access_url"):
                from monarch.simplefin import trigger_simplefin_sync
                sfin_res = trigger_simplefin_sync(family_id=family_id, db_path=target_db)
                if not monarch_res.get("success"):
                    if sfin_res.get("success"):
                        return sfin_res
                elif sfin_res.get("success"):
                    monarch_res["accounts_count"] = int(monarch_res.get("accounts_count", 0)) + int(sfin_res.get("accounts_count", 0))
                    monarch_res["holdings_count"] = int(monarch_res.get("holdings_count", 0)) + int(sfin_res.get("holdings_count", 0))
                    monarch_res["simplefin_synced"] = True
    except Exception:
        pass

    return monarch_res


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
        try:
            from monarchmoney.monarchmoney import MonarchMoneyEndpoints
            MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"
            MonarchMoneyEndpoints.getLoginEndpoint = classmethod(lambda cls: "https://api.monarch.com/auth/login/")
            MonarchMoneyEndpoints.getGraphQL = classmethod(lambda cls: "https://api.monarch.com/graphql")
        except Exception:
            pass
        try:
            from monarchmoney.monarchmoney import CaptchaRequiredException
        except ImportError:
            class CaptchaRequiredException(Exception):
                pass
    except Exception as ie:
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
    except Exception as e:
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
        try:
            from monarchmoney.monarchmoney import MonarchMoneyEndpoints
            MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"
            MonarchMoneyEndpoints.getLoginEndpoint = classmethod(lambda cls: "https://api.monarch.com/auth/login/")
            MonarchMoneyEndpoints.getGraphQL = classmethod(lambda cls: "https://api.monarch.com/graphql")
        except Exception:
            pass
    except Exception as ie:
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
    except Exception as e:
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
