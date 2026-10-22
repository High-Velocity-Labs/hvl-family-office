"""
Database abstraction package for High Velocity Labs applications.
Standardizes production SQLite WAL connection pooling via SQLAlchemy 2.0 `QueuePool`,
declarative FEK-encrypted `TypeDecorator` columns, scoped ORM sessions with `after_commit`
domain invalidation hooks, online atomic backups, schema migration management, two-tier
encrypted caching (`cachetools` + `diskcache`), and multi-worker background jobs.
"""

from hvl_common.db.cache import SQLiteFileDiskCache, TwoTierCache
from hvl_common.db.domain_versions import (
    DomainVersionTracker,
    delete_all_json_domain_versions,
    ensure_json_domain_versions_schema,
    load_json_domain_versions_row,
    orm_bump_domains,
    orm_get_domain_versions,
    save_json_domain_versions_row,
)
from hvl_common.db.jobs import SQLiteJobPool
from hvl_common.db.l1_lru import L1LRUMixin
from hvl_common.db.l2_disk import L2DiskMixin
from hvl_common.db.orm import orm_session_scope
from hvl_common.db.sqlite import (
    backup_sqlite_db,
    close_all_pools,
    get_db_connection,
    get_engine,
    run_migrations,
)
from hvl_common.db.tenancy import (
    DEFAULT_UNIVERSE,
    KNOWN_UNIVERSES,
    VALID_UNIVERSES,
    get_global_db_path,
    get_tenant_cache_db_path,
    get_tenant_db_path,
    get_universe_dir,
    resolve_tenant_db_path,
    resolve_universe,
    sync_household_to_tenant_db,
    sync_member_to_tenant_db,
)
from hvl_common.db.types import (
    EncryptedFloat,
    EncryptedJSON,
    EncryptedString,
    encryption_context,
    get_active_family_key,
    register_default_key_resolver,
)

__all__ = [
    "get_engine",
    "get_db_connection",
    "close_all_pools",
    "backup_sqlite_db",
    "run_migrations",
    "TwoTierCache",
    "SQLiteFileDiskCache",
    "L1LRUMixin",
    "L2DiskMixin",
    "SQLiteJobPool",
    "EncryptedString",
    "EncryptedFloat",
    "EncryptedJSON",
    "encryption_context",
    "get_active_family_key",
    "register_default_key_resolver",
    "orm_session_scope",
    "orm_get_domain_versions",
    "orm_bump_domains",
    "DomainVersionTracker",
    "ensure_json_domain_versions_schema",
    "load_json_domain_versions_row",
    "save_json_domain_versions_row",
    "delete_all_json_domain_versions",
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
