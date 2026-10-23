"""
SQLAlchemy 2.0 `TypeDecorator` classes for transparent column-level Fernet encryption at rest.

Automatically encrypts Python values (`str`, `float`, `int`, `dict`, `list`) into Fernet
ciphertext tokens (`gAAAAA...`) before SQLite bind, and transparently decrypts + casts them
back to their native Python types on SQLite result load using the active household's FEK.
"""

from __future__ import annotations

from contextlib import contextmanager
import contextvars
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Union
import warnings

from sqlalchemy.engine import Dialect
from sqlalchemy.types import Text, TypeDecorator

from hvl_common.security.crypto import (
    decrypt_data,
    decrypt_field,
    encrypt_data,
    encrypt_field,
)

logger = logging.getLogger(__name__)

KeyResolverFn = Callable[[Optional[Path], int], Optional[bytes]]

_ACTIVE_FAMILY_KEY: contextvars.ContextVar[Optional[bytes]] = contextvars.ContextVar(
    "_ACTIVE_FAMILY_KEY", default=None
)
_ACTIVE_FAMILY_ID: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_ACTIVE_FAMILY_ID", default=0
)
_ACTIVE_DB_PATH: contextvars.ContextVar[Optional[Path]] = contextvars.ContextVar(
    "_ACTIVE_DB_PATH", default=None
)
_ACTIVE_KEY_RESOLVER: contextvars.ContextVar[Optional[KeyResolverFn]] = contextvars.ContextVar(
    "_ACTIVE_KEY_RESOLVER", default=None
)
_DEFAULT_KEY_RESOLVER: Optional[KeyResolverFn] = None


def register_default_key_resolver(resolver: Optional[KeyResolverFn]) -> None:
    """Registers a process-wide fallback FEK resolver `(db_path, household_id) -> bytes`."""
    global _DEFAULT_KEY_RESOLVER
    _DEFAULT_KEY_RESOLVER = resolver


def get_active_family_key() -> Optional[bytes]:
    """Returns the active per-household Fernet FEK from contextvars or the registered resolver."""
    key = _ACTIVE_FAMILY_KEY.get()
    if key is not None:
        return key
    fid = _ACTIVE_FAMILY_ID.get()
    db_path = _ACTIVE_DB_PATH.get()
    resolver = _ACTIVE_KEY_RESOLVER.get() or _DEFAULT_KEY_RESOLVER
    if resolver is not None:
        resolved = resolver(db_path, fid)
        if resolved is not None:
            _ACTIVE_FAMILY_KEY.set(resolved)
            return resolved
    return None


@contextmanager
def encryption_context(
    db_path: Optional[Union[str, Path]] = None,
    family_id: int = 0,
    *,
    key: Optional[bytes] = None,
    key_resolver: Optional[KeyResolverFn] = None,
) -> Iterator[Optional[bytes]]:
    """
    Binds the active household's Fernet FEK context so all SQLAlchemy `Encrypted*`
    `TypeDecorator` columns encrypt and decrypt transparently.
    """
    fid = int(family_id or 0)
    resolved_path = Path(db_path) if db_path is not None else None

    tok_key = _ACTIVE_FAMILY_KEY.set(key)
    tok_fid = _ACTIVE_FAMILY_ID.set(fid)
    tok_path = _ACTIVE_DB_PATH.set(resolved_path)
    tok_res = _ACTIVE_KEY_RESOLVER.set(key_resolver) if key_resolver is not None else None
    try:
        yield key
    finally:
        _ACTIVE_FAMILY_KEY.reset(tok_key)
        _ACTIVE_FAMILY_ID.reset(tok_fid)
        _ACTIVE_DB_PATH.reset(tok_path)
        if tok_res is not None:
            _ACTIVE_KEY_RESOLVER.reset(tok_res)


