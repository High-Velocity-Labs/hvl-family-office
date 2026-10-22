"""
Multi-universe tenancy and dynamic database path routing for High Velocity Labs applications.

Standardizes physical per-tenant SQLite isolation across universe partitions
(e.g., 'public', 'beta', 'demo', 'sandbox', 'test').
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from hvl_common.db.sqlite import get_db_connection

VALID_UNIVERSES: tuple[str, ...] = ("public", "beta", "demo", "test")
KNOWN_UNIVERSES: tuple[str, ...] = ("public", "beta", "demo", "sandbox", "test")
DEFAULT_UNIVERSE: str = "public"


def resolve_universe(
    universe: Optional[str] = None,
    env_var: str = "APP_UNIVERSE",
    default: str = DEFAULT_UNIVERSE,
    valid_universes: Optional[Sequence[str]] = None,
) -> str:
    """
    Resolves and normalizes a universe partition identifier.

    Checks explicit `universe`, then `os.getenv(env_var)`, falling back to `default`.
    Normalizes by stripping whitespace and lowercasing. Validates against `valid_universes`
    (defaults to `VALID_UNIVERSES`).
    """
    allowed = valid_universes if valid_universes is not None else VALID_UNIVERSES
    raw = universe if universe is not None else os.getenv(env_var, default)
    val = (raw or default).strip().lower()
    if val in allowed:
        return val
    return default


def get_universe_dir(
    data_dir: Union[str, Path],
    universe: Optional[str] = None,
    valid_universes: Optional[Sequence[str]] = None,
) -> Path:
    """Returns the isolated directory for a universe partition: data_dir / universe."""
    u = resolve_universe(universe, valid_universes=valid_universes)
    return Path(data_dir) / u


def get_global_db_path(
    data_dir: Union[str, Path],
    universe: Optional[str] = None,
    valid_universes: Optional[Sequence[str]] = None,
) -> Path:
    """Returns the global auth/directory DB path inside the universe partition."""
    return get_universe_dir(data_dir, universe=universe, valid_universes=valid_universes) / "global.db"


def get_tenant_db_path(
    data_dir: Union[str, Path],
    tenant_id: int | str,
    tenant_dir_name: str = "households",
    universe: Optional[str] = None,
    valid_universes: Optional[Sequence[str]] = None,
) -> Path:
    """Returns the dedicated tenant SQLite DB path: data_dir / universe / tenant_dir_name / {tenant_id}.db."""
    tid = int(tenant_id)
    u_dir = get_universe_dir(data_dir, universe=universe, valid_universes=valid_universes)
    return u_dir / tenant_dir_name / f"{tid}.db"


def get_tenant_cache_db_path(
    data_dir: Union[str, Path],
    tenant_id: int | str,
    tenant_dir_name: str = "households",
    universe: Optional[str] = None,
    valid_universes: Optional[Sequence[str]] = None,
) -> Path:
    """Returns the dedicated tenant SQLite cache DB path: data_dir / universe / tenant_dir_name / {tenant_id}_cache.db."""
    tid = int(tenant_id)
    u_dir = get_universe_dir(data_dir, universe=universe, valid_universes=valid_universes)
    return u_dir / tenant_dir_name / f"{tid}_cache.db"


def resolve_tenant_db_path(
    db_path: Optional[Union[str, Path]] = None,
    tenant_id: Optional[int] = None,
    data_dir: Union[str, Path] = "data",
    universe: Optional[str] = None,
    tenant_dir_name: str = "households",
    valid_universes: Optional[Sequence[str]] = None,
) -> Path:
    """
    Resolves the active SQLite database path for the current universe and tenant context.

    - Preserves explicit mock / non-standard test file paths (e.g. tmp_path / 'conv_privacy.db')
      where path name does not match conventional global/tenant names.
    - If tenant_id > 0, routes to data_dir / universe / tenant_dir_name / {tenant_id}.db.
    - If tenant_id == 0 or None, routes to data_dir / universe / global.db.
    """
    allowed = valid_universes if valid_universes is not None else KNOWN_UNIVERSES
    base_dir = Path(data_dir)
    target_uni = resolve_universe(universe, valid_universes=allowed)
    tid = int(tenant_id or 0)

    # If db_path is provided and not a proxy object
    if db_path is not None and not hasattr(db_path, "_path"):
        p = Path(db_path)
        p_name = p.name
        parent_name = p.parent.name

        # Conventional root DB filenames without a universe directory
        if p_name in ("assistant.db", "global.db", "family_office.db") and parent_name not in allowed:
            if tid > 0:
                return get_tenant_db_path(base_dir, tid, tenant_dir_name=tenant_dir_name, universe=target_uni, valid_universes=allowed)
            return get_global_db_path(base_dir, universe=target_uni, valid_universes=allowed)

        # Legacy flat filenames (e.g. family_office_sandbox.db, global_beta.db)
        if (p_name.startswith("family_office") or p_name.startswith("global")) and p_name.endswith(".db") and parent_name not in allowed:
            if "_sandbox" in p_name:
                u = "sandbox"
            elif "_demo" in p_name:
                u = "demo"
            elif "_beta" in p_name:
                u = "demo" if tenant_dir_name == "families" else "beta"
            elif "_test" in p_name:
                u = "test"
            else:
                u = "public"
            if tid > 0:
                return get_tenant_db_path(base_dir, tid, tenant_dir_name=tenant_dir_name, universe=u, valid_universes=allowed)
            return get_global_db_path(base_dir, universe=u, valid_universes=allowed)

        # Path inside a universe folder: .../{universe}/...
        if parent_name in allowed:
            u_dir = p.parent
            target_tid = tid if tid > 0 else (int(p.stem) if p.stem.isdigit() and tenant_id is None else 0)
            if target_tid > 0:
                return u_dir / tenant_dir_name / f"{target_tid}.db"
            return u_dir / "global.db"

        # Path inside tenant folder: .../{universe}/{tenant_dir_name}/...
        if parent_name == tenant_dir_name and p.parent.parent.name in allowed:
            u_dir = p.parent.parent
            target_tid = tid if tid > 0 else (int(p.stem) if p.stem.isdigit() and tenant_id is None else 0)
            if target_tid > 0:
                return p.parent / f"{target_tid}.db"
            if tenant_id == 0:
                return u_dir / "global.db"
            if p.stem.isdigit():
                return p
            return u_dir / "global.db"

        # Non-standard explicit mock/test path (e.g. /tmp/conv_privacy.db or memory)
        return p

    # Default path resolution
    if tid > 0:
        return get_tenant_db_path(base_dir, tid, tenant_dir_name=tenant_dir_name, universe=target_uni, valid_universes=allowed)
    return get_global_db_path(base_dir, universe=target_uni, valid_universes=allowed)


def sync_household_to_tenant_db(
    tenant_db_path: Path | str,
    household_id: int,
    name: str,
) -> bool:
    """
    Synchronizes a household record from global.db into a dedicated tenant DB if it exists.
    Returns True on success, False otherwise.
    """
    try:
        target = Path(tenant_db_path)
        if not target.exists():
            return False
        with get_db_connection(target) as conn:
            conn.execute(
                "INSERT INTO households (id, name) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
                (int(household_id), str(name)),
            )
        return True
    except Exception:
        return False


def sync_member_to_tenant_db(
    tenant_db_path: Path | str,
    household_id: int,
    member_data: dict[str, Any],
) -> bool:
    """
    Synchronizes a household member record from global.db into a dedicated tenant DB if it exists.
    Returns True on success, False otherwise.
    """
    try:
        target = Path(tenant_db_path)
        if not target.exists():
            return False
        with get_db_connection(target) as conn:
            conn.execute(
                "INSERT INTO household_members (household_id, email, display_name, role, preferred_model_tier, google_vault_synced) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(email) DO UPDATE SET "
                "household_id = excluded.household_id, "
                "display_name = excluded.display_name, "
                "role = excluded.role, "
                "preferred_model_tier = excluded.preferred_model_tier, "
                "google_vault_synced = excluded.google_vault_synced",
                (
                    int(household_id),
                    str(member_data["email"]),
                    str(member_data["display_name"]),
                    str(member_data.get("role", "adult")),
                    str(member_data.get("preferred_model_tier", "lite")),
                    int(member_data.get("google_vault_synced") or 0),
                ),
            )
        return True
    except Exception:
        return False


__all__ = [
    "VALID_UNIVERSES",
    "KNOWN_UNIVERSES",
    "DEFAULT_UNIVERSE",
    "resolve_universe",
    "get_universe_dir",
    "get_global_db_path",
    "get_tenant_db_path",
    "get_tenant_cache_db_path",
    "resolve_tenant_db_path",
    "sync_household_to_tenant_db",
    "sync_member_to_tenant_db",
]
