"""
Token Minting, SHA-256 Hashing & Household/Member Token Store (`hvl_common.mcp.tokens`).
Supports individual member keys within households, automatic table creation,
and constant-time hash verification.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from cryptography.fernet import Fernet

from hvl_common.db import get_db_connection

MCP_TOKEN_PREFIX = "hvl_mcp_"
_SANDBOX_UNIVERSES = {"sandbox", "demo", "beta"}


def _derive_token_wrapping_key(
    raw_token: str, server_secret: Optional[Union[bytes, str]] = None
) -> bytes:
    """
    Derives a 32-byte URL-safe base64 Fernet key from (raw_token, server_secret).
    Because raw_token is never stored on disk (only its SHA-256 hash), any secret_payload
    wrapped with this key cannot be decrypted at rest without the caller's raw_token.
    """
    sec_bytes = (
        server_secret.encode("utf-8")
        if isinstance(server_secret, str)
        else (server_secret or b"")
    )
    digest = hashlib.sha256(raw_token.strip().encode("utf-8") + b":mcp-wrap:" + sec_bytes).digest()
    return base64.urlsafe_b64encode(digest)


def _wrap_secret_payload(
    raw_token: str,
    secret_payload: Optional[Union[bytes, str]],
    server_secret: Optional[Union[bytes, str]] = None,
) -> str:
    if not secret_payload:
        return ""
    payload_bytes = (
        secret_payload.encode("utf-8") if isinstance(secret_payload, str) else bytes(secret_payload)
    )
    f = Fernet(_derive_token_wrapping_key(raw_token, server_secret))
    return f.encrypt(payload_bytes).decode("utf-8")


def _unwrap_secret_payload(
    raw_token: str,
    wrapped_secret: str,
    server_secret: Optional[Union[bytes, str]] = None,
) -> Optional[bytes]:
    if not wrapped_secret:
        return None
    try:
        f = Fernet(_derive_token_wrapping_key(raw_token, server_secret))
        return f.decrypt(wrapped_secret.encode("utf-8"))
    except Exception:
        return None


def generate_raw_token() -> Tuple[str, str, str]:
    """
    Generates a secure, cryptographically random raw token, its SHA-256 digest,
    and a safe-for-display prefix (e.g. 'hvl_mcp_a1b2c3d...').
    """
    raw_token = f"{MCP_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    token_hash = hash_mcp_token(raw_token)
    token_prefix = f"{raw_token[:14]}..."
    return raw_token, token_hash, token_prefix


def hash_mcp_token(raw_token: str) -> str:
    """
    Computes standard SHA-256 hex digest of stripped raw token string.
    """
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def ensure_mcp_tokens_table(db_path: Union[str, Path]) -> None:
    """
    Ensures the `mcp_tokens` table and its compound index exist.
    """
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_tokens (
                token_id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                user_email TEXT NOT NULL DEFAULT '',
                label TEXT NOT NULL DEFAULT 'Personal Assistant',
                token_hash TEXT NOT NULL UNIQUE,
                token_prefix TEXT NOT NULL,
                scopes TEXT NOT NULL DEFAULT 'read,simulate',
                wrapped_secret TEXT NOT NULL DEFAULT '',
                is_enabled INTEGER NOT NULL DEFAULT 1,
                call_count INTEGER NOT NULL DEFAULT 0,
                last_used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        try:
            conn.execute(
                "ALTER TABLE mcp_tokens ADD COLUMN wrapped_secret TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mcp_tokens_owner ON mcp_tokens(owner_id, user_email)"
        )
        conn.commit()


def mint_mcp_token(
    db_path: Union[str, Path],
    *,
    owner_id: int,
    user_email: str = "",
    label: str = "Personal Assistant",
    scopes: Sequence[str] = ("read", "simulate"),
    universe: str = "public",
    secret_payload: Optional[Union[bytes, str]] = None,
    server_secret: Optional[Union[bytes, str]] = None,
) -> Dict[str, Any]:
    """
    Mints a new MCP API token for an owner / household member.
    Rejects sandbox / demo workspaces and owner_id <= 0.
    Replaces any existing token for the exact same (owner_id, user_email) pair.
    """
    clean_universe = (universe or "").strip().lower()
    if clean_universe in _SANDBOX_UNIVERSES or owner_id <= 0:
        raise PermissionError("MCP tokens cannot be minted for sandbox or demo workspaces.")

    ensure_mcp_tokens_table(db_path)
    raw_token, token_hash, token_prefix = generate_raw_token()
    clean_email = (user_email or "").strip()
    norm_email = clean_email.lower()
    clean_label = (label or "Personal Assistant").strip()
    scopes_str = ",".join(s.strip() for s in scopes if s.strip())
    wrapped_secret = _wrap_secret_payload(raw_token, secret_payload, server_secret)

    with get_db_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM mcp_tokens WHERE owner_id = ? AND LOWER(user_email) = ?",
            (owner_id, norm_email),
        )
        cur = conn.execute(
            """
            INSERT INTO mcp_tokens (
                owner_id, user_email, label, token_hash, token_prefix, scopes, wrapped_secret, is_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (owner_id, clean_email, clean_label, token_hash, token_prefix, scopes_str, wrapped_secret),
        )
        conn.commit()
        token_id = cur.lastrowid

    return {
        "token_id": token_id,
        "raw_token": raw_token,
        "token_prefix": token_prefix,
        "owner_id": owner_id,
        "user_email": clean_email,
        "label": clean_label,
        "scopes": list(scopes),
        "is_enabled": True,
    }


