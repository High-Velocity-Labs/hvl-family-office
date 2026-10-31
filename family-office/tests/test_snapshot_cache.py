"""The balance-sheet snapshot is cached against the data it is built from (forecast/snapshot_cache.py): a plan save
keeps it, a write to its data or a new day rebuilds it, and callers get private copies."""

from __future__ import annotations

from datetime import date

import pytest

from account_sync import snapshot as snapshot_module
from forecast import cache as forecast_cache
from forecast import snapshot_cache

FID = 1


@pytest.fixture
def builds(monkeypatch):
    """Counts snapshot builds (cache misses) by counting the account loads only a build does."""
    import db

    count = {"n": 0}
    real = db.store.get_accounts

    def counted(*args, **kwargs):
        count["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(db.store, "get_accounts", counted)
    snapshot_cache.clear()
    yield count
    snapshot_cache.clear()


def _snapshot():
    return snapshot_module.get_financial_snapshot(family_id=FID)


def test_a_plan_save_keeps_the_snapshot(builds):
    first = _snapshot()
    built = builds["n"]
    assert built >= 1
    forecast_cache.invalidate_family_cache(FID, domains=["scenarios"])
    assert _snapshot() == first
    assert builds["n"] == built


def test_a_write_to_its_data_rebuilds_it(builds):
    _snapshot()
    built = builds["n"]
    forecast_cache.invalidate_family_cache(FID, domains=["accounts"])
    _snapshot()
    assert builds["n"] > built


def test_a_new_day_rebuilds_it(builds, monkeypatch):
    _snapshot()
    built = builds["n"]

    class Tomorrow(date):
        @classmethod
        def today(cls):
            return date.fromordinal(date.today().toordinal() + 1)

    monkeypatch.setattr(snapshot_cache, "date", Tomorrow)
    _snapshot()
    assert builds["n"] > built


def test_callers_get_private_copies(builds):
    first = _snapshot()
    first["accounts_count"] = -1
    assert _snapshot()["accounts_count"] != -1


def test_a_write_during_the_build_does_not_cache_the_older_snapshot_as_current(builds, monkeypatch):
    import db

    real = db.store.get_accounts
    state = {"bumped": False}

    def accounts_then_a_concurrent_write(*args, **kwargs):
        rows = real(*args, **kwargs)
        if not state["bumped"]:
            state["bumped"] = True
            forecast_cache.invalidate_family_cache(FID, domains=["accounts"])  # lands mid-build
        return rows

    monkeypatch.setattr(db.store, "get_accounts", accounts_then_a_concurrent_write)
    _snapshot()
    built = builds["n"]
    monkeypatch.setattr(db.store, "get_accounts", real)
    _snapshot()
    assert state["bumped"]
    assert builds["n"] > built, "the snapshot built before the write is not served after it"
