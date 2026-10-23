"""
Google OAuth 2.0 & Google Identity Services (One Tap) reusable authentication module.
Shared between multiple High Velocity Labs applications (Family Office, Fantasy Assistant, etc.).
"""

from __future__ import annotations

import secrets
import urllib.parse
from typing import Any, Callable, Dict, Optional, Tuple, Union

from flask import Blueprint, jsonify, make_response, redirect, request, session

from hvl_common.auth.google_helpers import (
    GOOGLE_APPDATA_SCOPE,
    build_google_auth_url,
    build_redirect_uri,
    clear_auth_and_vault_cookies,
    enter_demo_session,
    exchange_code_for_tokens,
    exit_demo_session,
    read_google_appdata_json,
    verify_google_id_token,
    write_google_appdata_json,
)


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
    prompt: str = "select_account",
    access_type: str = "online",
    after_login_response: Optional[Callable[[Any], Any]] = None,
) -> Blueprint:
    """Factory creating a Google OAuth 2.0 and Google Identity Services Blueprint."""
    from hvl_common.web.security import apply_hvl_session_config, check_csrf_origin

    bp = Blueprint(name, __name__, url_prefix=url_prefix)

    @bp.record_once
    def _configure_persistent_sessions(state: Any) -> None:
        apply_hvl_session_config(state.app, max_age_days=30)

    @bp.before_app_request
    def _enforce_permanent_pwa_session() -> None:
        if session.get("authenticated") and not session.get("is_demo"):
            session.permanent = True

    def _resolve_redirect_uri() -> str:
        return build_redirect_uri(get_redirect_uri() if get_redirect_uri else None)

    def _error_redirect(err: str):
        return redirect(redirect_on_error.format(error=urllib.parse.quote(err)))

    @bp.route("/login", methods=["GET"])
    def google_login():
        client_id, _ = get_credentials()
        if not client_id:
            return jsonify({"error": "Google OAuth is not configured. Missing client credentials."}), 500
        csrf_token = secrets.token_urlsafe(16)
        session[csrf_session_key] = csrf_token
        effective_scope = (
            f"{scope} {GOOGLE_APPDATA_SCOPE}".strip()
            if (include_appdata_scope and GOOGLE_APPDATA_SCOPE not in scope)
            else scope
        )
        effective_prompt = "consent select_account" if request.args.get("reconsent") == "1" else prompt
        return redirect(
            build_google_auth_url(
                client_id,
                _resolve_redirect_uri(),
                csrf_token,
                scope=effective_scope,
                prompt=effective_prompt,
                access_type=access_type,
            )
        )

    @bp.route("/callback", methods=["GET"])
    def google_callback():
        error = request.args.get("error")
        if error:
            return _error_redirect(error)

        code = request.args.get("code")
        received_csrf = request.args.get("state", "")
        expected_state = session.pop(csrf_session_key, None)
        if not expected_state or expected_state != received_csrf:
            return _error_redirect("CSRF state validation failed. Please try signing in again.")

        client_id, client_secret = get_credentials()
        tokens, err = exchange_code_for_tokens(code, client_id, client_secret, _resolve_redirect_uri())
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
            return _error_redirect(auth_payload if isinstance(auth_payload, str) else "denied")
        if not session.get("is_demo"):
            session.permanent = True

        resp = make_response(redirect(redirect_on_success))
        return after_login_response(resp) if after_login_response else resp

    @bp.route("/verify_credential", methods=["POST"])
    @bp.route("/verify-token", methods=["POST"])
    def verify_credential_post():
        csrf_rejection = check_csrf_origin(require_session_cookie=False)
        if csrf_rejection is not None:
            return csrf_rejection

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
            return jsonify({"success": False, "error": auth_payload if isinstance(auth_payload, str) else "Access denied"}), 403
        if not session.get("is_demo"):
            session.permanent = True

        if request.is_json:
            resp_dict: Dict[str, Any] = {"success": True, "redirect": redirect_on_success}
            if isinstance(auth_payload, dict):
                resp_dict.update(auth_payload)
            resp = make_response(jsonify(resp_dict))
        else:
            resp = make_response(redirect(redirect_on_success))
        return after_login_response(resp) if after_login_response else resp

    @bp.route("/config", methods=["GET"])
    def google_auth_config():
        client_id, _ = get_credentials()
        return jsonify({"enabled": bool(client_id), "client_id": client_id, "login_url": f"{url_prefix}/login"})

    @bp.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        if request.is_json:
            return clear_auth_and_vault_cookies(jsonify({"success": True, "redirect": redirect_on_logout}))
        return clear_auth_and_vault_cookies(redirect(redirect_on_logout))

    @bp.route("/status", methods=["GET"])
    def auth_status():
        return jsonify({
            "authenticated": bool(session.get("authenticated")),
            "user": session.get("user"),
            "email": session.get("user_email"),
            "role": session.get("user_role") or session.get("role"),
            "picture": session.get("avatar_picture"),
        })

    return bp


__all__ = [
    "GOOGLE_APPDATA_SCOPE",
    "build_google_auth_url",
    "build_redirect_uri",
    "clear_auth_and_vault_cookies",
    "create_google_auth_blueprint",
    "enter_demo_session",
    "exchange_code_for_tokens",
    "exit_demo_session",
    "read_google_appdata_json",
    "verify_google_id_token",
    "write_google_appdata_json",
]
