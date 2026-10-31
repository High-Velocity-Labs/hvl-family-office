"""
Passphrase wrapping of the household FEK inside a portable `.fovault` backup (format v2).

Zero-In -> Zero-Out: nothing here reads the environment, a database, or the session, and the
passphrase is never stored or logged. The wrapped FEK is a self-describing JSON envelope:

    {"fovault_format": 2,
     "kdf": {"name": "scrypt", "n": 131072, "r": 8, "p": 1, "salt": "<b64 16 random bytes>"},
     "cipher": "aes-256-gcm", "nonce": "<b64 12 random bytes>", "ct": "<b64 ciphertext+tag>"}

The cipher's associated data is the canonical JSON of `{"fovault_format", "kdf"}`, so any change to
the format version or the KDF parameters/salt makes decryption fail authentication.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FOVAULT_FORMAT_VERSION = 2
MIN_EXPORT_PASSPHRASE_LEN = 12
MAX_PASSPHRASE_LEN = 128

_SCRYPT_N = 2**17
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_NONCE_BYTES = 12
# Upper bounds applied to parameters read back from an untrusted file (denial-of-service guard).
_MAX_SCRYPT_N = 2**18
_MAX_SCRYPT_R = 16
_MAX_SCRYPT_P = 4


class FovaultPassphraseError(ValueError):
    """Base class for passphrase problems; the message is safe to show to the user."""


class PassphraseRequired(FovaultPassphraseError):
    pass


class WeakPassphrase(FovaultPassphraseError):
    pass


class WrongPassphrase(FovaultPassphraseError):
    pass


class FovaultFormatError(ValueError):
    """The embedded key envelope is malformed or uses an unsupported format."""


class LegacyFovaultFormat(ValueError):
    """The file uses the pre-v2 unprotected key wrapping and the caller did not opt in to legacy import."""


LEGACY_FORMAT_MESSAGE = (
    "This .fovault file uses the old unprotected format (its key is not protected by a passphrase). "
    "It is refused by default. To import it anyway, tick 'Import an old-format backup' and try again."
)


def validate_export_passphrase(passphrase: Any, confirm: Any = None) -> str:
    """Returns the passphrase if acceptable for a new export; raises a user-facing error otherwise."""
    if not isinstance(passphrase, str) or passphrase == "":
        raise PassphraseRequired("A passphrase is required to export a vault backup.")
    if len(passphrase) < MIN_EXPORT_PASSPHRASE_LEN:
        raise WeakPassphrase(f"Choose a passphrase of at least {MIN_EXPORT_PASSPHRASE_LEN} characters.")
    if len(passphrase) > MAX_PASSPHRASE_LEN:
        raise WeakPassphrase(f"Passphrase must be at most {MAX_PASSPHRASE_LEN} characters.")
    if len(set(passphrase)) < 4:
        raise WeakPassphrase("Choose a passphrase with more variety than a few repeated characters.")
    if confirm is not None and confirm != passphrase:
        raise PassphraseRequired("The passphrase and its confirmation do not match.")
    return passphrase


def _derive_key(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def _aad(fmt: int, kdf: dict[str, Any]) -> bytes:
    return json.dumps({"fovault_format": fmt, "kdf": kdf}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: Any) -> bytes:
    try:
        return base64.b64decode(str(value), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FovaultFormatError("Malformed key envelope in .fovault file.") from exc


def wrap_fek(raw_fek: bytes, passphrase: str) -> dict[str, Any]:
    """Wraps `raw_fek` under a key derived from `passphrase` with a fresh random salt and nonce."""
    validate_export_passphrase(passphrase)
    kdf = {
        "name": "scrypt", "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P,
        "salt": _b64(secrets.token_bytes(_SALT_BYTES)),
    }
    key = _derive_key(passphrase, _unb64(kdf["salt"]), _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, bytes(raw_fek), _aad(FOVAULT_FORMAT_VERSION, kdf))
    return {
        "fovault_format": FOVAULT_FORMAT_VERSION, "kdf": kdf,
        "cipher": "aes-256-gcm", "nonce": _b64(nonce), "ct": _b64(ct),
    }


def is_v2_envelope(value: Any) -> bool:
    return isinstance(value, dict) and "fovault_format" in value


def unwrap_fek(envelope: Any, passphrase: str) -> bytes:
    """Returns the FEK, or raises `WrongPassphrase` (authentication failure) / `FovaultFormatError`."""
    if not is_v2_envelope(envelope):
        raise FovaultFormatError("Malformed key envelope in .fovault file.")
    if envelope.get("fovault_format") != FOVAULT_FORMAT_VERSION or envelope.get("cipher") != "aes-256-gcm":
        raise FovaultFormatError("This .fovault file was written by a newer, unsupported version.")
    kdf = envelope.get("kdf")
    if not isinstance(kdf, dict) or kdf.get("name") != "scrypt":
        raise FovaultFormatError("Unsupported key-derivation function in .fovault file.")
    try:
        n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FovaultFormatError("Malformed key-derivation parameters in .fovault file.") from exc
    if not (2 <= n <= _MAX_SCRYPT_N and n & (n - 1) == 0 and 1 <= r <= _MAX_SCRYPT_R and 1 <= p <= _MAX_SCRYPT_P):
        raise FovaultFormatError("Key-derivation parameters in .fovault file are out of range.")
    if not isinstance(passphrase, str) or passphrase == "":
        raise PassphraseRequired("This backup is protected. Enter the passphrase chosen when it was exported.")
    if len(passphrase) > MAX_PASSPHRASE_LEN:
        raise WrongPassphrase("Wrong passphrase.")
    key = _derive_key(passphrase, _unb64(kdf.get("salt")), n, r, p)
    try:
        return AESGCM(key).decrypt(
            _unb64(envelope.get("nonce")), _unb64(envelope.get("ct")), _aad(FOVAULT_FORMAT_VERSION, kdf)
        )
    except InvalidTag as exc:
        raise WrongPassphrase("Wrong passphrase.") from exc
