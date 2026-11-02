"""
Cryptographic encryption, MultiFernet key rings, blind indexing, and PBKDF2 passphrase helpers.

Trust model: the FEK cookie wrapping key (`wrap_cookie_fek`) is derived from the server's SECRET_KEY,
so the server can always unwrap any FEK cookie it issued. This is a server-trust design (the cookie
keeps the FEK out of the database and off the browser in plaintext), not zero-knowledge.
Only the passphrase wrap (`wrap_fek_with_passphrase`) is held against the server.
"""

from __future__ import annotations

import base64
from collections import OrderedDict
from functools import lru_cache
import hashlib
import json
import secrets
from typing import Any, List, Optional, Union
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

VAULT_COOKIE_NAME = "hvl_vault_fek"
ADMIN_GATE_COOKIE_NAME = "hvl_beta_admin"
_ADMIN_GATE_SALT = b"hvl_beta_admin_gate_v1"
PBKDF2_PASSPHRASE_ITERATIONS = 600_000
CIPHERTEXT_PREFIX = "gAAAAA"
# Single lifetime for the wrapped-FEK cookie: used as the browser `max_age` AND the Fernet unwrap TTL.
VAULT_COOKIE_TTL_SECONDS = 30 * 86400


class DecryptionError(ValueError):
    """A value that is a Fernet ciphertext could not be decrypted (wrong/missing key or corrupt token)."""


def is_ciphertext(value: Any) -> bool:
    """True when `value` looks like a Fernet token; anything else is legacy plaintext."""
    return isinstance(value, str) and value.startswith(CIPHERTEXT_PREFIX)

_FERNET_RING_CACHE: OrderedDict[bytes, Union[Fernet, MultiFernet]] = OrderedDict()
_FERNET_CACHE_MAX = 128


def generate_secret_key() -> str:
    """Generates a new URL-safe base64-encoded 32-byte Fernet key."""
    return Fernet.generate_key().decode("utf-8")


@lru_cache(maxsize=64)
def derive_key(secret: str, salt: bytes = b"hvl_salt_v1") -> bytes:
    """
    Derives a deterministic Fernet key from a string secret using PBKDF2/SHA256.
    The default salt is static ON PURPOSE and must never change: assistant's server KEK is
    derive_key(FLASK_SECRET_KEY), so a new salt would lock its data. The secrets fed in are high-entropy
    server keys, so a static salt is no weakness here. Do not use it for low-entropy input (passwords, PINs);
    use derive_passphrase_fernet_key, which takes a random per-blob salt.
    """
    derived = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 100_000)
    return base64.urlsafe_b64encode(derived[:32])


def parse_fernet_keys(raw_key: Union[bytes, str]) -> List[bytes]:
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


def get_fernet(key: Union[bytes, str]) -> Union[Fernet, MultiFernet]:
    """Returns a cached Fernet or MultiFernet instance for a single or comma-separated key ring."""
    eff_key = key.encode("utf-8") if isinstance(key, str) else bytes(key)
    cached = _FERNET_RING_CACHE.get(eff_key)
    if cached is not None:
        _FERNET_RING_CACHE.move_to_end(eff_key)
        return cached
    parsed_keys = parse_fernet_keys(eff_key)
    if not parsed_keys:
        raise ValueError("No valid Fernet key provided")
    fernet_obj: Union[Fernet, MultiFernet] = (
        Fernet(parsed_keys[0])
        if len(parsed_keys) == 1
        else MultiFernet([Fernet(k) for k in parsed_keys])
    )
    _FERNET_RING_CACHE[eff_key] = fernet_obj
    while len(_FERNET_RING_CACHE) > _FERNET_CACHE_MAX:
        _FERNET_RING_CACHE.popitem(last=False)
    return fernet_obj


def encrypt_value(plain_text: str, key: Union[bytes, str]) -> str:
    """Encrypts plaintext string with the provided Fernet key or key ring. Returns base64 string."""
    if not plain_text:
        return ""
    f = get_fernet(key)
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_value(cipher_text: str, key: Union[bytes, str]) -> str:
    """Decrypts a Fernet token with the key or key ring. Empty input returns ""; failure raises DecryptionError."""
    if not cipher_text:
        return ""
    try:
        return get_fernet(key).decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise DecryptionError("Fernet token could not be decrypted with the supplied key") from exc


def try_decrypt_value(cipher_text: str, key: Union[bytes, str]) -> Optional[str]:
    """Explicit trial decryption for probing candidate keys. Returns None when this key does not open the token."""
    try:
        return decrypt_value(cipher_text, key)
    except DecryptionError:
        return None


def encrypt_field(val: Any, key: Optional[Union[bytes, str]]) -> str:
    """Encrypts a column value into a Fernet ciphertext token. Idempotent if already encrypted under `key`."""
    if val is None or val == "" or not key:
        return ""
    val_str = str(val)
    if is_ciphertext(val_str) and try_decrypt_value(val_str, key):
        return val_str
    return encrypt_value(val_str, key)


def _cast_field(text: str, default: Any, is_numeric: Optional[bool]) -> Any:
    """Casts decrypted/legacy text to the type of `default`. Raises ValueError/TypeError if not castable."""
    if is_numeric is True or isinstance(default, float):
        return float(text)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(float(text))
    return text


