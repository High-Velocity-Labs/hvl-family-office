"""
Paired-app MCP token provisioning (`services.mcp_provisioning`).

A paired HVL app (Assistant) sends a household member's Google OAuth access token. Family Office verifies it with
Google, finds that member's own household, unlocks the household FEK the way a Google login does (Drive
appDataFolder, then Family Office's own escrow), and mints a read/simulate MCP token bound to that FEK.
The caller never sees Family Office's root key, the FEK, or its databases; it only receives the raw token.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from hvl_common.auth import (
    GoogleTokenError,
    read_google_appdata_json,
    trusted_google_client_ids,
    verify_google_access_token,
)
from hvl_common.mcp.tokens import mint_mcp_token

ASSISTANT_TOKEN_LABEL = "HVL Assistant"
_MINTING_ROLES = ("admin", "editor")


class ProvisioningError(Exception):
    """A refused provisioning request; `status` is the HTTP status the route returns."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def provision_paired_app_token(access_token: str) -> Dict[str, str]:
    """Mints a read/simulate MCP token for the household of the Google account behind `access_token`."""
    import security
    from db.users import get_user_by_email_hash
    from services.auth_google import get_auth_db_path
    from services.auth_vault_fek import resolve_household_vault_fek
    from services.mcp_service import _resolve_mcp_db_path, _resolve_mcp_server_secret
    from services.request_context import get_current_universe

    try:
        email = verify_google_access_token(access_token, trusted_google_client_ids())
    except GoogleTokenError as exc:
        raise ProvisioningError(exc.message, exc.status) from exc
    auth_db = Path(get_auth_db_path())
    user_row = get_user_by_email_hash(auth_db, security.email_hash_candidates(email))
    fid = int((user_row or {}).get("family_id") or 0)
    if user_row is None or fid <= 0:
        raise ProvisioningError(
            "No Family Office account matches this Google account. Sign in to Family Office first.", 404
        )
    if str(user_row.get("role") or "viewer").strip().lower() not in _MINTING_ROLES:
        raise ProvisioningError("Only household editors can link Family Office to an assistant.", 403)
    if security.get_family_deletion_status(auth_db, family_id=fid):
        raise ProvisioningError("This household is scheduled for deletion.", 403)

    raw_fek, _source, locked_err = resolve_household_vault_fek(
        db_path=auth_db, fid=fid, user_row=user_row, clean_email=email, access_token=access_token,
        already_synced=False, read_appdata_fn=read_google_appdata_json,
    )
    if locked_err or raw_fek is None:
        raise ProvisioningError(
            "The Family Office vault is locked for this account. Sign in to Family Office once, then link again.", 409
        )

    try:
        info = mint_mcp_token(
            _resolve_mcp_db_path(), owner_id=fid, user_email=email, label=ASSISTANT_TOKEN_LABEL,
            scopes=("read", "simulate"), universe=get_current_universe(),
            secret_payload=raw_fek, server_secret=_resolve_mcp_server_secret(),
        )
    except PermissionError as exc:
        raise ProvisioningError(str(exc), 403) from exc
    return {"raw_token": str(info["raw_token"]), "token_prefix": str(info["token_prefix"])}
