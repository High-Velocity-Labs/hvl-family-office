"""
Cryptographic encryption and key derivation helpers using AES-128 Fernet.
"""

from __future__ import annotations
import os
import base64
import hashlib
from functools import lru_cache
from typing import Optional, Union
from cryptography.fernet import Fernet

VAULT_COOKIE_NAME = "hvl_vault_fek"


def generate_secret_key() -> str:
    """Generates a new URL-safe base64-encoded 32-byte Fernet key."""
    return Fernet.generate_key().decode("utf-8")


@lru_cache(maxsize=64)
def derive_key(secret: str, salt: bytes = b"hvl_salt_v1") -> bytes:
    """Derives a deterministic Fernet key from a string secret using PBKDF2/SHA256."""
    derived = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 100_000)
    return base64.urlsafe_b64encode(derived[:32])


def encrypt_value(plain_text: str, key: bytes) -> str:
    """Encrypts plaintext string with the provided Fernet key. Returns base64 string."""
    if not plain_text:
        return ""
    f = Fernet(key)
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_value(cipher_text: str, key: bytes, default: str = "") -> str:
    """Decrypts ciphertext string with the provided Fernet key. Returns default on failure."""
    if not cipher_text:
        return default
    try:
        f = Fernet(key)
        return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception:
        return default


def wrap_cookie_fek(raw_fek: Union[bytes, str], secret_key: Union[bytes, str]) -> str:
    """Encrypts a raw Family Encryption Key (FEK) using a key derived from secret_key for cookie storage."""
    secret_str = secret_key.decode("utf-8") if isinstance(secret_key, bytes) else str(secret_key)
    fek_bytes = raw_fek.encode("utf-8") if isinstance(raw_fek, str) else raw_fek
    wrapping_key = derive_key(secret_str)
    return Fernet(wrapping_key).encrypt(fek_bytes).decode("utf-8")


def unwrap_cookie_fek(token: str, secret_key: Union[bytes, str]) -> Optional[bytes]:
    """Decrypts a wrapped FEK cookie token using a key derived from secret_key. Returns bytes or None."""
    if not token or not secret_key:
        return None
    try:
        secret_str = secret_key.decode("utf-8") if isinstance(secret_key, bytes) else str(secret_key)
        token_bytes = token.encode("utf-8") if isinstance(token, str) else token
        wrapping_key = derive_key(secret_str)
        return Fernet(wrapping_key).decrypt(token_bytes)
    except Exception:
        return None


ADMIN_GATE_COOKIE_NAME = "hvl_beta_admin"
_ADMIN_GATE_SALT = b"hvl_beta_admin_gate_v1"


def wrap_admin_gate_token(email: str, secret_key: Union[bytes, str]) -> str:
    """Creates a signed/encrypted cross-subdomain admin gate token for `.highvelocitylabs.dev`."""
    clean_email = (email or "").strip().lower()
    if not clean_email or not secret_key:
        return ""
    secret_str = secret_key.decode("utf-8") if isinstance(secret_key, bytes) else str(secret_key)
    key = derive_key(secret_str, salt=_ADMIN_GATE_SALT)
    return Fernet(key).encrypt(clean_email.encode("utf-8")).decode("utf-8")


def unwrap_admin_gate_token(
    token: str,
    secret_keys: Union[bytes, str, list, tuple, set],
    max_age_seconds: int = 30 * 24 * 3600,
) -> Optional[str]:
    """Validates a cross-subdomain admin gate token against one or more candidate secret keys."""
    if not token or not secret_keys:
        return None
    if isinstance(secret_keys, (bytes, str)):
        candidates = [secret_keys]
    else:
        candidates = [k for k in secret_keys if k]
    token_bytes = token.encode("utf-8") if isinstance(token, str) else token
    for sec in candidates:
        try:
            sec_str = sec.decode("utf-8") if isinstance(sec, bytes) else str(sec)
            if not sec_str:
                continue
            key = derive_key(sec_str, salt=_ADMIN_GATE_SALT)
            plain = Fernet(key).decrypt(token_bytes, ttl=max_age_seconds).decode("utf-8").strip().lower()
            if plain and "@" in plain:
                return plain
        except Exception:
            continue
    return None


