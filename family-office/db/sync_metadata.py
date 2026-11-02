"""
db/sync_metadata.py: Atomic per-provider sync metadata (`last_sync_metadata` in `family_encrypted_store`).

Shape: `{"timestamp": <latest sync of any provider>, "providers": {"monarch": {...}, "simplefin": {...}}}`.
Per-provider state lives only under `providers[...]`. Writes are one `BEGIN IMMEDIATE` read-modify-write, so
threads and separate processes syncing different providers never lose each other's entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Union

import security
from hvl_common.db import get_db_connection

SYNC_METADATA_KEY = "last_sync_metadata"
RUN_KEY = "run"  # providers[p]["run"]: the sync lifecycle record owned by account_sync.sync_lifecycle


def provider_entry(meta: Any, provider: str) -> Dict[str, Any]:
    """Returns one provider's entry from a loaded `last_sync_metadata` dict (legacy flat blobs included)."""
    if not isinstance(meta, dict):
        return {}
    entry = (meta.get("providers") or {}).get(provider)
    if isinstance(entry, dict):
        return entry
    if "providers" not in meta and meta.get("provider") == provider:
        return meta
    return {}


def load_provider_sync_entry(db_path: Union[str, Path], family_id: int, provider: str) -> Dict[str, Any]:
    """Loads and decrypts one provider's last sync entry (empty dict when never synced)."""
    return provider_entry(security.db_load_encrypted(Path(db_path), SYNC_METADATA_KEY, family_id=family_id), provider)


def _normalize(existing: Any) -> Dict[str, Any]:
    """Converts a legacy flat blob into the per-provider shape; drops lingering top-level provider state."""
    if not isinstance(existing, dict):
        return {"providers": {}}
    providers = dict(existing.get("providers") or {})
    legacy_provider = existing.get("provider")
    if legacy_provider and legacy_provider not in providers and "providers" not in existing:
        providers[str(legacy_provider)] = {k: v for k, v in existing.items() if k != "providers"}
    out: Dict[str, Any] = {"providers": providers}
    if existing.get("timestamp"):
        out["timestamp"] = existing["timestamp"]
    return out


def update_provider_sync_entry(
    db_path: Union[str, Path],
    family_id: int,
    provider: str,
    mutate: Callable[[Dict[str, Any]], Dict[str, Any]],
    *,
    notify: bool = True,
) -> Dict[str, Any]:
    """
    One `BEGIN IMMEDIATE` read-modify-write of `providers[provider]`: `mutate(previous_entry)` returns the new
    entry (it may raise to abort, which rolls back). Other providers' entries are never touched. Returns the
    stored metadata. `notify=False` skips the domain-version bump for bookkeeping that the UI does not render.
    """
    if not family_id:
        return {}
    path = Path(db_path)
    fam_key = security.get_family_key(path, family_id)
    with get_db_connection(path, timeout=30.0) as conn:
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT encrypted_payload FROM family_encrypted_store WHERE family_id = ? AND key = ?",
                (family_id, SYNC_METADATA_KEY),
            ).fetchone()
            meta = _normalize(security.decrypt_data(row[0], key=fam_key) if row and row[0] else None)
            meta["providers"][provider] = mutate(dict(meta["providers"].get(provider) or {}))
            entries = [e for e in meta["providers"].values() if isinstance(e, dict)]
            stamps = [str(e["timestamp"]) for e in entries if e.get("timestamp")]
            if stamps:
                meta["timestamp"] = max(stamps)
            conn.execute(
                """
                INSERT INTO family_encrypted_store (family_id, key, category, updated_at, encrypted_payload)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(family_id, key) DO UPDATE SET
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP,
                    encrypted_payload = excluded.encrypted_payload
                """,
                (family_id, SYNC_METADATA_KEY, f"{provider}_sync", security.encrypt_data(meta, key=fam_key)),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    if notify:
        from db import store as _store
        from forecast.cache import resolve_domains_for_encrypted_key

        domains = resolve_domains_for_encrypted_key(SYNC_METADATA_KEY, f"{provider}_sync")
        _store.notify_family_mutation(family_id, domains=domains, db_path=path)
    return meta


def merge_provider_sync_entry(
    db_path: Union[str, Path], family_id: int, provider: str, entry: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Atomically stores `entry` as `providers[provider]`, keeping other providers' entries, the provider's lifecycle
    `run` record, and any previous `last_upstream_refresh_ts` when `entry` carries none. Returns the stored metadata.
    """

    def _mutate(previous: Dict[str, Any]) -> Dict[str, Any]:
        stored = dict(entry)
        if stored.get("last_upstream_refresh_ts") is None and previous.get("last_upstream_refresh_ts"):
            stored["last_upstream_refresh_ts"] = previous["last_upstream_refresh_ts"]
        if RUN_KEY not in stored and previous.get(RUN_KEY):
            stored[RUN_KEY] = previous[RUN_KEY]
        return stored

    return update_provider_sync_entry(db_path, family_id, provider, _mutate)
