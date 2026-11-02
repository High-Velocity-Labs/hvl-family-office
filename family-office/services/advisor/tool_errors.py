"""Failures an advisor tool reports to the model as `{"error": ..., "status": "unavailable"}`.

A tool reads household data that can be legitimately unavailable: the vault is locked (`PermissionError`, an `OSError`),
the file or database cannot be read (`OSError`, `SQLAlchemyError`), a stored value cannot be decrypted or parsed
(`InvalidToken`, `DecryptionError` which is a `ValueError`), or the model passed an input the tool rejects
(`ValueError`).
Anything else is a defect in the tool and must raise to the route error handler, never be reported as "unavailable".
"""

from __future__ import annotations

from cryptography.fernet import InvalidToken
from sqlalchemy.exc import SQLAlchemyError

ADVISOR_TOOL_ERRORS: tuple[type[Exception], ...] = (OSError, ValueError, SQLAlchemyError, InvalidToken)
