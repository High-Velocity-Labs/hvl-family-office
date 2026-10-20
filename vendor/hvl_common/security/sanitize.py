"""
Input sanitization and validation utilities for High Velocity Labs applications.
"""

from __future__ import annotations
import re
from typing import Any


def sanitize_text(
    val: Any,
    max_length: int = 100,
    field_name: str = "Field",
    required: bool = False,
    multiline: bool = False,
    default: str = "",
) -> str:
    """
    Sanitizes user input string:
    - Strips leading/trailing whitespace.
    - Strips non-printable ASCII control characters (preserving newlines/tabs only if multiline=True).
    - Validates required constraints.
    - Enforces maximum length constraints.
    Raises ValueError with a clear user-friendly message if validation fails.
    """
    if val is None:
        if required:
            raise ValueError(f"{field_name} is required.")
        return default

    s = str(val).strip()
    if multiline:
        # Strip ASCII control characters except newline (\n), carriage return (\r), and tab (\t)
        s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    else:
        # Strip all ASCII control characters including newlines
        s = re.sub(r"[\x00-\x1f\x7f]", "", s).strip()

    if required and not s:
        raise ValueError(f"{field_name} is required.")

    if len(s) > max_length:
        raise ValueError(f"{field_name} exceeds maximum length of {max_length} characters.")

    return s if s else default
