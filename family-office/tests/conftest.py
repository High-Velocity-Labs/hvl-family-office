"""
Pytest Global Configuration for HVL Family Office.
Enforces the 'test' universe sandbox for all test suites:
- Builds the 'test' universe at session start from tracked sources only: the seven demo personas plus the deterministic
  test household of tests/household_factory.py. Nothing is copied from data/public, so a clean clone passes.
- Sets APP_UNIVERSE='test' so all engine modules, database proxies, and route handlers
  operate strictly against the test database.
- Runs the whole session against an empty temporary data dir (FAMILY_OFFICE_DATA_DIR),
  so no test can read or modify the checkout's data/, and deletes that dir when the process exits. A session that
  crashed or was killed leaves its dir behind; the next session deletes it.
"""

from __future__ import annotations
import atexit
import os
import shutil
import pytest
from pathlib import Path



_PYTEST_DATA_DIR_ENV = "FO_PYTEST_SESSION_DATA_DIR"  # marks a data dir this conftest made, so xdist workers make their own
_DATA_DIR_PREFIX = "fo_pytest_data_"
_OWNER_PID_FILE = ".owner_pid"  # the pid of the session that made the dir; a later session deletes it once that pid is gone
_UNOWNED_DIR_MAX_AGE_SECONDS = 24 * 3600


def _isolate_data_dir() -> None:
    """Points the whole session at an empty throwaway data dir; the universes are built from fixtures by `setup_test_universe`.

    A caller that already set FAMILY_OFFICE_DATA_DIR (an isolated worker) keeps its own directory. A pytest-xdist worker
    inherits the directory its controller made for itself and makes its own, so workers never share databases.
    """
    import tempfile

    inherited = os.getenv("FAMILY_OFFICE_DATA_DIR", "").strip()
    made_by_pytest = inherited and inherited == os.getenv(_PYTEST_DATA_DIR_ENV, "")
    if inherited and not (made_by_pytest and os.getenv("PYTEST_XDIST_WORKER")):
        return
    _sweep_dead_session_data_dirs(Path(tempfile.gettempdir()))
    target = Path(tempfile.mkdtemp(prefix=_DATA_DIR_PREFIX))
    (target / _OWNER_PID_FILE).write_text(str(os.getpid()))
    # Each session leaves ~180 MB of databases and key copies here; 1,942 leftovers filled the disk (2026-10-29).
    atexit.register(shutil.rmtree, target, ignore_errors=True)
    os.environ["FAMILY_OFFICE_DATA_DIR"] = str(target)
    os.environ[_PYTEST_DATA_DIR_ENV] = str(target)
    # The rate limiter's default cache is `../common/data/ratelimit_cache`: a test run must not write beside the checkout
    # (the verify sandbox lets a run write only its own app directory).
    os.environ["HVL_RATELIMIT_CACHE_DIR"] = str(target / "ratelimit_cache")


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # alive, owned by another user
        return True
    return True


def _sweep_dead_session_data_dirs(temp_root: Path) -> None:
    """Deletes data dirs a crashed or killed session left behind, so the next run cleans up what atexit could not.

    A dir whose owner process is gone is removed. A dir without an owner file predates it (or its session died before
    writing one) and is removed once it is a day old, so a session that just made its dir is never touched.
    """
    import time

    for leftover in temp_root.glob(f"{_DATA_DIR_PREFIX}*"):
        owner_file = leftover / _OWNER_PID_FILE
        if owner_file.is_file():
            owner_text = owner_file.read_text().strip()
            if owner_text.isdigit() and _process_alive(int(owner_text)):
                continue
        elif time.time() - leftover.stat().st_mtime < _UNOWNED_DIR_MAX_AGE_SECONDS:
            continue
        shutil.rmtree(leftover, ignore_errors=True)


_isolate_data_dir()
import hvl_common.security  # noqa: F401
import config

SOURCE_DATA_DIR = config.DATA_DIR
DATA_DIR = config.get_data_dir()
TEST_DB = DATA_DIR / "test" / "global.db"