def verify_mcp_token(
    db_path: Union[str, Path],
    raw_token: str,
    *,
    server_secret: Optional[Union[bytes, str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Verifies a raw MCP token against the persistent database.
    Returns token metadata dict if valid and enabled; returns None otherwise.
    """
    if not isinstance(raw_token, str):
        return None
    clean_token = raw_token.strip()
    if not clean_token.startswith(MCP_TOKEN_PREFIX):
        return None

    token_hash = hash_mcp_token(clean_token)
    ensure_mcp_tokens_table(db_path)

    with get_db_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT token_id, owner_id, user_email, label, token_prefix, scopes,
                   wrapped_secret, is_enabled, call_count, last_used_at
            FROM mcp_tokens
            WHERE token_hash = ? AND is_enabled = 1
            """,
            (token_hash,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        raw_scopes = row["scopes"] or ""
        scopes_list = [s.strip() for s in raw_scopes.split(",") if s.strip()]
        unwrapped = _unwrap_secret_payload(
            clean_token, str(row["wrapped_secret"] or ""), server_secret
        )
        return {
            "token_id": int(row["token_id"]),
            "owner_id": int(row["owner_id"]),
            "user_email": str(row["user_email"]),
            "label": str(row["label"]),
            "token_prefix": str(row["token_prefix"]),
            "scopes": scopes_list,
            "secret_payload": unwrapped,
            "is_enabled": True,
            "call_count": int(row["call_count"] or 0),
            "last_used_at": row["last_used_at"],
        }


def record_mcp_token_usage(db_path: Union[str, Path], token_id: int) -> None:
    """
    Increments call_count and updates last_used_at timestamp.
    """
    ensure_mcp_tokens_table(db_path)
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE mcp_tokens
            SET call_count = call_count + 1, last_used_at = CURRENT_TIMESTAMP
            WHERE token_id = ?
            """,
            (token_id,),
        )
        conn.commit()


def list_mcp_tokens(db_path: Union[str, Path], owner_id: int) -> List[Dict[str, Any]]:
    """
    Lists all tokens for a given owner_id ordered by created_at DESC.
    Never exposes raw token hashes.
    """
    ensure_mcp_tokens_table(db_path)
    with get_db_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT token_id, owner_id, user_email, label, token_prefix, scopes,
                   is_enabled, call_count, last_used_at, created_at
            FROM mcp_tokens
            WHERE owner_id = ?
            ORDER BY created_at DESC
            """,
            (owner_id,),
        )
        rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            raw_scopes = row["scopes"] or ""
            results.append({
                "token_id": int(row["token_id"]),
                "owner_id": int(row["owner_id"]),
                "user_email": str(row["user_email"]),
                "label": str(row["label"]),
                "token_prefix": str(row["token_prefix"]),
                "scopes": [s.strip() for s in raw_scopes.split(",") if s.strip()],
                "is_enabled": bool(row["is_enabled"]),
                "call_count": int(row["call_count"] or 0),
                "last_used_at": row["last_used_at"],
                "created_at": row["created_at"],
            })
        return results


def set_mcp_owner_enabled(db_path: Union[str, Path], owner_id: int, enabled: bool) -> int:
    """
    Enables or disables all tokens belonging to owner_id. Returns updated row count.
    """
    ensure_mcp_tokens_table(db_path)
    with get_db_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE mcp_tokens SET is_enabled = ? WHERE owner_id = ?",
            (1 if enabled else 0, owner_id),
        )
        conn.commit()
        return cur.rowcount


def revoke_mcp_token(
    db_path: Union[str, Path],
    owner_id: int,
    *,
    token_id: Optional[int] = None,
    user_email: Optional[str] = None,
) -> int:
    """
    Deletes matching token(s) for owner_id by token_id, user_email, or all if neither specified.
    Returns deleted row count.
    """
    ensure_mcp_tokens_table(db_path)
    with get_db_connection(db_path) as conn:
        if token_id is not None:
            cur = conn.execute(
                "DELETE FROM mcp_tokens WHERE owner_id = ? AND token_id = ?",
                (owner_id, token_id),
            )
        elif user_email is not None:
            cur = conn.execute(
                "DELETE FROM mcp_tokens WHERE owner_id = ? AND LOWER(user_email) = ?",
                (owner_id, user_email.strip().lower()),
            )
        else:
            cur = conn.execute(
                "DELETE FROM mcp_tokens WHERE owner_id = ?",
                (owner_id,),
            )
        conn.commit()
        return cur.rowcount
