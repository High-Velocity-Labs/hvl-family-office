"""
SQLAlchemy 2.0 `TypeDecorator` classes for transparent column-level Fernet encryption at rest.

Delegates core implementation to `hvl_common.db.types` with `security.get_family_key` registered
as default key resolver.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from hvl_common.db.types import (
    EncryptedFloat,
    EncryptedJSON,
    EncryptedString,
    encryption_context,
    get_active_family_key,
    register_default_key_resolver,
    _ACTIVE_FAMILY_KEY,
    _ACTIVE_FAMILY_ID,
    _ACTIVE_DB_PATH,
)
import security


def family_key_ring(db_path: Optional[Path], family_id: int) -> Optional[bytes]:
    """
    Resolves the per-family FEK via security.get_family_key and fails closed: a locked vault raises
    PermissionError instead of silently falling back to the root KEK. Root-KEK ciphertext no longer has a read
    path here: `security.get_family_key` re-encrypts it under the household key first (F-SEC-11).
    Every column read and write uses this one key.
    """
    return security.get_family_key(db_path, family_id)


register_default_key_resolver(family_key_ring)

__all__ = [
    "EncryptedFloat",
    "EncryptedJSON",
    "EncryptedString",
    "encryption_context",
    "family_key_ring",
    "get_active_family_key",
    "register_default_key_resolver",
    "_ACTIVE_FAMILY_KEY",
    "_ACTIVE_FAMILY_ID",
    "_ACTIVE_DB_PATH",
]
