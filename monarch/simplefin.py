"""
SimpleFIN Bridge (`beta-bridge.simplefin.org`) financial aggregator client.
Exchanges a Base64 SimpleFIN Setup Token for a persistent HTTPS Access URL, stores it
in the per-family encrypted SQLite vault, and normalizes SimpleFIN accounts & holdings
into the Family Office balance sheet tables (`monarch_accounts` and `monarch_holdings`).
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlunparse

import requests

import security
from monarch.categorizer import get_db_path
from monarch.simplefin_helpers import (
    _validate_simplefin_url,
    _infer_simplefin_account_type,
    _normalize_simplefin_payload,
    _reconstruct_simplefin_balance_history,
)

logger = logging.getLogger(__name__)


def claim_simplefin_setup_token(setup_token_or_url: str) -> Dict[str, Any]:
    """
    Accepts either a Base64-encoded SimpleFIN Setup Token or an already-claimed
    `https://user:pass@beta-bridge.simplefin.org/simplefin` Access URL.
    Returns `{"success": True, "access_url": "..."}` or `{"success": False, "error": "..."}`.
    """
    raw = (setup_token_or_url or "").strip()
    if not raw:
        return {"success": False, "error": "SimpleFIN Setup Token is required."}

    if raw.startswith("https://") and "@" in raw:
        ok, err, parsed = _validate_simplefin_url(raw)
        if not ok or parsed is None:
            return {"success": False, "error": err}
        if not parsed.username or not parsed.password:
            return {
                "success": False,
                "error": "SimpleFIN Access URL is missing embedded authentication credentials.",
            }
        return {"success": True, "access_url": raw.rstrip("/")}

    try:
        compact = "".join(raw.split())
        pad_len = (-len(compact)) % 4
        if pad_len:
            compact += "=" * pad_len
        decoded_bytes = base64.b64decode(compact, validate=False)
        claim_url = decoded_bytes.decode("utf-8").strip()
    except Exception:
        return {
            "success": False,
            "error": "Invalid SimpleFIN Setup Token. Please copy the Base64 Setup Token from SimpleFIN Bridge.",
        }

    ok, err, _ = _validate_simplefin_url(claim_url)
    if not ok:
        return {"success": False, "error": err}

    try:
        resp = requests.post(
            claim_url,
            headers={"Content-Length": "0", "Accept": "text/plain"},
            timeout=20,
        )
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to reach SimpleFIN Bridge to claim token: {exc}",
        }

    if resp.status_code == 403 or resp.status_code != 200:
        return {
            "success": False,
            "error": (
                f"SimpleFIN Setup Token was rejected (HTTP {resp.status_code}). "
                "Setup tokens are single-use—please generate a fresh Setup Token in SimpleFIN Bridge."
            ),
        }

    access_url = (resp.text or "").strip().rstrip("/")
    ok_acc, err_acc, parsed_acc = _validate_simplefin_url(access_url)
    if not ok_acc or parsed_acc is None or not parsed_acc.username or not parsed_acc.password:
        return {
            "success": False,
            "error": err_acc or "SimpleFIN Bridge returned an invalid Access URL.",
        }

    return {"success": True, "access_url": access_url}


def fetch_simplefin_data(access_url: str, start_date: Optional[int] = None) -> Dict[str, Any]:
    """Fetches `/accounts` JSON from SimpleFIN Bridge using the household's Access URL."""
    from datetime import timedelta

    ok, err, parsed = _validate_simplefin_url(access_url)
    if not ok or parsed is None:
        return {"success": False, "error": err}

    username = parsed.username or ""
    password = parsed.password or ""
    if not username or not password:
        return {"success": False, "error": "SimpleFIN Access URL is missing credentials."}

    clean_netloc = parsed.hostname or "beta-bridge.simplefin.org"
    if parsed.port:
        clean_netloc = f"{clean_netloc}:{parsed.port}"
    base_path = (parsed.path or "").rstrip("/")
    accounts_path = f"{base_path}/accounts" if not base_path.endswith("/accounts") else base_path
    endpoint_url = urlunparse(("https", clean_netloc, accounts_path, "", "", ""))

    eff_start = (
        int(start_date)
        if start_date is not None
        else int((datetime.now(timezone.utc) - timedelta(days=90)).timestamp())
    )

    try:
        resp = requests.get(
            endpoint_url,
            auth=(username, password),
            headers={"Accept": "application/json"},
            params={"start-date": str(eff_start)},
            timeout=30,
        )
    except Exception as exc:
        return {"success": False, "error": f"Failed connecting to SimpleFIN Bridge: {exc}"}

    if resp.status_code == 403 or resp.status_code == 401:
        return {
            "success": False,
            "error": "SimpleFIN access token was revoked or unauthorized (HTTP 403). Please reconnect with a new Setup Token.",
        }
    if resp.status_code != 200:
        return {
            "success": False,
            "error": f"SimpleFIN Bridge returned HTTP {resp.status_code}.",
        }

    try:
        payload = resp.json()
    except Exception:
        return {"success": False, "error": "SimpleFIN Bridge returned invalid JSON."}

    if not isinstance(payload, dict):
        return {"success": False, "error": "Unexpected response format from SimpleFIN Bridge."}

    return {"success": True, "data": payload}


