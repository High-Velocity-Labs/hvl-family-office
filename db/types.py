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


def _family_office_key_resolver(db_path: Optional[Path], family_id: int) -> Optional[bytes]:
    """Resolves per-family FEK via security.get_family_key with root KEK fallback ring."""
    root_key: Optional[bytes] = None
    try:
        root_key = security.get_or_create_key()
    except Exception:
        pass

    fam_key: Optional[bytes] = None
    try:
        fam_key = security.get_family_key(db_path, family_id)
    except Exception:
        pass

    if fam_key and root_key and fam_key != root_key:
        return fam_key + b"," + root_key
    return fam_key or root_key


register_default_key_resolver(_family_office_key_resolver)

__all__ = [
    "EncryptedFloat",
    "EncryptedJSON",
    "EncryptedString",
    "encryption_context",
    "get_active_family_key",
    "register_default_key_resolver",
    "_ACTIVE_FAMILY_KEY",
    "_ACTIVE_FAMILY_ID",
    "_ACTIVE_DB_PATH",
]
