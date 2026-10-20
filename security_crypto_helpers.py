"""
Helper classes and utilities for cryptographic operations and credential persistence.
"""

from __future__ import annotations
from collections import OrderedDict
import hashlib
import os
from pathlib import Path
import sys
from typing import Any, List, Optional, Tuple, Union
from cryptography.fernet import Fernet
from dotenv import load_dotenv, set_key

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
KEY_FILE = BASE_DIR / ".mm" / ".secret.key"
KEY_FILE.parent.mkdir(parents=True, exist_ok=True)


class _BoundedDict(OrderedDict):
    def __init__(self, maxsize: int = 512, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.maxsize:
            self.popitem(last=False)


class _BoundedSet(set):
    def __init__(self, maxsize: int = 512, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def add(self, item):
        super().add(item)
        if len(self) > self.maxsize:
            self.pop()


def _parse_fernet_keys(raw_key: Union[bytes, str]) -> List[bytes]:
    """Parses a single or comma-separated list of Fernet keys into clean key bytes."""
    if isinstance(raw_key, bytes):
        raw_str = raw_key.decode("utf-8", errors="ignore")
    else:
        raw_str = str(raw_key or "")
    keys: List[bytes] = []
    for part in raw_str.split(","):
        cleaned = part.strip()
        if cleaned:
            keys.append(cleaned.encode("utf-8"))
    return keys


def _get_active_key_file() -> Path:
    """Resolves `.secret.key` inside user-writable data dir when FAMILY_OFFICE_DATA_DIR is set."""
    try:
        import config
        if os.environ.get("FAMILY_OFFICE_DATA_DIR") or getattr(sys, "frozen", False):
            p = config.get_data_dir() / ".mm" / ".secret.key"
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    return KEY_FILE


def _get_active_env_file() -> Path:
    """Resolves `.env` inside user-writable data dir when FAMILY_OFFICE_DATA_DIR is set."""
    try:
        import config
        if os.environ.get("FAMILY_OFFICE_DATA_DIR") or getattr(sys, "frozen", False):
            p = config.get_data_dir() / ".env"
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    return ENV_FILE


def save_encrypted_credentials(email: str, password: str) -> None:
    """Encrypts the password and saves credentials to .env."""
    import security_crypto
    enc_password = security_crypto.encrypt_string(password)
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), "MONARCH_EMAIL", email)
    set_key(str(ENV_FILE), "MONARCH_PASSWORD_ENC", enc_password)


def get_stored_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Retrieves and decrypts stored Monarch credentials from .env, if available."""
    import security_crypto
    load_dotenv(ENV_FILE)
    email = os.getenv("MONARCH_EMAIL")
    enc_pwd = os.getenv("MONARCH_PASSWORD_ENC")

    if not email or not enc_pwd:
        return None, None

    try:
        password = security_crypto.decrypt_string(enc_pwd)
        return email, password
    except Exception as e:
        print(f"Error decrypting credentials: {e}")
        return email, None


def save_encrypted_cookies(cookie_string: str) -> None:
    """Encrypts a Monarch cookie string and stores it in .env."""
    import security_crypto
    enc_cookies = security_crypto.encrypt_string(cookie_string.strip())
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), "MONARCH_COOKIES_ENC", enc_cookies)


def get_stored_cookies() -> Optional[str]:
    """Retrieves and decrypts stored Monarch cookies from .env, if available."""
    import security_crypto
    load_dotenv(ENV_FILE)
    plain_cookies = os.getenv("MONARCH_COOKIES")
    if plain_cookies and plain_cookies.strip():
        return plain_cookies.strip()

    enc_cookies = os.getenv("MONARCH_COOKIES_ENC")
    if enc_cookies and enc_cookies.strip():
        try:
            return security_crypto.decrypt_string(enc_cookies.strip())
        except Exception:
            pass

    token = os.getenv("MONARCH_TOKEN")
    if token and token.strip():
        return token.strip()

    return None


_PBKDF2_ITERATIONS = 600_000


def derive_passphrase_fernet_key(
    passphrase: str, salt: bytes, iterations: int = _PBKDF2_ITERATIONS
) -> bytes:
    """Derives a URL-safe base64-encoded 32-byte Fernet key from passphrase/PIN and salt."""
    import base64
    raw_dk = hashlib.pbkdf2_hmac(
        "sha256",
        str(passphrase).encode("utf-8"),
        bytes(salt),
        int(iterations),
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw_dk)


def wrap_fek_with_passphrase(
    raw_fek: bytes, passphrase: str, iterations: int = _PBKDF2_ITERATIONS
) -> str:
    """Wraps FEK using a user-supplied Master Passphrase/PIN."""
    import secrets as _secrets
    salt = _secrets.token_bytes(16)
    wk = derive_passphrase_fernet_key(passphrase, salt, iterations=iterations)
    ct = Fernet(wk).encrypt(
        raw_fek if isinstance(raw_fek, bytes) else str(raw_fek).encode("utf-8")
    ).decode("utf-8")
    return f"pbkdf2_sha256${int(iterations)}${salt.hex()}${ct}"


def unwrap_fek_with_passphrase(wrapped_blob: str, passphrase: str) -> Optional[bytes]:
    """Unwraps a household's FEK from a pbkdf2_sha256 blob using the user's passphrase/PIN."""
    import security_crypto
    try:
        parts = str(wrapped_blob or "").strip().split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return None
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        ct = parts[3].encode("utf-8")
        wk = derive_passphrase_fernet_key(passphrase, salt, iterations=iterations)
        raw_fek = Fernet(wk).decrypt(ct)
        security_crypto._get_fernet(raw_fek)
        return raw_fek
    except Exception:
        return None
