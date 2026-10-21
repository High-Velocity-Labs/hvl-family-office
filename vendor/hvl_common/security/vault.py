"""
Shared Zero-Knowledge Household FEK Vault, Cookie Transport, and Multi-App Google Drive `appDataFolder` Escrow.

Supports storing separate per-application FEKs (e.g. `"fek"` for Family Office, `"assistant_fek"` for Assistant)
inside the user's shared Google Drive `appDataFolder` (`hvl_vault_key.json`) so:
1. Enabling Support Access on one app only escrows that app's FEK in its local SQLite DB, keeping other apps
   100% cryptographically locked on disk.
2. During Google OAuth sign-in, an app can read both its own FEK and peer HVL app FEKs from `appDataFolder`
   (allowing Assistant to provision 1-Click Family Office MCP tokens even when Family Office has
   `support_access_enabled = 0` and no key on disk).
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional, Sequence, Union
from flask import g, has_request_context, request, session

from hvl_common.auth.google import read_google_appdata_json, write_google_appdata_json
from hvl_common.security.crypto import (
    VAULT_COOKIE_NAME,
    get_fernet,
    parse_fernet_keys,
    unwrap_cookie_fek,
    wrap_cookie_fek,
)


def get_vault_cookie_name(is_beta: bool = False) -> str:
    """Returns instance-scoped vault FEK cookie name ('hvl_vault_fek_beta' on beta, 'hvl_vault_fek' on prod)."""
    return "hvl_vault_fek_beta" if is_beta else VAULT_COOKIE_NAME


def get_vault_appdata_filename(is_beta: bool = False) -> str:
    """Returns instance-scoped Google Drive appDataFolder vault key filename."""
    env_override = os.getenv("VAULT_APPDATA_FILENAME", "").strip()
    if env_override:
        return env_override
    return "hvl_vault_key_beta.json" if is_beta else "hvl_vault_key.json"


def stash_request_vault_fek(
    household_id: int,
    raw_fek: Union[bytes, str],
    secret_key: Union[bytes, str],
    *,
    session_id_key: str = "vault_fek_family_id",
) -> str:
    """
    Wraps `raw_fek` for cookie/session transport and stashes it in Flask `session` and `g`
    so the outgoing HTTP response attaches the HttpOnly `hvl_vault_fek` cookie.
    """
    eff_fek = raw_fek.encode("utf-8") if isinstance(raw_fek, str) else bytes(raw_fek)
    wrapped = wrap_cookie_fek(eff_fek, secret_key)
    hid = int(household_id)
    if has_request_context():
        session["vault_fek"] = wrapped
        session[session_id_key] = hid
        session["vault_fek_household_id"] = hid
        session["vault_fek_family_id"] = hid
        active_feks = getattr(g, "_active_vault_feks", None)
        if not isinstance(active_feks, dict):
            active_feks = {}
            g._active_vault_feks = active_feks
        active_feks[hid] = eff_fek
        g._active_vault_fek = (hid, eff_fek)
        g._pending_vault_cookie = wrapped
    return wrapped


def get_request_vault_fek(
    household_id: int,
    secret_keys: Union[bytes, str, Sequence[Union[bytes, str]]],
    *,
    is_beta: bool = False,
) -> Optional[bytes]:
    """Resolves the active household FEK from Flask `g`, `session`, or `hvl_vault_fek` cookie."""
    if not household_id or int(household_id) <= 0 or not has_request_context():
        return None
    hid = int(household_id)

    active_feks = getattr(g, "_active_vault_feks", None)
    if isinstance(active_feks, dict) and hid in active_feks and active_feks[hid]:
        return active_feks[hid]
    active_tuple = getattr(g, "_active_vault_fek", None)
    if isinstance(active_tuple, tuple) and len(active_tuple) == 2 and active_tuple[0] == hid and active_tuple[1]:
        return active_tuple[1]

    sess_hid = session.get("vault_fek_household_id") or session.get("vault_fek_family_id")
    if sess_hid is not None and int(sess_hid or 0) != hid:
        return None

    cookie_name = get_vault_cookie_name(is_beta=is_beta)
    candidate_tokens = [
        session.get("vault_fek"),
        request.cookies.get(cookie_name),
        request.cookies.get(VAULT_COOKIE_NAME),
    ]

    if isinstance(secret_keys, (bytes, str)):
        raw_list: Sequence[Union[bytes, str]] = [secret_keys]
    else:
        raw_list = list(secret_keys)

    keks: list[Union[bytes, str]] = []
    for item in raw_list:
        if not item:
            continue
        for parsed in parse_fernet_keys(item):
            if parsed not in keks:
                keks.append(parsed)
        if item not in keks:
            keks.append(item)

    for tok in candidate_tokens:
        if not tok:
            continue
        for k in keks:
            unwrapped = unwrap_cookie_fek(str(tok), k)
            if unwrapped:
                if not isinstance(active_feks, dict):
                    active_feks = {}
                    g._active_vault_feks = active_feks
                active_feks[hid] = unwrapped
                g._active_vault_fek = (hid, unwrapped)
                return unwrapped
    return None


def attach_vault_cookie(
    response: Any,
    *,
    is_beta: bool = False,
    is_secure: Optional[bool] = None,
    max_age: int = 400 * 24 * 3600,
) -> Any:
    """Attaches any pending wrapped FEK cookie from `g._pending_vault_cookie` to the outgoing response."""
    if not has_request_context():
        return response
    cookie_val = getattr(g, "_pending_vault_cookie", None)
    if cookie_val:
        sec = (
            bool(request.is_secure or request.headers.get("X-Forwarded-Proto") == "https")
            if is_secure is None
            else bool(is_secure)
        )
        response.set_cookie(
            get_vault_cookie_name(is_beta=is_beta),
            str(cookie_val),
            max_age=max_age,
            httponly=True,
            secure=sec,
            samesite="Lax",
        )
    return response


def extract_appdata_fek(
    appdata: Optional[Dict[str, Any]],
    household_id: int,
    *,
    app_key_slot: str = "fek",
) -> Optional[bytes]:
    """
    Extracts and validates a Fernet FEK for `household_id` and `app_key_slot` from a Google Drive
    `appDataFolder` JSON dictionary.
    - `"fek"`: primary Family Office FEK (`appdata["fek_map"][str(hid)]` or `appdata["fek"]`)
    - `"assistant_fek"` (or custom slot): checks `appdata["assistant_fek_map"][str(hid)]` or `appdata["assistant_fek"]`
    """
    if not isinstance(appdata, dict):
        return None
    hid_str = str(int(household_id))
    candidate: Optional[str] = None

    map_key = "fek_map" if app_key_slot == "fek" else f"{app_key_slot}_map"
    slot_map = appdata.get(map_key)
    if isinstance(slot_map, dict) and hid_str in slot_map:
        candidate = str(slot_map[hid_str] or "").strip()
    elif appdata.get(app_key_slot):
        stored_fid = appdata.get("family_id")
        if app_key_slot != "fek" or stored_fid is None or int(stored_fid or 0) == int(household_id):
            candidate = str(appdata[app_key_slot]).strip()

    if not candidate:
        return None
    try:
        raw_bytes = candidate.encode("utf-8")
        get_fernet(raw_bytes)
        return raw_bytes
    except Exception:
        return None


def sync_appdata_fek(
    access_token: str,
    household_id: int,
    raw_fek: Union[bytes, str],
    *,
    app_key_slot: str = "fek",
    is_beta: bool = False,
    filename: Optional[str] = None,
    existing_appdata: Optional[Dict[str, Any]] = None,
    already_read: bool = False,
    read_fn: Callable[..., Optional[Dict[str, Any]]] = read_google_appdata_json,
    write_fn: Callable[..., bool] = write_google_appdata_json,
) -> Optional[Dict[str, Any]]:
    """
    Merges and writes `raw_fek` under `app_key_slot` (and `<app_key_slot>_map[str(household_id)]`)
    inside the user's shared Google Drive `appDataFolder` JSON file without clobbering sibling HVL app keys.
    Returns the merged payload dictionary on success, or None if the write fails.
    """
    if not access_token or not raw_fek:
        return None
    target_file = filename or get_vault_appdata_filename(is_beta=is_beta)
    fek_str = raw_fek.decode("utf-8") if isinstance(raw_fek, bytes) else str(raw_fek).strip()
    hid = int(household_id)

    payload: Dict[str, Any] = {}
    if isinstance(existing_appdata, dict):
        current: Optional[Dict[str, Any]] = existing_appdata
    elif already_read:
        current = None
    else:
        current = read_fn(access_token, filename=target_file)
    if isinstance(current, dict):
        payload.update(current)

    if app_key_slot == "fek":
        payload["family_id"] = hid
        payload["fek"] = fek_str
        fek_map = dict(payload.get("fek_map") or {}) if isinstance(payload.get("fek_map"), dict) else {}
        fek_map[str(hid)] = fek_str
        payload["fek_map"] = fek_map
    else:
        payload[app_key_slot] = fek_str
        map_key = f"{app_key_slot}_map"
        slot_map = dict(payload.get(map_key) or {}) if isinstance(payload.get(map_key), dict) else {}
        slot_map[str(hid)] = fek_str
        payload[map_key] = slot_map
        payload.setdefault("family_id", hid)

    ok = write_fn(access_token, payload, filename=target_file)
    return payload if ok else None
