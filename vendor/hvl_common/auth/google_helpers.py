"""
Helper utilities for Google OAuth 2.0, Google Drive appDataFolder vault storage,
redirect URI construction, cookie cleanup, and Demo Universe session transitions.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any, Dict, Optional, Tuple

import requests
from flask import request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

GOOGLE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"

_HTTP_SESSION = requests.Session()
_GOOGLE_AUTH_REQUEST = google_requests.Request(session=_HTTP_SESSION)
_APPDATA_FILE_ID_CACHE: Dict[Tuple[str, str], str] = {}


def _token_cache_key(access_token: str, filename: str) -> Tuple[str, str]:
    return (access_token[-16:] if len(access_token) >= 16 else access_token, filename)


def read_google_appdata_json(
    access_token: str,
    filename: str = "hvl_vault_key.json",
    timeout: int = 8,
) -> Optional[Dict[str, Any]]:
    """Reads and parses a JSON file stored in the user's hidden Google Drive appDataFolder."""
    if not access_token:
        return None
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "spaces": "appDataFolder",
        "q": f"name = '{filename}' and trashed = false",
        "fields": "files(id, name, modifiedTime)",
        "orderBy": "modifiedTime desc",
        "pageSize": 5,
    }
    try:
        list_resp = _HTTP_SESSION.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params=params,
            timeout=timeout,
        )
        if list_resp.status_code != 200:
            return None
        files = (list_resp.json() or {}).get("files") or []
        file_id = files[0].get("id") if files else None
        if not file_id:
            return None
        _APPDATA_FILE_ID_CACHE[_token_cache_key(access_token, filename)] = str(file_id)
        media_resp = _HTTP_SESSION.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
            headers=headers,
            timeout=timeout,
        )
        if media_resp.status_code != 200:
            return None
        data = media_resp.json()
        return data if isinstance(data, dict) else None
    except Exception as e:
        print(f"[hvl_common.auth.google] Failed to read appDataFolder file '{filename}': {e}")
        return None


def write_google_appdata_json(
    access_token: str,
    payload: Dict[str, Any],
    filename: str = "hvl_vault_key.json",
    timeout: int = 8,
) -> bool:
    """Creates or updates a JSON file in the user's hidden Google Drive appDataFolder."""
    if not access_token or not isinstance(payload, dict):
        return False
    headers = {"Authorization": f"Bearer {access_token}"}
    cache_key = _token_cache_key(access_token, filename)
    file_id: Optional[str] = _APPDATA_FILE_ID_CACHE.get(cache_key)
    try:
        if not file_id:
            params = {
                "spaces": "appDataFolder",
                "q": f"name = '{filename}' and trashed = false",
                "fields": "files(id, name, modifiedTime)",
                "orderBy": "modifiedTime desc",
                "pageSize": 5,
            }
            list_resp = _HTTP_SESSION.get(
                "https://www.googleapis.com/drive/v3/files",
                headers=headers,
                params=params,
                timeout=timeout,
            )
            if list_resp.status_code != 200:
                return False
            files = (list_resp.json() or {}).get("files") or []
            file_id = files[0].get("id") if files else None

        if not file_id:
            create_resp = _HTTP_SESSION.post(
                "https://www.googleapis.com/drive/v3/files",
                headers={**headers, "Content-Type": "application/json"},
                json={"name": filename, "parents": ["appDataFolder"], "mimeType": "application/json"},
                timeout=timeout,
            )
            if create_resp.status_code not in (200, 201):
                return False
            file_id = (create_resp.json() or {}).get("id")
            if not file_id:
                return False

        _APPDATA_FILE_ID_CACHE[cache_key] = str(file_id)
        upload_resp = _HTTP_SESSION.patch(
            f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
            timeout=timeout,
        )
        return upload_resp.status_code in (200, 201)
    except Exception as e:
        print(f"[hvl_common.auth.google] Failed to write appDataFolder file '{filename}': {e}")
        return False


def verify_google_id_token(token: str, client_id: str) -> Optional[Dict[str, Any]]:
    """
    Cryptographically verifies Google ID Token using Google's public certificates.
    Returns token claims dictionary if valid, None otherwise.
    """
    if not token or not client_id:
        return None
    try:
        id_info = id_token.verify_oauth2_token(token, _GOOGLE_AUTH_REQUEST, client_id)
        if id_info.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
            return None
        if id_info.get("email_verified") is False:
            return None
        return id_info
    except Exception as e:
        print(f"[hvl_common.auth.google] ID Token verification failed: {e}")
        return None


