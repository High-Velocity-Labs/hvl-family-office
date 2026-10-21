"""
Shared Magic Invite Token Generation, Lifecycle Formatting, and Validation Helpers.
Used across High Velocity Labs multi-member household applications (Family Office, Assistant).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, Mapping, Tuple

INVITE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_invite_code(prefix: str = "HVL") -> str:
    """Generates a human-friendly unambiguous Magic Invite code (`{PREFIX}-XXXX-XXXX`)."""
    clean_prefix = (prefix or "HVL").strip().upper()
    part1 = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(4))
    part2 = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(4))
    return f"{clean_prefix}-{part1}-{part2}"


def compute_invite_expiry_iso(expires_days: int = 14) -> str:
    """Computes an ISO-8601 UTC expiration timestamp `expires_days` in the future (clamped to 1..365)."""
    norm_days = max(1, min(365, int(expires_days or 14)))
    exp_dt = datetime.now(timezone.utc) + timedelta(days=norm_days)
    return exp_dt.strftime("%Y-%m-%d %H:%M:%S")


def compute_invite_status(
    uses_count: int,
    max_uses: int,
    revoked: bool | int,
    expires_at: str | None,
) -> Tuple[str, bool]:
    """
    Computes `(status, is_expired)` for an invite record where `status` is one of:
    `'active'`, `'redeemed'`, `'expired'`, or `'revoked'`.
    """
    max_u = max(1, int(max_uses or 1))
    uses_c = int(uses_count or 0)
    is_revoked = bool(int(revoked or 0))
    is_expired = False

    if expires_at:
        try:
            raw_exp = str(expires_at).strip().replace("Z", "+00:00")
            exp_dt = datetime.fromisoformat(raw_exp)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            is_expired = exp_dt <= datetime.now(timezone.utc)
        except Exception:
            is_expired = False

    if is_revoked:
        status = "revoked"
    elif uses_c >= max_u:
        status = "redeemed"
    elif is_expired:
        status = "expired"
    else:
        status = "active"
    return status, is_expired


def format_invite_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalizes a database invite row dictionary with computed `status`, `is_expired`, and `valid` flags."""
    data = dict(row)
    max_u = max(1, int(data.get("max_uses") or 1))
    uses_c = int(data.get("uses_count") or 0)
    is_revoked = bool(int(data.get("revoked") or 0))
    expires_at = str(data.get("expires_at") or "")
    status, is_expired = compute_invite_status(uses_c, max_u, is_revoked, expires_at)

    data["code"] = str(data.get("code") or "").strip().upper()
    data["max_uses"] = max_u
    data["uses_count"] = uses_c
    data["revoked"] = is_revoked
    data["is_expired"] = is_expired
    data["status"] = status
    data["valid"] = status == "active"
    return data
