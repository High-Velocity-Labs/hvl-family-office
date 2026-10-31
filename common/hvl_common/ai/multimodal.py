"""
Multimodal Chat Attachment Primitives for High Velocity Labs AI Applications.

Provides validation and base64 decoding for incoming chat attachments (images, PDFs, text/CSV),
Gemini multimodal `Part` construction (`types.Part.from_bytes` with `inline_data` fallback),
and compact metadata sanitization with a 30-day thumbnail auto-expiry policy.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

ATTACHMENT_RETENTION_DAYS = 30
MAX_ATTACHMENTS_PER_TURN = 4
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_THUMB_DATA_URL_CHARS = 24000
MAX_TEXT_ATTACHMENT_CHARS = 12000

ALLOWED_ATTACHMENT_MIMES = frozenset({
    "image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf", "text/plain", "text/csv",
})

_DATA_URL_PREFIX_RE = re.compile(r"^data:([^;,]+)?(?:;charset=[^;,]+)?;base64,", re.IGNORECASE)


def _sanitize_filename(raw_name: Any) -> str:
    """Normalizes an attachment filename, stripping directory traversal paths and control characters."""
    cleaned = str(raw_name or "attachment").strip().replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", cleaned).strip()
    return (cleaned or "attachment")[:120]


def _sanitize_thumb_data_url(raw_thumb: Any) -> str:
    """Retains thumbnail data URL only if it is an inline image within the compact character budget."""
    if not isinstance(raw_thumb, str):
        return ""
    thumb = raw_thumb.strip()
    if not thumb.startswith("data:image/") or len(thumb) > MAX_THUMB_DATA_URL_CHARS:
        return ""
    return thumb


def _decode_base64_payload(raw_b64: str, filename: str) -> tuple[bytes, str]:
    """Strips optional data URL header and decodes base64 string into bytes and inferred mime."""
    inferred_mime = ""
    payload = raw_b64.strip()
    if m := _DATA_URL_PREFIX_RE.match(payload):
        inferred_mime = (m.group(1) or "").strip().lower()
        payload = payload[m.end():].strip()
    try:
        return base64.b64decode(payload, validate=False), inferred_mime
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Attachment '{filename}' contains invalid base64 data.") from exc


def normalize_incoming_attachments(
    raw_attachments: Any,
    max_count: int = MAX_ATTACHMENTS_PER_TURN,
    max_bytes: int = MAX_ATTACHMENT_BYTES,
) -> list[dict[str, Any]]:
    """Validates and normalizes client-supplied attachment dicts for a chat turn."""
    if not raw_attachments:
        return []
    if not isinstance(raw_attachments, (list, tuple)):
        raise ValueError("Attachments payload must be a list.")
    if len(raw_attachments) > max_count:
        raise ValueError(f"Maximum {max_count} attachments allowed per message.")

    normalized: list[dict[str, Any]] = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            raise ValueError("Each attachment must be an object.")

        clean_name = _sanitize_filename(item.get("name") or item.get("filename"))
        mime_type = str(item.get("mime_type") or item.get("type") or "").strip().lower()

        if isinstance(item.get("data_bytes"), (bytes, bytearray)):
            raw_bytes = bytes(item["data_bytes"])
        else:
            raw_b64 = item.get("data_b64") or item.get("data_url") or item.get("data") or ""
            if not isinstance(raw_b64, str) or not raw_b64.strip():
                raise ValueError(f"Attachment '{clean_name}' is missing file data.")
            raw_bytes, inferred_mime = _decode_base64_payload(raw_b64, clean_name)
            if not mime_type and inferred_mime:
                mime_type = inferred_mime

        if mime_type == "image/jpg":
            mime_type = "image/jpeg"
        if mime_type not in ALLOWED_ATTACHMENT_MIMES:
            raise ValueError(
                f"Unsupported file type '{mime_type or 'unknown'}' for '{clean_name}'. "
                "Supported types: JPEG, PNG, WebP, GIF, PDF, CSV, and TXT."
            )
        if not raw_bytes:
            raise ValueError(f"Attachment '{clean_name}' is empty.")
        if len(raw_bytes) > max_bytes:
            max_mb = max(1, max_bytes // (1024 * 1024))
            raise ValueError(f"Attachment '{clean_name}' exceeds the {max_mb} MB size limit.")

        normalized.append({
            "name": clean_name,
            "mime_type": mime_type,
            "data_bytes": raw_bytes,
            "size_bytes": len(raw_bytes),
            "thumb_data_url": _sanitize_thumb_data_url(item.get("thumb_data_url")),
            "kind": "image" if mime_type.startswith("image/") else "document",
        })
    return normalized


def build_multimodal_user_parts(
    prompt_text: str,
    attachments: Sequence[dict[str, Any]] | None = None,
) -> list[Any]:
    """Builds the multimodal `parts` list for a Gemini `{"role": "user", "parts": ...}` turn."""
    parts: list[Any] = []
    for att in attachments or ():
        if not isinstance(att, dict):
            continue
        name = _sanitize_filename(att.get("name") or att.get("filename"))
        mime_type = str(att.get("mime_type") or "application/octet-stream").strip().lower()

        data_bytes = att.get("data_bytes")
        if isinstance(data_bytes, bytearray):
            data_bytes = bytes(data_bytes)
        elif not isinstance(data_bytes, bytes):
            raw_b64 = att.get("data_b64") or att.get("data_url") or ""
            data_bytes = b""
            if isinstance(raw_b64, str) and raw_b64.strip():
                try:
                    data_bytes, inferred = _decode_base64_payload(raw_b64, name)
                    mime_type = mime_type or inferred
                except ValueError:
                    data_bytes = b""

        if not data_bytes:
            continue
        if mime_type in ("text/plain", "text/csv"):
            decoded_text = data_bytes.decode("utf-8", errors="replace")[:MAX_TEXT_ATTACHMENT_CHARS]
            parts.append({"text": f"[Attached file: {name}]\n{decoded_text}"})
            continue
        try:
            from google.genai import types
            parts.append(types.Part.from_bytes(data=data_bytes, mime_type=mime_type))
        except Exception:
            b64_str = base64.b64encode(data_bytes).decode("ascii")
            parts.append({"inline_data": {"mime_type": mime_type, "data": b64_str}})

    effective_prompt = (prompt_text or "").strip() or "Analyze the attached file(s)."
    parts.append({"text": effective_prompt})
    return parts


def build_persisted_attachments_metadata(
    attachments: Sequence[dict[str, Any]] | None,
    created_at_iso: str | None = None,
) -> list[dict[str, Any]]:
    """
    Strips full-size binary payloads (`data_bytes`, `data_b64`) so only compact metadata
    and tiny thumbnails (`<= 24 KB`) are persisted inside encrypted SQLite columns.
    """
    if not attachments:
        return []
    timestamp = created_at_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    persisted: list[dict[str, Any]] = []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        mime_type = str(att.get("mime_type") or "application/octet-stream").strip().lower()
        raw_bytes = att.get("data_bytes")
        size_bytes = int(att.get("size_bytes") or (len(raw_bytes) if isinstance(raw_bytes, (bytes, bytearray)) else 0))
        persisted.append({
            "name": _sanitize_filename(att.get("name") or att.get("filename")),
            "mime_type": mime_type,
            "kind": str(att.get("kind") or ("image" if mime_type.startswith("image/") else "document")),
            "size_bytes": size_bytes,
            "thumb_data_url": _sanitize_thumb_data_url(att.get("thumb_data_url")),
            "created_at": str(att.get("created_at") or timestamp),
            "retention_days": int(att.get("retention_days") or ATTACHMENT_RETENTION_DAYS),
        })
    return persisted


def is_attachment_expired(
    created_at_str: str | None,
    retention_days: int = ATTACHMENT_RETENTION_DAYS,
    now_dt: datetime | None = None,
) -> bool:
    """Returns True if `created_at_str` is older than `retention_days` relative to `now_dt` (UTC)."""
    if not created_at_str or not str(created_at_str).strip():
        return False
    if retention_days <= 0:
        return True

    raw = str(created_at_str).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False

    parsed_utc = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    ref_now = now_dt or datetime.now(timezone.utc)
    ref_utc = ref_now.replace(tzinfo=timezone.utc) if ref_now.tzinfo is None else ref_now.astimezone(timezone.utc)
    return (ref_utc - parsed_utc) >= timedelta(days=retention_days)


def filter_active_attachments(
    raw_metadata: Any,
    message_created_at: str | None = None,
    retention_days: int = ATTACHMENT_RETENTION_DAYS,
    now_dt: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Parses stored attachment metadata (JSON string or list) and enforces the 30-day retention policy.
    Expired attachments have `thumb_data_url` wiped to `""` and `"expired": True`.
    """
    if not raw_metadata:
        return []
    items: Any = raw_metadata
    if isinstance(raw_metadata, str):
        try:
            items = json.loads(raw_metadata)
        except Exception:
            return []
    if not isinstance(items, list):
        return []

    filtered: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        created_at = str(item.get("created_at") or message_created_at or "").strip()
        item_retention = int(item.get("retention_days") or retention_days)
        expired = is_attachment_expired(created_at, retention_days=item_retention, now_dt=now_dt)
        mime_type = str(item.get("mime_type") or "application/octet-stream").strip().lower()
        filtered.append({
            "name": _sanitize_filename(item.get("name") or item.get("filename")),
            "mime_type": mime_type,
            "kind": str(item.get("kind") or ("image" if mime_type.startswith("image/") else "document")),
            "size_bytes": int(item.get("size_bytes") or 0),
            "thumb_data_url": "" if expired else _sanitize_thumb_data_url(item.get("thumb_data_url")),
            "created_at": created_at,
            "retention_days": item_retention,
            "expired": expired,
        })
    return filtered
