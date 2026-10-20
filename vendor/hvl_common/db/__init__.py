"""
Database abstraction package for High Velocity Labs applications.
Standardizes production SQLite WAL connection pooling via SQLAlchemy 2.0 `QueuePool`,
online atomic backups, schema migration management, two-tier encrypted caching
(`cachetools` + `diskcache`), and multi-worker background jobs.
"""

from hvl_common.db.cache import SQLiteFileDiskCache, TwoTierCache
from hvl_common.db.jobs import SQLiteJobPool
from hvl_common.db.l1_lru import L1LRUMixin
from hvl_common.db.l2_disk import L2DiskMixin
from hvl_common.db.sqlite import (
    backup_sqlite_db,
    close_all_pools,
    get_db_connection,
    get_engine,
    run_migrations,
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
]
