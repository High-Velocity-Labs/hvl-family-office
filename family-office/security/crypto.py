"""
Cryptographic primitives, Fernet key ring management, and request-scoped FEK resolution.
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import logging
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from dotenv import load_dotenv, set_key
from hvl_common.security import (
    BoundedDict,
    BoundedSet,
    VAULT_COOKIE_NAME,
    parse_fernet_keys as _parse_fernet_keys,
    unwrap_cookie_fek,
    wrap_cookie_fek,
)

__all__ = [
    "VAULT_COOKIE_NAME",
    "_parse_fernet_keys",
    "unwrap_cookie_fek",
    "wrap_cookie_fek",
]

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
KEY_FILE = BASE_DIR / ".mm" / ".secret.key"

KEY_FILE.parent.mkdir(parents=True, exist_ok=True)


def _get_active_key_file() -> Path:
    """Resolves `.secret.key` inside user-writable data dir when FAMILY_OFFICE_DATA_DIR is set."""
    import config

    if os.environ.get("FAMILY_OFFICE_DATA_DIR") or getattr(sys, "frozen", False):
        p = config.get_data_dir() / ".mm" / ".secret.key"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    return KEY_FILE


def _get_active_env_file() -> Path:
    """Resolves `.env` inside user-writable data dir when FAMILY_OFFICE_DATA_DIR is set."""
    import config

    if os.environ.get("FAMILY_OFFICE_DATA_DIR") or getattr(sys, "frozen", False):
        p = config.get_data_dir() / ".env"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return ENV_FILE


def save_encrypted_credentials(email: str, password: str) -> None:
    """Encrypts the password and saves credentials to .env."""
    enc_password = encrypt_string(password)
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), "MONARCH_EMAIL", email)
    set_key(str(ENV_FILE), "MONARCH_PASSWORD_ENC", enc_password)


def get_stored_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Retrieves and decrypts stored Monarch credentials from .env, if available."""
    load_dotenv(ENV_FILE)
    email = os.getenv("MONARCH_EMAIL")
    enc_pwd = os.getenv("MONARCH_PASSWORD_ENC")

    if not email or not enc_pwd:
        return None, None

    try:
        password = decrypt_string(enc_pwd)
        return email, password
    except InvalidToken as e:
        # The stored password is not decryptable under the current root key: report it as absent, never as plaintext.
        logger.warning("Stored credentials could not be decrypted: %s", type(e).__name__)
        return email, None


def save_encrypted_cookies(cookie_string: str) -> None:
    """Encrypts a Monarch cookie string and stores it in .env."""
    enc_cookies = encrypt_string(cookie_string.strip())
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), "MONARCH_COOKIES_ENC", enc_cookies)


def get_stored_cookies() -> Optional[str]:
    """Retrieves and decrypts stored Monarch cookies from .env, if available."""
    load_dotenv(ENV_FILE)
    plain_cookies = os.getenv("MONARCH_COOKIES")
    if plain_cookies and plain_cookies.strip():
        return plain_cookies.strip()

    enc_cookies = os.getenv("MONARCH_COOKIES_ENC")
    if enc_cookies and enc_cookies.strip():
        try:
            return decrypt_string(enc_cookies.strip())
        except InvalidToken:
            logger.warning("Stored cookies could not be decrypted; falling back to MONARCH_TOKEN if set")

    token = os.getenv("MONARCH_TOKEN")
    if token and token.strip():
        return token.strip()

    return None

_ROOT_KEY_CACHE: Optional[bytes] = None
_FAMILY_KEY_CACHE: Dict[Tuple[str, int], bytes] = BoundedDict(maxsize=512)
_FERNET_CACHE: Dict[bytes, Union[Fernet, MultiFernet]] = BoundedDict(maxsize=128)
_DB_INIT_CACHE: Set[str] = BoundedSet(maxsize=512)


def _get_fernet(key: Optional[Union[bytes, str]] = None) -> Union[Fernet, MultiFernet]:
    raw_eff = key if key is not None else get_or_create_key()
    eff_key = raw_eff.encode("utf-8") if isinstance(raw_eff, str) else raw_eff
    f = _FERNET_CACHE.get(eff_key)
    if f is None:
        parsed_keys = _parse_fernet_keys(eff_key)
        if not parsed_keys:
            raise ValueError("No valid Fernet key provided")
        if len(parsed_keys) == 1:
            f = Fernet(parsed_keys[0])
        else:
            f = MultiFernet([Fernet(k) for k in parsed_keys])
        if len(_FERNET_CACHE) < 128:
            _FERNET_CACHE[eff_key] = f
    return f