def build_redirect_uri(explicit_uri: Optional[str] = None) -> str:
    """Computes redirect URI based on current request host or explicit override."""
    if explicit_uri and explicit_uri.strip():
        return explicit_uri.strip()
    host = request.host
    is_local = any(h in host.lower() for h in ["127.0.0.1", "localhost", "192.168.", "10.", "172."])
    scheme = "https" if request.headers.get("X-Forwarded-Proto") == "https" or not is_local else "http"
    return f"{scheme}://{host}/auth/google/callback"


def build_google_auth_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    scope: str = "openid email",
    prompt: str = "select_account",
    access_type: str = "online",
) -> str:
    """Constructs standard Google OAuth 2.0 consent URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "access_type": access_type,
        "prompt": prompt,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    timeout: int = 10,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Exchanges authorization code for Google token dictionary. Returns (tokens_dict, error_message)."""
    token_data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        resp = _HTTP_SESSION.post("https://oauth2.googleapis.com/token", data=token_data, timeout=timeout)
        data = resp.json()
        if resp.status_code != 200:
            return None, str(data.get("error_description") or data.get("error") or f"HTTP {resp.status_code}")
        return data, None
    except Exception as e:
        return None, str(e)


def clear_auth_and_vault_cookies(response: Any, extra_cookies: Tuple[str, ...] | list[str] = ()) -> Any:
    """Deletes standard HVL vault FEK cookies and any extra cookies from a Flask response."""
    cookies = {"hvl_vault_fek", "hvl_vault_fek_beta", *(extra_cookies or ())}
    for cookie_name in cookies:
        if cookie_name and hasattr(response, "delete_cookie"):
            response.delete_cookie(str(cookie_name), path="/")
    return response


def enter_demo_session(
    session_obj: Any,
    *,
    user: str = "Demo Guest",
    user_display: str = "Demo Guest",
    role: str = "admin",
    tenant_id: int = 1,
    tenant_key: str = "household_id",
) -> Any:
    """Transitions a Flask/dict session into the isolated Demo Universe, preserving any real authenticated session."""
    was_auth = bool(session_obj.get("authenticated") and not session_obj.get("is_demo"))
    prev_user = session_obj.get("user") if was_auth else session_obj.get("prev_user")
    prev_email = (session_obj.get("user_email") or session_obj.get("member_email")) if was_auth else session_obj.get("prev_user_email")
    prev_role = (session_obj.get("user_role") or session_obj.get("role")) if was_auth else session_obj.get("prev_user_role")
    prev_tid = (session_obj.get(tenant_key) or session_obj.get(f"user_{tenant_key}")) if was_auth else session_obj.get("prev_user_tenant_id")
    prev_method = session_obj.get("auth_method") if was_auth else session_obj.get("prev_auth_method")

    session_obj.clear()
    if prev_user:
        session_obj["prev_user"] = prev_user
        session_obj["prev_user_email"] = prev_email
        session_obj["prev_user_role"] = prev_role
        session_obj["prev_user_tenant_id"] = prev_tid
        session_obj["prev_auth_method"] = prev_method

    session_obj["authenticated"] = True
    session_obj["is_demo"] = True
    session_obj["universe"] = "demo"
    session_obj["user"] = user
    session_obj["user_display"] = user_display
    session_obj["role"] = role
    session_obj["user_role"] = role
    session_obj[tenant_key] = int(tenant_id)
    session_obj["auth_method"] = "Demo Mode"
    if hasattr(session_obj, "permanent"):
        session_obj.permanent = False
    return session_obj


def exit_demo_session(session_obj: Any, *, tenant_key: str = "household_id") -> bool:
    """Exits Demo Universe, restoring any previous authenticated session (returns True) or clearing session (returns False)."""
    if session_obj.get("prev_user"):
        prev_user = session_obj.pop("prev_user")
        prev_email = session_obj.pop("prev_user_email", "") or ""
        prev_role = session_obj.pop("prev_user_role", "admin") or "admin"
        prev_tid = int(session_obj.pop("prev_user_tenant_id", 1) or 1)
        prev_method = session_obj.pop("prev_auth_method", "Authenticated") or "Authenticated"
        session_obj.clear()
        session_obj["user"] = prev_user
        session_obj["user_email"] = prev_email
        session_obj["member_email"] = prev_email
        session_obj["user_role"] = prev_role
        session_obj["role"] = prev_role
        session_obj[tenant_key] = prev_tid
        session_obj[f"user_{tenant_key}"] = prev_tid
        session_obj["universe"] = "public"
        session_obj["is_demo"] = False
        session_obj["authenticated"] = True
        session_obj["auth_method"] = prev_method
        if hasattr(session_obj, "permanent"):
            session_obj.permanent = True
        return True
    session_obj.clear()
    return False
