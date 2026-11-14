"""
The one passphrase wrap for a household FEK: scrypt + AES-256-GCM, in a self-describing JSON envelope.

Zero-In -> Zero-Out: nothing here reads the environment, a database, or the session, and the passphrase
is never stored or logged. Passphrase policy (a PIN's or an export passphrase's minimum length) belongs to
the calling app; this module only refuses an empty or over-long one. The envelope:

    {"fovault_format": 2,
     "kdf": {"name": "scrypt", "n": 131072, "r": 8, "p": 1, "salt": "<b64 16 random bytes>"},
     "cipher": "aes-256-gcm", "nonce": "<b64 12 random bytes>", "ct": "<b64 ciphertext+tag>"}

The `fovault_format` key is the format's first name (family-office `.fovault` backups, where it began) and
stays as is, so every backup already written still opens. The cipher's associated data is the canonical
JSON of `{"fovault_format", "kdf"}`, so any change to the version or the KDF parameters/salt fails authentication.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from typing import Any, Union

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

PASSPHRASE_ENVELOPE_VERSION = 2
MAX_PASSPHRASE_LEN = 128

_FORMAT_KEY = "fovault_format"
_SCRYPT_N = 2**17
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_NONCE_BYTES = 12
# Upper bounds on parameters read back from an untrusted envelope (denial-of-service guard): what writers use.
_MAX_SCRYPT_N = _SCRYPT_N
_MAX_SCRYPT_R = _SCRYPT_R
_MAX_SCRYPT_P = _SCRYPT_P


class PassphraseError(ValueError):
    """Base class for passphrase problems; the message is safe to show to the user."""


class PassphraseRequired(PassphraseError):
    pass


class WrongPassphrase(PassphraseError):
    pass


class PassphraseEnvelopeError(ValueError):
    """The key envelope is malformed or uses an unsupported format."""


def _derive_key(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def _aad(fmt: int, kdf: dict[str, Any]) -> bytes:
    return json.dumps({_FORMAT_KEY: fmt, "kdf": kdf}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: Any) -> bytes:
    try:
        return base64.b64decode(str(value), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PassphraseEnvelopeError("Malformed key envelope.") from exc


def is_passphrase_envelope(value: Any) -> bool:
    return isinstance(value, dict) and _FORMAT_KEY in value


def wrap_fek_with_passphrase(raw_fek: Union[bytes, str], passphrase: str) -> dict[str, Any]:
    """Wraps `raw_fek` under a key derived from `passphrase` with a fresh random salt and nonce."""
    if not isinstance(passphrase, str) or passphrase == "":
        raise PassphraseRequired("A passphrase is required.")
    if len(passphrase) > MAX_PASSPHRASE_LEN:
        raise PassphraseError(f"Passphrase must be at most {MAX_PASSPHRASE_LEN} characters.")
    fek_bytes = raw_fek if isinstance(raw_fek, bytes) else str(raw_fek).encode("utf-8")
    salt = secrets.token_bytes(_SALT_BYTES)
    kdf = {"name": "scrypt", "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P, "salt": _b64(salt)}
    key = _derive_key(passphrase, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, fek_bytes, _aad(PASSPHRASE_ENVELOPE_VERSION, kdf))
    return {
        _FORMAT_KEY: PASSPHRASE_ENVELOPE_VERSION,
        "kdf": kdf,
        "cipher": "aes-256-gcm",
        "nonce": _b64(nonce),
        "ct": _b64(ct),
    }


def unwrap_fek_with_passphrase(envelope: Any, passphrase: str) -> bytes:
    """Returns the FEK, or raises `WrongPassphrase` / `PassphraseRequired` / `PassphraseEnvelopeError`."""
    if not is_passphrase_envelope(envelope):
        raise PassphraseEnvelopeError("Malformed key envelope.")
    if envelope.get(_FORMAT_KEY) != PASSPHRASE_ENVELOPE_VERSION or envelope.get("cipher") != "aes-256-gcm":
        raise PassphraseEnvelopeError("This key was written by a newer, unsupported version.")
    kdf = envelope.get("kdf")
    if not isinstance(kdf, dict) or kdf.get("name") != "scrypt":
        raise PassphraseEnvelopeError("Unsupported key-derivation function.")
    try:
        n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PassphraseEnvelopeError("Malformed key-derivation parameters.") from exc
    if not (2 <= n <= _MAX_SCRYPT_N and n & (n - 1) == 0 and 1 <= r <= _MAX_SCRYPT_R and 1 <= p <= _MAX_SCRYPT_P):
        raise PassphraseEnvelopeError("Key-derivation parameters are out of range.")
    if not isinstance(passphrase, str) or passphrase == "":
        raise PassphraseRequired("A passphrase is required.")
    if len(passphrase) > MAX_PASSPHRASE_LEN:
        raise WrongPassphrase("Wrong passphrase.")
    salt, nonce, ct = _unb64(kdf.get("salt")), _unb64(envelope.get("nonce")), _unb64(envelope.get("ct"))
    if len(salt) != _SALT_BYTES or len(nonce) != _NONCE_BYTES:
        raise PassphraseEnvelopeError("Malformed key envelope.")
    key = _derive_key(passphrase, salt, n, r, p)
    try:
        return AESGCM(key).decrypt(nonce, ct, _aad(PASSPHRASE_ENVELOPE_VERSION, kdf))
    except InvalidTag as exc:
        raise WrongPassphrase("Wrong passphrase.") from exc
