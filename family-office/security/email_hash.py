"""
Blind index for `users.email_hash`: a keyed HMAC-SHA256 of the normalized email, so a leaked database cannot be
checked against lists of known addresses. The key is `EMAIL_HASH_SECRET`, else a random per-install secret kept
next to the root key file (`.email_hash.key`, mode 0600). Rows written before this used a bare SHA-256; lookups
try `email_hash_candidates()` (current form first) and rewrite a legacy match to the current form on the spot.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
from pathlib import Path
from typing import Dict

_HMAC_DOMAIN = b"hvl-family-office-email-hash-v1|"
_SECRET_CACHE: Dict[str, bytes] = {}
_SECRET_LOCK = threading.Lock()


def _normalize(email: str) -> bytes:
    return email.strip().lower().encode("utf-8")


def _secret_file() -> Path:
    from security.crypto import _get_active_key_file

    return _get_active_key_file().with_name(".email_hash.key")


def _load_secret() -> bytes:
    env = os.environ.get("EMAIL_HASH_SECRET", "").strip()
    if env:
        return env.encode("utf-8")
    path = _secret_file()
    cache_key = str(path)
    cached = _SECRET_CACHE.get(cache_key)
    if cached is not None:
        return cached
    with _SECRET_LOCK:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass  # another worker created it first; read theirs
            else:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(os.urandom(32).hex().encode("ascii"))
        secret = path.read_bytes().strip()
        if not secret:
            raise RuntimeError(f"Email hash secret file {path} is empty.")
        _SECRET_CACHE[cache_key] = secret
        return secret


def hash_email(email: str) -> str:
    """Keyed blind-index hash (hex) of `email` for lookups without storing the address in the clear."""
    if not email or not email.strip():
        return ""
    return hmac.new(_load_secret(), _HMAC_DOMAIN + _normalize(email), hashlib.sha256).hexdigest()


def legacy_hash_email(email: str) -> str:
    """The pre-HMAC unsalted SHA-256 form, only for finding rows that have not been rewritten yet."""
    if not email or not email.strip():
        return ""
    return hashlib.sha256(_normalize(email)).hexdigest()


def email_hash_candidates(email: str) -> tuple[str, ...]:
    """Every stored form `email` may have: current keyed hash first, then the legacy one. Empty for no email."""
    current = hash_email(email)
    return (current, legacy_hash_email(email)) if current else ()