def connect_simplefin(setup_token_or_url: str, family_id: int = 0) -> Dict[str, Any]:
    """
    Claims a SimpleFIN Setup Token (or validates an Access URL), stores it in the
    per-family encrypted SQLite vault, and runs an initial account & holdings sync.
    """
    if not family_id or int(family_id) <= 0:
        return {"success": False, "error": "Valid family session required."}

    claim_res = claim_simplefin_setup_token(setup_token_or_url)
    if not claim_res.get("success"):
        return claim_res

    access_url = str(claim_res["access_url"])
    db_path = get_db_path(family_id=family_id)
    now_str = datetime.now(timezone.utc).isoformat()

    security.db_save_encrypted(
        db_path,
        "simplefin_credentials",
        "settings",
        {
            "access_url": access_url,
            "updated_at": now_str,
        },
        family_id=family_id,
    )

    sync_res = trigger_simplefin_sync(family_id=family_id)
    if not sync_res.get("success"):
        return sync_res

    return {
        "success": True,
        "provider": "simplefin",
        "message": f"Connected to SimpleFIN Bridge ({sync_res.get('accounts_count', 0)} accounts synced).",
        "accounts_count": sync_res.get("accounts_count", 0),
        "holdings_count": sync_res.get("holdings_count", 0),
        "timestamp": sync_res.get("timestamp", now_str),
    }


def trigger_simplefin_sync(family_id: int = 0, db_path: Any = None) -> Dict[str, Any]:
    """Synchronizes SimpleFIN accounts and holdings for `family_id` into the encrypted SQLite database."""
    if not family_id or int(family_id) <= 0:
        return {"success": False, "error": "Valid family_id is required for SimpleFIN sync."}

    target_db = db_path if db_path is not None else get_db_path(family_id=family_id)
    creds = security.db_load_encrypted(target_db, "simplefin_credentials", family_id=family_id) or {}
    access_url = str(creds.get("access_url") or "").strip()
    if not access_url:
        return {
            "success": False,
            "error": "No SimpleFIN Bridge connection configured for this family. Please paste a Setup Token in Settings.",
        }

    fetch_res = fetch_simplefin_data(access_url)
    if not fetch_res.get("success"):
        return fetch_res

    import db

    existing_accounts = db.accounts.list_accounts(family_id=family_id, db_path=target_db) or []
    existing_nw_flags = {
        str(a.get("id")): bool(a.get("includeInNetWorth", True))
        for a in existing_accounts
        if a.get("id")
    }

    sfin_data = fetch_res.get("data") or {}
    accounts, holdings_by_account = _normalize_simplefin_payload(
        sfin_data, existing_nw_flags=existing_nw_flags
    )

    now_str = datetime.now(timezone.utc).isoformat()
    db.accounts.replace_accounts(
        family_id=family_id,
        accounts=accounts,
        db_path=target_db,
        provider="simplefin",
    )
    db.accounts.replace_holdings(
        family_id=family_id,
        holdings_by_account=holdings_by_account,
        db_path=target_db,
        provider="simplefin",
    )

    try:
        reconstructed = _reconstruct_simplefin_balance_history(sfin_data)
        if reconstructed:
            db.accounts.record_account_balance_snapshots(
                family_id=family_id,
                snapshots=reconstructed,
                db_path=target_db,
            )
    except Exception as exc:
        logger.debug("SimpleFIN balance history reconstruction skipped for family %s: %s", family_id, exc)

    sfin_errors = sfin_data.get("errors") if isinstance(sfin_data.get("errors"), list) else []
    sync_meta = {
        "timestamp": now_str,
        "status": "success",
        "provider": "simplefin",
        "accounts_count": len(accounts),
        "holdings_accounts_count": len(holdings_by_account),
        "warnings": [str(e) for e in sfin_errors[:5]],
    }
    security.db_save_encrypted(
        target_db,
        "simplefin_sync_metadata",
        "simplefin_sync",
        sync_meta,
        family_id=family_id,
    )

    all_accounts = db.accounts.list_accounts(family_id=family_id, db_path=target_db) or []
    security.db_save_encrypted(
        target_db,
        "last_sync_metadata",
        "simplefin_sync",
        {
            "timestamp": now_str,
            "status": "success",
            "provider": "simplefin",
            "accounts_count": len(all_accounts),
            "holdings_accounts_count": len(holdings_by_account),
        },
        family_id=family_id,
    )

    return {
        "success": True,
        "provider": "simplefin",
        "timestamp": now_str,
        "accounts_count": len(accounts),
        "holdings_count": sum(len(h) for h in holdings_by_account.values()),
        "warnings": sync_meta["warnings"],
    }


