"""
Monarch Money sign-in: email/password (with optional TOTP secret) and 2FA code verification.
Saves the credentials and session token to the per-family encrypted SQLite vault.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import security
from account_sync.categorizer import get_db_path
from account_sync.monarch_sync import MONARCH_REQUEST_ERRORS as _MONARCH_REQUEST_ERRORS, _persist_vault_token


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
