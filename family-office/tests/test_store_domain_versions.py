"""The entity store (db/store.py) keys each entity by the versions of its own domains: a write reloads only the
entities in the domains it changed, so a plan edit no longer reloads and decrypts accounts, holdings and the rest."""

from __future__ import annotations

import pytest

import db
from forecast import cache as forecast_cache

FID = 1


@pytest.fixture
def loads(monkeypatch):
    """Records which entities were loaded from the database (store misses)."""
    seen = []
    real = db.store.get_or_load_entity

    def spy(family_id, entity_name, loader_fn, **kwargs):
        def counted(path):
            seen.append(entity_name)
            return loader_fn(path)
        return real(family_id, entity_name, counted, **kwargs)

    monkeypatch.setattr(db.store, "get_or_load_entity", spy)
    db.store.clear()
    yield seen
    db.store.clear()


def _load_all():
    db.store.get_accounts(family_id=FID)
    db.store.get_tuition_ledger(family_id=FID)
    db.store.get_family_members(family_id=FID)


def test_a_plan_save_keeps_every_entity_cached(loads):
    _load_all()
    assert sorted(loads) == ["accounts", "family_members", "tuition_ledger"]
    loads.clear()
    forecast_cache.invalidate_family_cache(FID, domains=["scenarios"])
    _load_all()
    assert loads == []


def test_a_write_reloads_only_the_entities_of_the_domains_it_changed(loads):
    _load_all()
    loads.clear()
    forecast_cache.invalidate_family_cache(FID, domains=["accounts"])
    _load_all()
    assert loads == ["accounts"]


def test_a_mutation_of_unknown_scope_reloads_everything(loads, monkeypatch):
    monkeypatch.setattr(forecast_cache, "get_request_domains", lambda _fid: None)
    _load_all()
    loads.clear()
    forecast_cache.invalidate_family_cache(FID)
    _load_all()
    assert sorted(loads) == ["accounts", "family_members", "tuition_ledger"]


def test_scoped_purge_and_explicit_full_purge(loads):
    _load_all()
    loads.clear()
    db.store.invalidate_family(FID, domains=["college"])
    _load_all()
    assert loads == ["tuition_ledger"], "a scoped purge drops only that domain's entities"
    loads.clear()
    db.store.invalidate_family(FID)
    _load_all()
    assert sorted(loads) == ["accounts", "family_members", "tuition_ledger"], "no domains purges everything"


def test_an_entity_without_a_version_is_loaded_uncached(loads, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("no domain versions")

    monkeypatch.setattr(forecast_cache, "get_domain_versions", broken)
    db.store.get_accounts(family_id=FID)
    db.store.get_accounts(family_id=FID)
    assert loads == ["accounts", "accounts"]


def test_a_restore_leaves_every_counter_above_its_value_before_the_restore(tmp_path):
    from db.domain_versions import load_domain_versions_row, raise_rows_above, save_domain_versions_row

    state_db = tmp_path / "family.db"
    save_domain_versions_row(state_db, 9, 40, {"accounts": 30, "college": 12})
    before = load_domain_versions_row(state_db, 9)
    save_domain_versions_row(state_db, 9, 5, {"accounts": 4, "holdings": 7})  # the backup's older counters
    raise_rows_above(state_db, 9, before)
    state_version, domains = load_domain_versions_row(state_db, 9)
    assert state_version > 40
    assert domains["accounts"] > 30 and domains["college"] > 12 and domains["holdings"] > 7
    raise_rows_above(tmp_path / "new.db", 9, None)  # a restore into a new household has no floor
    assert load_domain_versions_row(tmp_path / "new.db", 9)[0] == 2