sync_simplefin_accounts = trigger_simplefin_sync


def disconnect_simplefin(family_id: int = 0, remove_accounts: bool = True) -> Dict[str, Any]:
    """Disconnects SimpleFIN Bridge for `family_id` and optionally removes synced `sfin_*` accounts."""
    if not family_id or int(family_id) <= 0:
        return {"success": False, "error": "Valid family_id is required."}

    db_path = get_db_path(family_id=family_id)
    security.db_save_encrypted(db_path, "simplefin_credentials", "settings", {}, family_id=family_id)
    security.db_save_encrypted(db_path, "simplefin_sync_metadata", "settings", {}, family_id=family_id)

    if remove_accounts:
        import db
        db.accounts.replace_accounts(family_id=family_id, accounts=[], db_path=db_path, provider="simplefin")
        db.accounts.replace_holdings(family_id=family_id, holdings_by_account={}, db_path=db_path, provider="simplefin")

    return {
        "success": True,
        "message": "SimpleFIN Bridge disconnected.",
    }


def get_simplefin_status(family_id: int = 0, db_path: Any = None) -> Dict[str, Any]:
    """Returns structured connection status for SimpleFIN Bridge for SSR and API responses."""
    default_status = {
        "is_connected": False,
        "status_text": "Not Connected",
        "last_sync": "Never",
        "accounts_count": 0,
        "auth_mode": "None",
        "warnings": [],
    }
    if not family_id or int(family_id) <= 0:
        return default_status

    target_db = db_path if db_path is not None else get_db_path(family_id=family_id)
    if not target_db.exists():
        return default_status

    try:
        creds = security.db_load_encrypted(target_db, "simplefin_credentials", family_id=family_id) or {}
        sync_meta = security.db_load_encrypted(target_db, "simplefin_sync_metadata", family_id=family_id) or {}
        has_access_url = bool(creds.get("access_url"))

        import db
        all_accs = db.accounts.list_accounts(family_id=family_id, db_path=target_db) or []
        sfin_accs = [
            a for a in all_accs
            if str(a.get("provider") or "").lower() == "simplefin" or str(a.get("id") or "").startswith("sfin_")
        ]

        raw_ts = sync_meta.get("timestamp") or creds.get("updated_at")
        last_sync_str = "Never"
        if raw_ts:
            try:
                dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                last_sync_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                last_sync_str = str(raw_ts)

        return {
            "is_connected": has_access_url,
            "status_text": "Connected & Operational" if has_access_url else "Not Connected",
            "last_sync": last_sync_str if has_access_url else "Never",
            "accounts_count": len(sfin_accs) if sfin_accs else int(sync_meta.get("accounts_count") or 0),
            "auth_mode": "SimpleFIN Bridge Token (MX)" if has_access_url else "None",
            "warnings": sync_meta.get("warnings") or [],
        }
    except Exception as exc:
        logger.warning("Failed to build SimpleFIN status for family %s: %s", family_id, exc)
        return default_status