def _require_active_fek_or_fallback(fallback_str: str) -> Optional[bytes]:
    """Returns the active FEK or raises RuntimeError unless HVL_ALLOW_UNENCRYPTED_FALLBACK=1 is set."""
    active_key = get_active_family_key()
    if active_key:
        return active_key
    if os.getenv("HVL_ALLOW_UNENCRYPTED_FALLBACK") == "1":
        warnings.warn(
            "Writing Encrypted* column without active encryption_context FEK (HVL_ALLOW_UNENCRYPTED_FALLBACK=1).",
            RuntimeWarning,
            stacklevel=3,
        )
        return None
    raise RuntimeError(
        "Refusing to write sensitive EncryptedType column without an active encryption_context FEK."
    )


def _encrypt_str(val_str: str) -> str:
    """Encrypts a plaintext string with the active FEK or fails closed."""
    if not val_str:
        return ""
    if val_str.startswith("gAAAAA"):
        return val_str
    active_key = _require_active_fek_or_fallback(val_str)
    if not active_key:
        return val_str
    return encrypt_field(val_str, key=active_key)


class EncryptedString(TypeDecorator[str]):
    """Transparently encrypts and decrypts `str` columns using the active household Fernet FEK."""

    impl = Text
    cache_ok = True

    def __init__(self, default: str = "") -> None:
        super().__init__()
        self._default = default

    def process_bind_param(self, value: Optional[Any], dialect: Dialect) -> str:
        if value is None or value == "":
            return ""
        return _encrypt_str(str(value))

    def process_result_value(self, value: Optional[Any], dialect: Dialect) -> str:
        if value is None or value == "":
            return self._default
        res = decrypt_field(
            value,
            default=self._default,
            key=get_active_family_key(),
            is_numeric=False,
        )
        return str(res if res is not None else self._default)


class EncryptedFloat(TypeDecorator[float]):
    """Transparently encrypts and decrypts `float` columns as Fernet ciphertext in SQLite."""

    impl = Text
    cache_ok = True

    def __init__(self, default: float = 0.0) -> None:
        super().__init__()
        self._default = float(default)

    def process_bind_param(self, value: Optional[Any], dialect: Dialect) -> str:
        if value is None or value == "":
            return ""
        if isinstance(value, str) and value.startswith("gAAAAA"):
            return value
        try:
            num = float(value)
        except (ValueError, TypeError):
            num = self._default
        active_key = _require_active_fek_or_fallback(str(num))
        if not active_key:
            return str(num)
        return encrypt_field(num, key=active_key)

    def process_result_value(self, value: Optional[Any], dialect: Dialect) -> float:
        if value is None or value == "":
            return self._default
        res = decrypt_field(
            value,
            default=self._default,
            key=get_active_family_key(),
            is_numeric=True,
        )
        try:
            return float(res if res is not None else self._default)
        except (ValueError, TypeError):
            return self._default


class EncryptedJSON(TypeDecorator[Any]):
    """Transparently JSON-serializes + Fernet-encrypts structured dicts/lists in SQLite."""

    impl = Text
    cache_ok = True

    def __init__(self, default_type: str = "dict") -> None:
        super().__init__()
        self._default_type = default_type

    def _empty_default(self) -> Any:
        if self._default_type == "list":
            return []
        if self._default_type == "none":
            return None
        return {}

    def process_bind_param(self, value: Optional[Any], dialect: Dialect) -> str:
        if value is None or value == "":
            return ""
        if isinstance(value, str) and value.startswith("gAAAAA"):
            return value
        raw_json = json.dumps(value, default=str)
        active_key = _require_active_fek_or_fallback(raw_json)
        if not active_key:
            return raw_json
        return encrypt_data(value, key=active_key)

    def process_result_value(self, value: Optional[Any], dialect: Dialect) -> Any:
        if value is None or value == "":
            return self._empty_default()
        val_str = str(value)
        key = get_active_family_key()
        if key:
            try:
                return decrypt_data(val_str, key=key)
            except Exception:
                pass
        if not val_str.startswith("gAAAAA"):
            try:
                return json.loads(val_str)
            except Exception:
                pass
        return self._empty_default()
