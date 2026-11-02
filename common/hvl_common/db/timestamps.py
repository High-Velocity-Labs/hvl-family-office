"""Stored timestamp parsing shared by the apps' repositories (`hvl_common.db.timestamps`)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def parse_iso_utc(raw_ts: Any) -> Optional[datetime]:
    """An ISO-8601 column value (`Z` suffix allowed) as an aware UTC datetime; None when empty or unparseable."""
    if not raw_ts:
        return None
    s = str(raw_ts).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


__all__ = ["parse_iso_utc"]
