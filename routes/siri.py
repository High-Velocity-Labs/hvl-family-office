"""
Siri & Apple Shortcuts Voice Webhook Blueprint (`routes/siri.py`).
Mounts `create_siri_blueprint` at `/api/siri` with zero-knowledge `vault_fek` unwrapping
via `hvl_common.mcp.tokens` and AI Advisor delegation (`run_advisor_chat`).
"""

from __future__ import annotations

from typing import Any

from flask import session
from hvl_common.mcp.tokens import record_mcp_token_usage
from hvl_common.web.siri import create_siri_blueprint

from routes.helpers import (
    _is_demo_session,
    get_current_cache_db_path,
    get_current_family_id,
    get_current_universe,
    reset_background_context,
)
from services.mcp_service import (
    _resolve_mcp_db_path,
    bind_request_fek,
    mint_siri_token,
    revoke_siri_token,
    run_advisor_chat,
    verify_siri_token,
)


def _get_siri_session_user() -> dict[str, Any] | None:
    """Extracts the active session user context for Siri token minting and revocation."""
    fid = get_current_family_id()
    uni = get_current_universe()
    role = str(session.get("role") or session.get("user_role") or "editor").strip().lower()
    is_demo = bool(_is_demo_session() or session.get("is_demo") or uni in ("demo", "sandbox", "beta"))
    is_auth = bool(session.get("authenticated") and fid > 0)
    email = str(session.get("user_email") or session.get("user") or "").strip().lower()
    if is_auth and not email:
        email = f"family{fid}@household.local"
    return {
        "email": email,
        "family_id": fid,
        "household_id": fid,
        "role": role,
        "is_demo": is_demo,
        "is_authenticated": is_auth,
        "universe": "public" if uni == "test" else uni,
    }


def _authenticate_siri_token(raw_token: str) -> dict[str, Any] | None:
    """Verifies a Siri bearer token and unwraps its zero-knowledge household `vault_fek`."""
    meta = verify_siri_token(raw_token)
    if not meta:
        return None
    fid = int(meta.get("owner_id") or 0)
    if fid <= 0:
        return None
    raw_email = str(meta.get("user_email") or "").strip().lower()
    clean_email = raw_email[5:] if raw_email.startswith("siri:") else raw_email
    return {
        "token_id": meta.get("token_id"),
        "family_id": fid,
        "household_id": fid,
        "email": clean_email or f"family{fid}@household.local",
        "secret_payload": meta.get("secret_payload"),
    }


def _mint_siri_user_token(user: dict[str, Any]) -> str:
    """Mints a Siri Shortcut token (`hvl_siri_...`) wrapping the active session's `vault_fek`."""
    info = mint_siri_token(
        family_id=int(user.get("family_id") or user.get("household_id") or 0),
        user_email=str(user.get("email") or ""),
        universe=str(user.get("universe") or "public"),
    )
    return str(info.get("raw_token") or info.get("token") or "")


def _revoke_siri_user_token(user: dict[str, Any]) -> bool:
    """Revokes the active Siri Shortcut token for the authenticated household member."""
    removed = revoke_siri_token(
        family_id=int(user.get("family_id") or user.get("household_id") or 0),
        user_email=str(user.get("email") or ""),
    )
    return bool(removed > 0)


def _execute_siri_turn(
    member: dict[str, Any],
    text: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Binds unwrapped `vault_fek` and executes a spoken query against the Family Office AI Advisor."""
    fid = int(member.get("household_id") or member.get("family_id") or 0)
    vault_fek = member.get("secret_payload")
    tokens = bind_request_fek(fid, vault_fek)
    try:
        if member.get("token_id"):
            try:
                record_mcp_token_usage(_resolve_mcp_db_path(), int(member["token_id"]))
            except Exception:
                pass
        res = run_advisor_chat(
            family_id=fid,
            prompt=text,
            user_email=str(member.get("email") or ""),
            vault_fek=vault_fek,
        )
        return {
            "success": bool(res.get("success", True)),
            "reply": str(res.get("reply") or res.get("response") or "Done.").strip(),
            "intent": "advisor_chat",
            "open_url": "/",
        }
    finally:
        reset_background_context(tokens)


siri_bp = create_siri_blueprint(
    authenticate_token_fn=_authenticate_siri_token,
    mint_token_fn=_mint_siri_user_token,
    revoke_token_fn=_revoke_siri_user_token,
    get_current_user_fn=_get_siri_session_user,
    execute_siri_turn_fn=_execute_siri_turn,
    open_url="/",
    async_jobs_enabled=False,
    cache_db_path_fn=lambda: get_current_cache_db_path(),
    blueprint_name="siri",
    url_prefix="/api/siri",
)

__all__ = ["siri_bp"]