def _clear_security_caches() -> None:
    global _ROOT_KEY_CACHE
    _ROOT_KEY_CACHE = None
    _FAMILY_KEY_CACHE.clear()
    _FERNET_CACHE.clear()
    _DB_INIT_CACHE.clear()
    from services.request_context import _bg_vault_fek_ctx

    _bg_vault_fek_ctx.set((0, None))


def get_or_create_key() -> bytes:
    """Retrieves existing encryption key(s) or creates a new cryptographically secure key."""
    global _ROOT_KEY_CACHE
    custom_data_dir = bool(os.environ.get("FAMILY_OFFICE_DATA_DIR") or getattr(sys, "frozen", False))
    active_env = _get_active_env_file()
    active_key_file = _get_active_key_file()

    if not custom_data_dir:
        env_key = os.environ.get("APP_ENCRYPTION_KEY")
        if not env_key:
            load_dotenv(active_env)
            env_key = os.environ.get("APP_ENCRYPTION_KEY")
        if env_key and env_key.strip():
            raw_bytes = env_key.strip().encode("utf-8")
            _ROOT_KEY_CACHE = raw_bytes
            return raw_bytes

    if active_key_file.exists():
        with open(active_key_file, "rb") as f:
            key = f.read().strip()
            if key:
                _ROOT_KEY_CACHE = key
                return _ROOT_KEY_CACHE

    new_key = Fernet.generate_key()
    with open(active_key_file, "wb") as f:
        f.write(new_key)

    if not custom_data_dir:
        try:
            set_key(str(active_env), "APP_ENCRYPTION_KEY", new_key.decode("utf-8"))
        except OSError as exc:
            logger.warning("Root key written to %s but not mirrored into %s: %s", active_key_file, active_env, exc)

    _ROOT_KEY_CACHE = new_key
    return new_key


def get_primary_key() -> bytes:
    """Returns the primary (first/newest) Fernet key from the configured root KEK ring."""
    keys = _parse_fernet_keys(get_or_create_key())
    if not keys:
        raise ValueError("No valid primary Fernet key available")
    return keys[0]


def _is_authenticated_for_family(
    family_id: int, allow_sandbox: bool = False, require_sandbox: bool = False
) -> bool:
    """Returns True if inside a Flask request context authenticated for the given family_id."""
    if not family_id or int(family_id) <= 0:
        return False
    from flask import has_request_context, session

    if not has_request_context():
        return False
    if session.get("is_demo"):
        return False
    is_sb = bool(session.get("is_sandbox"))
    if require_sandbox and not is_sb:
        return False
    if is_sb and not allow_sandbox:
        return False
    uni = str(session.get("universe") or "public").strip().lower()
    if is_sb:
        if uni not in ("sandbox", "public", ""):
            return False
    elif uni not in ("public", ""):
        return False
    fid = int(family_id)
    try:
        sess_fid = int(session.get("family_id") or 0)
        user_fid = int(session.get("user_family_id") or 0)
    except (TypeError, ValueError):
        return False  # a malformed session id is never an authenticated household
    if user_fid > 0 and user_fid != fid:
        return False
    return sess_fid == fid or user_fid == fid


def get_request_vault_fek(
    family_id: int, allow_sandbox: bool = True, require_sandbox: bool = False
) -> Optional[bytes]:
    """
    Resolves the per-family FEK from the active background task context or Flask request context
    (`g`, `session`, or `hvl_vault_fek` cookie) when the request belongs to `family_id`.
    """
    if not family_id or int(family_id) <= 0:
        return None
    fid = int(family_id)
    from services.request_context import get_background_vault_fek

    bg_fek = get_background_vault_fek(fid)
    if bg_fek is not None:
        return bg_fek
    from flask import has_request_context, request, session, g

    if not has_request_context():
        return None
    active_feks = getattr(g, "_active_vault_feks", None)
    if isinstance(active_feks, dict) and fid in active_feks:
        return active_feks[fid]

    if not _is_authenticated_for_family(
        fid, allow_sandbox=allow_sandbox, require_sandbox=require_sandbox
    ):
        return None

    vault_fid = session.get("vault_fek_family_id")
    try:
        if vault_fid is not None and int(vault_fid or 0) != fid:
            return None
    except (TypeError, ValueError):
        return None  # a malformed vault binding never matches the household

    import config
    candidate_tokens = [
        session.get("vault_fek"),
        request.cookies.get(config.get_vault_cookie_name()),
        request.cookies.get(VAULT_COOKIE_NAME),
    ]
    raw_root = get_or_create_key()
    keks = list(_parse_fernet_keys(raw_root))
    if raw_root and raw_root not in keks:
        keks.append(raw_root)
    for token in candidate_tokens:
        if not token:
            continue
        for k in keks:
            unwrapped = unwrap_cookie_fek(str(token), k)  # None for a forged, expired or foreign token
            if unwrapped:
                if not isinstance(active_feks, dict):
                    active_feks = {}
                    g._active_vault_feks = active_feks
                active_feks[fid] = unwrapped
                return unwrapped
    return None


