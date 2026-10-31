"""
Google OAuth access-token verification for backend-to-backend callers (`hvl_common.auth.google_tokeninfo`).

A paired HVL app sends a member's Google access token as a bearer; the receiving app asks Google's tokeninfo
endpoint who it belongs to, and only accepts tokens issued to an OAuth client it trusts.
"""

from __future__ import annotations

import os
from typing import Collection

import requests

GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
PROVISION_CLIENT_IDS_ENV = "MCP_PROVISION_CLIENT_IDS"


class GoogleTokenError(Exception):
    """A refused Google access token; `status` is the HTTP status the calling route returns."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def trusted_google_client_ids() -> frozenset[str]:
    """Google OAuth client IDs whose access tokens may provision: the app's own `GOOGLE_CLIENT_ID` plus the list."""
    raw = ",".join((os.getenv("GOOGLE_CLIENT_ID", ""), os.getenv(PROVISION_CLIENT_IDS_ENV, "")))
    return frozenset(c.strip() for c in raw.split(",") if c.strip())


def verify_google_access_token(access_token: str, trusted_client_ids: Collection[str]) -> str:
    """Returns the verified, lowercased email of a Google access token issued to one of `trusted_client_ids`."""
    try:
        resp = requests.get(GOOGLE_TOKENINFO_URL, params={"access_token": access_token}, timeout=5)
    except requests.RequestException as exc:
        raise GoogleTokenError(f"Could not reach Google to verify the sign-in: {exc}", 502) from exc
    if resp.status_code != 200:
        raise GoogleTokenError("Google sign-in is invalid or expired. Sign in again, then retry.", 401)
    info = resp.json()
    client_id = str(info.get("azp") or info.get("aud") or "")
    if client_id not in trusted_client_ids:
        raise GoogleTokenError("This Google sign-in was not issued to a trusted HVL app.", 403)
    email = str(info.get("email") or "").strip().lower()
    if not email or str(info.get("email_verified")).lower() != "true":
        raise GoogleTokenError("The Google account has no verified email.", 403)
    return email