@pytest.fixture(scope="session", autouse=True)
def setup_test_universe():
    """Session-level fixture initializing the test universe database sandbox."""
    os.environ["APP_UNIVERSE"] = "test"
    config.APP_UNIVERSE = "test"
    existing_admins = [e.strip() for e in os.environ.get("ADMIN_EMAIL", "").split(",") if e.strip()]
    if "admin@example.com" not in existing_admins:
        existing_admins.append("admin@example.com")
    os.environ["ADMIN_EMAIL"] = ",".join(existing_admins)
    active_data_dir = config.get_data_dir()
    test_dir = active_data_dir / "test"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_db = test_dir / "global.db"

    # The isolated worker directory needs the root key and .env; the demo universe is seeded below, never copied.
    if active_data_dir.resolve() != SOURCE_DATA_DIR.resolve():
        mm_dst = active_data_dir / ".mm" / ".secret.key"
        mm_dst.parent.mkdir(parents=True, exist_ok=True)
        src_mm_key = config.BASE_DIR / ".mm" / ".secret.key"
        if not mm_dst.exists() and src_mm_key.exists():
            shutil.copy2(src_mm_key, mm_dst)
            from security import crypto as security_crypto
            security_crypto._ROOT_KEY_CACHE = None
        for key_file in (".secret.key", ".env"):
            src_key = config.BASE_DIR / key_file
            dst_key = active_data_dir / key_file
            if src_key.exists() and not dst_key.exists():
                shutil.copy2(src_key, dst_key)

    for base_name in ("family_office.db", "family_office_cache.db", "global.db", "global_cache.db"):
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

    from scripts.seed_demo_families import seed_all_demo_families
    from household_factory import build_household

    seed_all_demo_families(db_path=test_db, verbose=False)
    build_household(test_db)

    # The demo universe is seeded before any test runs, so a request that touches the demo DB first cannot leave a
    # placeholder family row that the demo seeder then refuses to overwrite.
    demo_global_db = config.get_global_db_path("demo")
    if not demo_global_db.exists():
        demo_global_db.parent.mkdir(parents=True, exist_ok=True)
        seed_all_demo_families(db_path=demo_global_db, verbose=False)

    yield


@pytest.fixture
def household_context():
    """
    Factory binding a trusted household context, exactly as `submit_job` and the MCP gateway do,
    for tests that call advisor tools directly (tools never take the household from their arguments).
    """
    from contextlib import contextmanager
    from routes.context import get_current_universe, reset_background_context, set_background_context

    @contextmanager
    def _bind(family_id: int = 1, can_mutate: bool = True):
        tokens = set_background_context(family_id, get_current_universe(), can_mutate=can_mutate)
        try:
            yield
        finally:
            reset_background_context(tokens)

    return _bind


@pytest.fixture
def household_1(household_context):
    """Binds household 1 (the seeded Jones demo persona in the test universe) with write permission for a test."""
    with household_context(1):
        yield


@pytest.fixture
def public_household():
    """Builds the deterministic test household in the 'public' universe (a production-style tenant) once per worker."""
    from household_factory import PUBLIC_HOUSEHOLD_FAMILY_ID, build_household

    public_db = config.get_global_db_path("public")
    family_db = public_db.parent / "families" / f"{PUBLIC_HOUSEHOLD_FAMILY_ID}.db"
    if not family_db.exists():
        public_db.parent.mkdir(parents=True, exist_ok=True)
        build_household(public_db, family_id=PUBLIC_HOUSEHOLD_FAMILY_ID)
    return PUBLIC_HOUSEHOLD_FAMILY_ID


@pytest.fixture
def test_household(household_context):
    """Binds the deterministic test household of `household_factory` with write permission for a test."""
    from household_factory import HOUSEHOLD_FAMILY_ID

    with household_context(HOUSEHOLD_FAMILY_ID):
        yield HOUSEHOLD_FAMILY_ID


@pytest.fixture(autouse=True)
def _isolate_gemini_api_key(monkeypatch):
    """Prevents live Gemini API calls (the `.env` key) during tests unless a test sets its own key and mocks the client."""
    monkeypatch.setenv("GEMINI_API_KEY", "")


@pytest.fixture(autouse=True)
def isolate_test_cache_and_state():
    """Clears forecast_cache (L1/L2), security FEK caches, and transient in-memory state between tests."""
    from forecast import cache as forecast_cache
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



@pytest.fixture
def demo_jones_universe():
    """Runs the test inside the seeded demo universe, where family 1 is the fictional Jones persona."""
    from flask import session
    from wsgi import app as flask_app
    from scripts.seed_demo_families import seed_all_demo_families

    seed_all_demo_families(db_path=config.get_global_db_path("demo"), verbose=False)
    with flask_app.test_request_context():
        session["universe"] = "demo"
        session["is_demo"] = True
        session["family_id"] = 1
        yield