def decrypt_field(
    ciphertext: Any,
    default: Any = "",
    key: Optional[Union[bytes, str]] = None,
    is_numeric: Optional[bool] = None,
) -> Any:
    """
    Decrypts a column value, casting to the type of `default`.
    - None / "" -> `default`.
    - Not a Fernet token (no `gAAAAA` prefix) -> legacy pre-encryption plaintext, returned explicitly
      (cast to `default`'s type; `default` if the legacy text is not castable).
    - Fernet token -> decrypted with `key`; a missing key, wrong key, corrupt token, or non-castable
      plaintext raises DecryptionError. Never returns `default` for a ciphertext.
    """
    if is_numeric is True and default == "":
        default = 0.0
    if ciphertext is None or ciphertext == "":
        return default
    val_str = str(ciphertext)
    if not is_ciphertext(val_str):
        try:
            return _cast_field(val_str, default, is_numeric)
        except (ValueError, TypeError):
            return default if isinstance(default, (int, float)) else 0.0
    if not key:
        raise DecryptionError("Encrypted value read without an active key")
    plain = decrypt_value(val_str, key)
    try:
        return _cast_field(plain, default, is_numeric)
    except (ValueError, TypeError) as exc:
        raise DecryptionError("Decrypted value does not match the expected column type") from exc


def encrypt_data(data: Any, key: Union[bytes, str]) -> str:
    """Serializes arbitrary Python data to JSON and encrypts it with Fernet."""
    raw_json = json.dumps(data, default=str)
    return encrypt_value(raw_json, key)


def decrypt_data(ciphertext: str, key: Union[bytes, str]) -> Any:
    """Decrypts Fernet ciphertext and parses the resulting JSON."""
    return json.loads(decrypt_value(ciphertext, key))


def derive_passphrase_fernet_key(
    passphrase: str,
    salt: bytes,
    iterations: int = PBKDF2_PASSPHRASE_ITERATIONS,
) -> bytes:
    """Derives a URL-safe base64-encoded 32-byte Fernet key from a user passphrase/PIN and salt."""
    raw_dk = hashlib.pbkdf2_hmac(
        "sha256",
        str(passphrase).encode("utf-8"),
        bytes(salt),
        int(iterations),
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw_dk)


def wrap_fek_with_passphrase(
    raw_fek: Union[bytes, str],
    passphrase: str,
    iterations: int = PBKDF2_PASSPHRASE_ITERATIONS,
) -> str:
    """Wraps a Family Encryption Key (FEK) using a user-supplied Master Passphrase/PIN."""
    salt = secrets.token_bytes(16)
    wk = derive_passphrase_fernet_key(passphrase, salt, iterations=iterations)
    fek_bytes = raw_fek if isinstance(raw_fek, bytes) else str(raw_fek).encode("utf-8")
    ct = Fernet(wk).encrypt(fek_bytes).decode("utf-8")
    return f"pbkdf2_sha256${int(iterations)}${salt.hex()}${ct}"


def unwrap_fek_with_passphrase(wrapped_blob: str, passphrase: str) -> Optional[bytes]:
    """Unwraps a household's FEK from a pbkdf2_sha256 blob using the user's passphrase/PIN."""
    try:
        parts = str(wrapped_blob or "").strip().split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return None
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        ct = parts[3].encode("utf-8")
        wk = derive_passphrase_fernet_key(passphrase, salt, iterations=iterations)
        raw_fek = Fernet(wk).decrypt(ct)
        get_fernet(raw_fek)
        return raw_fek
    except (InvalidToken, ValueError):
        return None


def wrap_cookie_fek(raw_fek: Union[bytes, str], secret_key: Union[bytes, str]) -> str:
    """
    Encrypts a raw Family Encryption Key (FEK) for cookie storage under PBKDF2(secret_key, static salt).
    Server-trust, not zero-knowledge: anyone holding secret_key can unwrap it, so the server can always
    recover the FEK. The wrapping key is derive_key(secret_key) with its static salt.
    """
    secret_str = secret_key.decode("utf-8") if isinstance(secret_key, bytes) else str(secret_key)
    fek_bytes = raw_fek.encode("utf-8") if isinstance(raw_fek, str) else raw_fek
    wrapping_key = derive_key(secret_str)
    return Fernet(wrapping_key).encrypt(fek_bytes).decode("utf-8")


def unwrap_cookie_fek(
    token: str,
    secret_key: Union[bytes, str],
    max_age_seconds: Optional[int] = VAULT_COOKIE_TTL_SECONDS,
) -> Optional[bytes]:
    """
    Decrypts a wrapped FEK cookie token using derive_key(secret_key), with an optional Fernet TTL.
    Server-trust: whoever holds secret_key can unwrap any cookie. Fernet authenticates the token
    (HMAC-SHA256), so a forged or tampered token returns None; no hand-rolled comparison is involved.
    """
    if not token or not secret_key:
        return None
    try:
        secret_str = secret_key.decode("utf-8") if isinstance(secret_key, bytes) else str(secret_key)
        token_bytes = token.encode("utf-8") if isinstance(token, str) else token
        wrapping_key = derive_key(secret_str)
        f = Fernet(wrapping_key)
        if max_age_seconds is not None:
            return f.decrypt(token_bytes, ttl=int(max_age_seconds))
        return f.decrypt(token_bytes)
    except (InvalidToken, ValueError):
        return None


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
        except (InvalidToken, ValueError):
            continue
    return None
