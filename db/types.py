"""
SQLAlchemy 2.0 `TypeDecorator` classes for transparent column-level Fernet encryption at rest.

Automatically encrypts Python values (`str`, `float`, `int`, `dict`, `list`) into Fernet
ciphertext tokens (`gAAAAA...`) before SQLite bind, and transparently decrypts + casts them
back to their native Python types on SQLite result load using the active family's DEK.
"""

from __future__ import annotations

from contextlib import contextmanager
import contextvars
import json
from pathlib import Path
from typing import Any, Iterator, Optional, Union

from sqlalchemy.engine import Dialect
from sqlalchemy.types import Text, TypeDecorator

import security

_ACTIVE_FAMILY_KEY: contextvars.ContextVar[Optional[bytes]] = contextvars.ContextVar(
    "_ACTIVE_FAMILY_KEY", default=None
)
_ACTIVE_FAMILY_ID: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_ACTIVE_FAMILY_ID", default=0
)
_ACTIVE_DB_PATH: contextvars.ContextVar[Optional[Path]] = contextvars.ContextVar(
    "_ACTIVE_DB_PATH", default=None
)


def get_active_family_key() -> Optional[bytes]:
    """Returns the active per-family Fernet DEK from contextvars, or falls back to root KEK."""
    key = _ACTIVE_FAMILY_KEY.get()
    if key is not None:
        return key
    fid = _ACTIVE_FAMILY_ID.get()
    db_path = _ACTIVE_DB_PATH.get()
    if fid > 0 and db_path is not None:
        resolved = security.get_family_key(db_path, fid)
        _ACTIVE_FAMILY_KEY.set(resolved)
        return resolved
    resolved = security.get_or_create_key()
    _ACTIVE_FAMILY_KEY.set(resolved)
    return resolved


@contextmanager
def encryption_context(
    db_path: Optional[Union[str, Path]] = None,
    family_id: int = 0,
    *,
    key: Optional[bytes] = None,
) -> Iterator[Optional[bytes]]:
    """
    Binds the active family's Fernet DEK context so all SQLAlchemy `Encrypted*`
    `TypeDecorator` columns encrypt and decrypt transparently.
    """
    fid = int(family_id or 0)
    resolved_path = Path(db_path) if db_path is not None else None

    tok_key = _ACTIVE_FAMILY_KEY.set(key)
    tok_fid = _ACTIVE_FAMILY_ID.set(fid)
    tok_path = _ACTIVE_DB_PATH.set(resolved_path)
    try:
        yield key
    finally:
        _ACTIVE_FAMILY_KEY.reset(tok_key)
        _ACTIVE_FAMILY_ID.reset(tok_fid)
        _ACTIVE_DB_PATH.reset(tok_path)


class EncryptedString(TypeDecorator[str]):
    """Transparently encrypts and decrypts `str` columns using the active family Fernet key."""

    impl = Text
    cache_ok = True

    def __init__(self, default: str = "") -> None:
        super().__init__()
        self._default = default

    def process_bind_param(self, value: Optional[Any], dialect: Dialect) -> str:
        if value is None or value == "":
            return ""
        val_str = str(value)
        if val_str.startswith("gAAAAA"):
            return val_str
        return security.encrypt_field(val_str, key=get_active_family_key())

    def process_result_value(self, value: Optional[Any], dialect: Dialect) -> str:
        if value is None or value == "":
            return self._default
        res = security.decrypt_field(
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
        return security.encrypt_field(num, key=get_active_family_key())

    def process_result_value(self, value: Optional[Any], dialect: Dialect) -> float:
        if value is None or value == "":
            return self._default
        res = security.decrypt_field(
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
        return security.encrypt_data(value, key=get_active_family_key())

    def process_result_value(self, value: Optional[Any], dialect: Dialect) -> Any:
        if value is None or value == "":
            return self._empty_default()
        val_str = str(value)
        key = get_active_family_key()
        try:
            return security.decrypt_data(val_str, key=key)
        except Exception:
            if not val_str.startswith("gAAAAA"):
                try:
                    return json.loads(val_str)
                except Exception:
                    pass
            return self._empty_default()
