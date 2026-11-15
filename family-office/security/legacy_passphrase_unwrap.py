"""
One-time read of a Local Desktop Master Passphrase/PIN wrap from before the shared scrypt envelope.

Old installs stored `families.local_passphrase_fek_enc` as `pbkdf2_sha256$<iter>$<salt hex>$<Fernet>`.
Nothing writes that format any more. Its only reader is `services.desktop_service.execute_local_passphrase_login`,
which re-wraps the FEK under scrypt and stores it straight away, so each install reads it at most once.
Delete this module and that one call after 2027-02-01 (card #2739); an owner who has not signed in
by then resets the passphrase with their Recovery Key, which needs no old passphrase.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

_LEGACY_PREFIX = "pbkdf2_sha256$"


def is_legacy_pbkdf2_wrap(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_LEGACY_PREFIX)


def unwrap_legacy_pbkdf2_fek(wrapped_blob: str, passphrase: str) -> Optional[bytes]:
    """Returns the FEK, or None for a wrong passphrase/PIN or a malformed blob."""
    parts = str(wrapped_blob or "").strip().split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return None
    try:
        derived = hashlib.pbkdf2_hmac("sha256", str(passphrase).encode("utf-8"), bytes.fromhex(parts[2]), int(parts[1]))
        raw_fek = Fernet(base64.urlsafe_b64encode(derived)).decrypt(parts[3].encode("utf-8"))
        Fernet(raw_fek)
        return raw_fek
    except (InvalidToken, ValueError):
        return None  # wrong passphrase/PIN or a malformed blob; the login answers 401
