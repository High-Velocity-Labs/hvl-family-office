"""
Pytest Global Configuration for HVL Family Office.
Enforces the 'test' universe sandbox for all test suites:
- Automatically initializes data/test/family_office.db from baseline data at session start.
- Sets APP_UNIVERSE='test' so all engine modules, database proxies, and route handlers
  operate strictly against the test database.
- Guarantees data/public/family_office.db (the public production database) is NEVER modified by tests.
"""

from __future__ import annotations
import os
import shutil
import pytest
from pathlib import Path
import config

SOURCE_DATA_DIR = config.DATA_DIR
DATA_DIR = config.get_data_dir()
PROD_DB = SOURCE_DATA_DIR / "public" / "family_office.db"
TEST_DB = DATA_DIR / "test" / "family_office.db"


@pytest.fixture(scope="session", autouse=True)
def setup_test_universe():
    """Session-level fixture initializing the test universe database sandbox."""
    import sqlite3

    os.environ["APP_UNIVERSE"] = "test"
    config.APP_UNIVERSE = "test"
    active_data_dir = config.get_data_dir()
    test_dir = active_data_dir / "test"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_db = test_dir / "family_office.db"

    # When running in an isolated worker directory (FAMILY_OFFICE_DATA_DIR), copy .mm/.secret.key, .env and demo universe
    if active_data_dir.resolve() != SOURCE_DATA_DIR.resolve():
        mm_dst = active_data_dir / ".mm" / ".secret.key"
        mm_dst.parent.mkdir(parents=True, exist_ok=True)
        src_mm_key = config.BASE_DIR / ".mm" / ".secret.key"
        if not mm_dst.exists() and src_mm_key.exists():
            shutil.copy2(src_mm_key, mm_dst)
            import security_crypto
            security_crypto._ROOT_KEY_CACHE = None
        for key_file in (".secret.key", ".env"):
            src_key = config.BASE_DIR / key_file
            dst_key = active_data_dir / key_file
            if src_key.exists() and not dst_key.exists():
                shutil.copy2(src_key, dst_key)
        src_demo = SOURCE_DATA_DIR / "demo"
        dst_demo = active_data_dir / "demo"
        if src_demo.exists() and not dst_demo.exists():
            shutil.copytree(src_demo, dst_demo, dirs_exist_ok=True)

    for base_name in ("family_office.db", "family_office_cache.db", "global.db"):
        for suffix in ("", "-wal", "-shm"):
            p = test_dir / f"{base_name}{suffix}"
            if p.exists():
                p.unlink()
    for base_name in ("family_office_test.db", "family_office_test_cache.db", "global_test.db"):
        for suffix in ("", "-wal", "-shm"):
            p = active_data_dir / f"{base_name}{suffix}"
            if p.exists():
                p.unlink()
    families_test_dir = test_dir / "families"
    families_test_dir.mkdir(parents=True, exist_ok=True)
    for p in families_test_dir.glob("*"):
        if p.is_file():
            p.unlink()
    _unlock_fek_sql = """
        UPDATE families
        SET encryption_key_enc = (
            SELECT pending_fek_enc FROM users
            WHERE users.family_id = families.family_id
              AND pending_fek_enc IS NOT NULL AND pending_fek_enc != ''
            LIMIT 1
        ),
        support_access_enabled = 1
        WHERE (encryption_key_enc IS NULL OR encryption_key_enc = '')
          AND EXISTS (
            SELECT 1 FROM users
            WHERE users.family_id = families.family_id
              AND pending_fek_enc IS NOT NULL AND pending_fek_enc != ''
          )
    """
    prod_global_db = SOURCE_DATA_DIR / "public" / "global.db"
    if not prod_global_db.exists() and (SOURCE_DATA_DIR / "global.db").exists():
        prod_global_db = SOURCE_DATA_DIR / "global.db"
    test_global_db = test_dir / "global.db"
    if prod_global_db.exists():
        test_global_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(prod_global_db)) as src_conn, sqlite3.connect(str(test_global_db)) as dst_conn:
            src_conn.backup(dst_conn)
        with sqlite3.connect(str(test_global_db)) as dst_conn:
            try:
                dst_conn.execute(_unlock_fek_sql)
                dst_conn.execute("UPDATE families SET support_access_enabled = 1")
                dst_conn.commit()
            except sqlite3.OperationalError:
                pass

    prod_families_dir = SOURCE_DATA_DIR / "public" / "families"
    if not prod_families_dir.exists() and (SOURCE_DATA_DIR / "families").exists():
        prod_families_dir = SOURCE_DATA_DIR / "families"
    if prod_families_dir.exists():
        families_test_dir.mkdir(parents=True, exist_ok=True)
        for src_fam_db in prod_families_dir.glob("*.db"):
            if src_fam_db.name.endswith("_cache.db"):
                continue
            dst_fam_db = families_test_dir / src_fam_db.name
            with sqlite3.connect(str(src_fam_db)) as src_conn, sqlite3.connect(str(dst_fam_db)) as dst_conn:
                src_conn.backup(dst_conn)
            with sqlite3.connect(str(dst_fam_db)) as dst_conn:
                try:
                    dst_conn.execute(_unlock_fek_sql)
                    dst_conn.commit()
                except Exception:
                    pass
    # If family 1 in test universe is unseeded (e.g. clean dev checkout without production DB), seed demo personas
    test_fam_1 = families_test_dir / "1.db"
    has_seeded_data = False
    if test_fam_1.exists():
        with sqlite3.connect(str(test_fam_1)) as c:
            try:
                has_seeded_data = bool(c.execute("SELECT count(*) FROM compensation").fetchone()[0] > 0)
            except Exception:
                has_seeded_data = False
    if not has_seeded_data:
        from scripts.seed_demo_families import seed_all_demo_families
        seed_all_demo_families(db_path=test_db, verbose=False)

    yield


@pytest.fixture(autouse=True)
def isolate_test_cache_and_state():
    """Clears forecast_cache (L1/L2), security FEK caches, and transient in-memory state between tests."""
    import forecast_cache
    import security

    def _clear_transient_state() -> None:
        security._clear_security_caches()
        forecast_cache.clear_all_caches()
        active_data_dir = config.get_data_dir()
        for fam_cache_dir in (
            active_data_dir / "test" / "families",
            active_data_dir / "demo" / "families",
            active_data_dir / "families_test",
            active_data_dir / "families_beta",
        ):
            if fam_cache_dir.exists():
                for cache_db in fam_cache_dir.glob("*_cache.db"):
                    try:
                        state_db = fam_cache_dir / f"{cache_db.stem.removesuffix('_cache')}.db"
                        forecast_cache.CACHE.clear(db_path=state_db, cache_db_path=cache_db)
                    except Exception:
                        pass

    _clear_transient_state()
    yield
    _clear_transient_state()