def stash_request_vault_fek(family_id: int, raw_fek: bytes) -> str:
    """
    Wraps `raw_fek` for cookie/session transport and stashes it in Flask `session` and `g`
    (or background context when outside a request) so the outgoing HTTP response attaches
    the `hvl_vault_fek` HttpOnly cookie.
    """
    eff_fek = raw_fek.encode("utf-8") if isinstance(raw_fek, str) else raw_fek
    wrapped = wrap_cookie_fek(eff_fek, get_primary_key())
    from flask import has_request_context, session, g

    fid = int(family_id)
    if has_request_context():
        session["vault_fek"] = wrapped
        session["vault_fek_family_id"] = fid
        active_feks = getattr(g, "_active_vault_feks", None)
        if not isinstance(active_feks, dict):
            active_feks = {}
            g._active_vault_feks = active_feks
        active_feks[fid] = eff_fek
        g._pending_vault_cookie = wrapped
    else:
        from services.request_context import _bg_vault_fek_ctx
        _bg_vault_fek_ctx.set((fid, eff_fek))
    return wrapped


def encrypt_string(plaintext: str, key: Optional[bytes] = None) -> str:
    """Encrypts a plaintext string into a Fernet ciphertext token."""
    k = key or get_or_create_key()
    fernet = _get_fernet(k)
    ciphertext = fernet.encrypt(plaintext.encode("utf-8"))
    return ciphertext.decode("utf-8")


def decrypt_string(ciphertext: str, key: Optional[bytes] = None) -> str:
    """Decrypts a Fernet ciphertext token back to plaintext."""
    # An explicit key is the only key tried: root-KEK ciphertext was re-encrypted under household keys (F-SEC-11).
    # Without a key this is a root-KEK value by design (e.g. stored credentials).
    fernet = _get_fernet(key if key else get_or_create_key())
    return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def encrypt_data(data: Any, key: Optional[bytes] = None) -> str:
    """Serializes arbitrary Python data to JSON and encrypts it with AES."""
    raw_json = json.dumps(data, default=str)
    return encrypt_string(raw_json, key=key)


def decrypt_data(ciphertext: str, key: Optional[bytes] = None) -> Any:
    """Decrypts AES ciphertext and parses the resulting JSON."""
    raw_json = decrypt_string(ciphertext, key=key)
    return json.loads(raw_json)


def encrypt_field(val: Any, key: Optional[bytes] = None) -> str:
    """Encrypts a sensitive column value into a Fernet ciphertext token. Returns empty string if None or empty."""
    if val is None or val == "":
        return ""
    return encrypt_string(str(val), key=key)


def decrypt_field(
    ciphertext: Any,
    default: Any = "",
    key: Optional[bytes] = None,
    is_numeric: Optional[bool] = None,
) -> Any:
    """
    Decrypts a Fernet ciphertext token, casting the result to the default value's type.
    Falls back gracefully to raw text or the default value if unencrypted or decryption fails.
    """
    if is_numeric is True and default == "":
        default = 0.0
    if ciphertext is None or ciphertext == "":
        return default
    val_str = str(ciphertext)
    try:
        decrypted = decrypt_string(val_str, key=key)
        val_str = decrypted
    except InvalidToken:
        if val_str.startswith("gAAAAA"):
            return default  # a token this key cannot open reads as absent, never as its ciphertext
        # Anything else is a legacy unencrypted value (db/plaintext_columns re-encrypts those at init).

    if is_numeric is True or isinstance(default, float):
        try:
            return float(val_str)
        except (ValueError, TypeError):
            return default if isinstance(default, (int, float)) else 0.0
    elif isinstance(default, int):
        try:
            return int(float(val_str))
        except (ValueError, TypeError):
            return default
    elif isinstance(default, str):
        return val_str
    return val_str
