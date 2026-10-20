"""
Google OAuth 2.0 & Google Identity Services (One Tap) reusable authentication module.
Shared between multiple High Velocity Labs applications (Family Office, Fantasy Assistant, etc.).
"""

from __future__ import annotations

import json
import os
import secrets
import urllib.parse
from typing import Any, Callable, Dict, Optional, Tuple, Union

import requests
from flask import Blueprint, jsonify, make_response, redirect, request, session
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

GOOGLE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"


def read_google_appdata_json(
    access_token: str,
    filename: str = "hvl_vault_key.json",
    timeout: int = 8,
) -> Optional[Dict[str, Any]]:
    """
    Reads and parses a JSON file stored in the user's hidden Google Drive appDataFolder.
    Returns the parsed dictionary if found and valid, or None on error/missing.
    """
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
        list_resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params=params,
            timeout=timeout,
        )
        if list_resp.status_code != 200:
            return None
        files = (list_resp.json() or {}).get("files") or []
        if not files:
            return None
        file_id = files[0].get("id")
        if not file_id:
            return None

        media_resp = requests.get(
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
    """
    Creates or updates a JSON file in the user's hidden Google Drive appDataFolder.
    Returns True on success, False otherwise.
    """
    if not access_token or not isinstance(payload, dict):
        return False
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "spaces": "appDataFolder",
        "q": f"name = '{filename}' and trashed = false",
        "fields": "files(id, name, modifiedTime)",
        "orderBy": "modifiedTime desc",
        "pageSize": 5,
    }
    try:
        list_resp = requests.get(
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
            create_resp = requests.post(
                "https://www.googleapis.com/drive/v3/files",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "name": filename,
                    "parents": ["appDataFolder"],
                    "mimeType": "application/json",
                },
                timeout=timeout,
            )
            if create_resp.status_code not in (200, 201):
                return False
            file_id = (create_resp.json() or {}).get("id")
            if not file_id:
                return False

        payload_bytes = json.dumps(payload).encode("utf-8")
        upload_resp = requests.patch(
            f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media",
            headers={**headers, "Content-Type": "application/json"},
            data=payload_bytes,
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
        req = google_requests.Request()
        id_info = id_token.verify_oauth2_token(token, req, client_id)
        if id_info.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
            return None
        return id_info
    except Exception as e:
        print(f"[hvl_common.auth.google] ID Token verification failed: {e}")
        return None


def build_redirect_uri(explicit_uri: Optional[str] = None) -> str:
    """
    Computes redirect URI based on current request host or explicit override.
    Properly detects HTTPS from X-Forwarded-Proto or non-local hosts.
    """
    if explicit_uri and explicit_uri.strip():
        return explicit_uri.strip()

    host = request.host
    host_lower = host.lower()
    is_local = any(h in host_lower for h in ["127.0.0.1", "localhost", "192.168.", "10.", "172."])
    scheme = "http" if is_local else "https"
    if request.headers.get("X-Forwarded-Proto") == "https":
        scheme = "https"
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
    """
    Exchanges authorization code for Google token dictionary.
    Returns (tokens_dict, error_message).
    """
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        resp = requests.post(token_url, data=token_data, timeout=timeout)
        data = resp.json()
        if resp.status_code != 200:
            err = data.get("error_description") or data.get("error") or f"HTTP {resp.status_code}"
            return None, str(err)
        return data, None
    except Exception as e:
        return None, str(e)


def create_google_auth_blueprint(
    get_credentials: Callable[[], Tuple[str, str]],
    on_authenticate: Callable[[str, Dict[str, Any]], Tuple[bool, Union[Dict[str, Any], str, None]]],
    get_redirect_uri: Optional[Callable[[], Optional[str]]] = None,
    name: str = "auth_google",
    url_prefix: str = "/auth/google",
    redirect_on_success: str = "/",
    redirect_on_error: str = "/login?auth_error={error}",
    redirect_on_logout: str = "/login",
    csrf_session_key: str = "oauth_state",
    scope: str = "openid email",
    include_appdata_scope: bool = False,
    after_login_response: Optional[Callable[[Any], Any]] = None,
) -> Blueprint:
    """
    Factory creating a fully functional Google OAuth 2.0 and Google Identity Services Blueprint.

    :param get_credentials: Returns (client_id, client_secret).
    :param on_authenticate: Callback (email, profile_info) -> (is_authorized, user_dict_or_error_msg).
                            This callback is responsible for populating application-specific session state.
    :param get_redirect_uri: Optional callback returning an explicit redirect URI override.
    :param name: Flask Blueprint name.
    :param url_prefix: Blueprint URL prefix.
    :param redirect_on_success: Target route on successful login.
    :param redirect_on_error: Format string with `{error}` placeholder for auth failures.
    :param redirect_on_logout: Target route after logging out.
    :param csrf_session_key: Session key for CSRF state token.
    :param scope: Base OAuth 2.0 scope string.
    :param include_appdata_scope: If True, appends Google Drive appDataFolder scope to the authorization URL.
    :param after_login_response: Optional callback `fn(response) -> response` invoked on successful login responses.
    """
    bp = Blueprint(name, __name__, url_prefix=url_prefix)

    def _resolve_redirect_uri() -> str:
        explicit = None
        if get_redirect_uri:
            explicit = get_redirect_uri()
        return build_redirect_uri(explicit)

    def _error_redirect(err: str):
        encoded = urllib.parse.quote(err)
        target = redirect_on_error.format(error=encoded)
        return redirect(target)

    # -------------------------------------------------------------------------
    # Route: /login
    # -------------------------------------------------------------------------
    @bp.route("/login", methods=["GET"])
    def google_login():
        client_id, _ = get_credentials()
        if not client_id:
            return jsonify({
                "error": "Google OAuth is not configured. Missing client credentials."
            }), 500

        csrf_token = secrets.token_urlsafe(16)
        session[csrf_session_key] = csrf_token

        effective_scope = scope
        if include_appdata_scope and GOOGLE_APPDATA_SCOPE not in effective_scope:
            effective_scope = f"{effective_scope} {GOOGLE_APPDATA_SCOPE}".strip()

        redirect_uri = _resolve_redirect_uri()
        auth_url = build_google_auth_url(client_id, redirect_uri, csrf_token, scope=effective_scope)
        return redirect(auth_url)

    # -------------------------------------------------------------------------
    # Route: /callback
    # -------------------------------------------------------------------------
    @bp.route("/callback", methods=["GET"])
    def google_callback():
        error = request.args.get("error")
        if error:
            return _error_redirect(error)

        code = request.args.get("code")
        received_csrf = request.args.get("state", "")

        expected_state = session.pop(csrf_session_key, None)
        if expected_state and expected_state != received_csrf:
            return _error_redirect("CSRF state validation failed. Please try signing in again.")

        client_id, client_secret = get_credentials()
        redirect_uri = _resolve_redirect_uri()

        tokens, err = exchange_code_for_tokens(code, client_id, client_secret, redirect_uri)
        if err or not tokens:
            return _error_redirect(f"Token exchange failed: {err}")

        raw_id_token = tokens.get("id_token")
        if not raw_id_token:
            return _error_redirect(tokens.get("error_description", "Failed to retrieve ID token from Google"))

        id_info = verify_google_id_token(raw_id_token, client_id)
        if not id_info:
            return _error_redirect("Invalid Google ID Token")

        email = id_info.get("email")
        if not email:
            return _error_redirect("No email returned by Google")

        id_info = dict(id_info)
        id_info["_oauth_tokens"] = tokens

        success, auth_payload = on_authenticate(email, id_info)
        if not success:
            err_msg = auth_payload if isinstance(auth_payload, str) else "denied"
            return _error_redirect(err_msg)

        resp = make_response(redirect(redirect_on_success))
        if after_login_response:
            resp = after_login_response(resp)
        return resp

    # -------------------------------------------------------------------------
    # Route: /verify_credential (Google One Tap / GIS)
    # -------------------------------------------------------------------------
    @bp.route("/verify_credential", methods=["POST"])
    @bp.route("/verify-token", methods=["POST"])
    def verify_credential_post():
        credential = request.form.get("credential")
        if not credential and request.is_json:
            json_body = request.get_json() or {}
            credential = json_body.get("credential") or json_body.get("id_token")
        elif not credential:
            credential = request.form.get("id_token")

        if not credential:
            return jsonify({"success": False, "error": "Missing Google credential token"}), 400

        client_id, _ = get_credentials()
        if not client_id:
            return jsonify({"success": False, "error": "Google OAuth is not configured on this server"}), 500

        id_info = verify_google_id_token(credential, client_id)
        if not id_info:
            return jsonify({"success": False, "error": "Invalid or expired Google credential"}), 401

        email = id_info.get("email")
        if not email:
            return jsonify({"success": False, "error": "Google account did not provide an email"}), 400

        success, auth_payload = on_authenticate(email, id_info)
        if not success:
            err_msg = auth_payload if isinstance(auth_payload, str) else "Access denied"
            return jsonify({"success": False, "error": err_msg}), 403

        if request.is_json:
            resp_dict: Dict[str, Any] = {"success": True, "redirect": redirect_on_success}
            if isinstance(auth_payload, dict):
                resp_dict.update(auth_payload)
            resp = make_response(jsonify(resp_dict))
        else:
            resp = make_response(redirect(redirect_on_success))

        if after_login_response:
            resp = after_login_response(resp)
        return resp

    # -------------------------------------------------------------------------
    # Route: /config
    # -------------------------------------------------------------------------
    @bp.route("/config", methods=["GET"])
    def google_auth_config():
        client_id, _ = get_credentials()
        return jsonify({
            "enabled": bool(client_id),
            "client_id": client_id,
            "login_url": f"{url_prefix}/login",
        })

    # -------------------------------------------------------------------------
    # Route: /logout
    # -------------------------------------------------------------------------
    @bp.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        if request.is_json:
            return jsonify({"success": True, "redirect": redirect_on_logout})
        return redirect(redirect_on_logout)

    # -------------------------------------------------------------------------
    # Route: /status
    # -------------------------------------------------------------------------
    @bp.route("/status", methods=["GET"])
    def auth_status():
        is_authenticated = bool(session.get("authenticated"))
        return jsonify({
            "authenticated": is_authenticated,
            "user": session.get("user"),
            "email": session.get("user_email"),
            "role": session.get("user_role") or session.get("role"),
            "picture": session.get("avatar_picture"),
        })

    return bp

