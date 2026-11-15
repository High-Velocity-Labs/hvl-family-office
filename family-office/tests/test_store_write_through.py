"""A repository save patches the kept entities it changed (db/store.py `write_through`): the next read loads nothing
and returns what a fresh load from the database returns. Entities whose domains the save bumps through other tables
stay kept; another process's write to the same domains still makes the next read load."""

from __future__ import annotations

import pytest

import db
from db import account_roles, accounts, balance_history, balance_snapshots, education, families
from db import household_assumptions
from forecast import cache as forecast_cache

FID = 1

READS = {
    "accounts": lambda: db.store.get_accounts(family_id=FID),
    "holdings_by_account": lambda: db.store.get_holdings_by_account(family_id=FID),
    "account_roles": lambda: db.store.get_account_roles(family_id=FID),
    "balance_history": lambda: balance_snapshots.load_balance_history_map(family_id=FID),
    "tuition_ledger": lambda: db.store.get_tuition_ledger(family_id=FID),
    "tuition_labels": lambda: db.store.get_tuition_labels(family_id=FID),
    "household_profile": lambda: db.store.get_household_profile(family_id=FID),
    "household_assumptions": lambda: household_assumptions.get_assumptions(family_id=FID),
}


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


def _read_all() -> dict:
    return {name: read() for name, read in READS.items()}


def _assert_patched(loads) -> None:
    """Every entity reads without a load, and as a fresh load from the database reads it."""
    loads.clear()
    kept = _read_all()
    assert loads == []
    db.store.clear()
    assert kept == _read_all()


def _child_id() -> int:
    return int(db.store.get_family_members(family_id=FID)[0]["user_id"])


def test_tuition_saves_patch_the_ledger_and_its_labels(loads):
    child = _child_id()
    _read_all()
    education.upsert_tuition_record(FID, child, "2087-2088", 18000.0, notes="first", school_name="School A")
    _assert_patched(loads)
    education.upsert_tuition_record(FID, child, "2087-2088", 19500.0, notes="raised")
    _assert_patched(loads)
    assert education.delete_tuition_by_year(FID, "2087-2088") == 1
    _assert_patched(loads)


def test_a_tuition_year_record_save_keeps_the_ledger(loads):
    _read_all()
    education.upsert_tuition_year_record(FID, "2032-2033", {"school": "School B", "total": 1200.0})
    _assert_patched(loads)
    education.delete_tuition_year_record(FID, "2032-2033")
    _assert_patched(loads)


def test_an_assumptions_save_patches_its_section_and_keeps_the_profile(loads):
    _read_all()
    household_assumptions.set_section(FID, "pension", {"monthly": 1500, "start_age": 62})
    _assert_patched(loads)
    merged = household_assumptions.merge_dict_section(FID, "pension", {"start_age": 64})
    assert merged == {"monthly": 1500, "start_age": 64}
    _assert_patched(loads)
    household_assumptions.set_section(FID, "pension", None)
    _assert_patched(loads)


def test_a_profile_save_patches_the_profile(loads):
    _read_all()
    families.upsert_household_profile(FID, state="WA", annual_spending=91000.0, retirement_age=60)
    _assert_patched(loads)
    families.update_household_metrics(FID, annual_savings=24000.0, inflation_rate=0.03)
    _assert_patched(loads)


def test_role_saves_patch_the_roles(loads):
    _read_all()
    families.upsert_account_role(FID, "acct_role_test", role="cash_liquid")
    _assert_patched(loads)
    families.upsert_account_role(FID, "acct_role_test", role="tax_liability")
    _assert_patched(loads)
    assert families.confirm_all_roles(FID, [{"monarch_account_id": "acct_role_test"}, {"monarch_account_id": "x2"}]) == 2
    _assert_patched(loads)


def test_a_provider_sync_patches_accounts_holdings_and_history(loads):
    _read_all()
    synced = [
        {"id": "sfin_wt_1", "displayName": "Checking", "currentBalance": 1200.5, "type": {"name": "depository"}},
        {"id": "sfin_wt_2", "displayName": "Brokerage", "currentBalance": 5000.0, "type": {"name": "brokerage"}},
    ]
    holdings = {"sfin_wt_2": [{"ticker": "VTI", "quantity": 3, "totalValue": 900.0}]}
    accounts.replace_accounts_and_holdings(FID, synced, holdings, provider="simplefin")
    _assert_patched(loads)
    accounts.replace_accounts(FID, synced[:1], provider="simplefin", as_of_date="2031-01-02")
    _assert_patched(loads)
    accounts.replace_holdings(FID, {"sfin_wt_1": [{"ticker": "BND", "totalValue": 10.0}]}, provider="simplefin")
    _assert_patched(loads)
    assert accounts.toggle_account_net_worth(FID, "sfin_wt_1", include=False) == "Checking"
    _assert_patched(loads)
    accounts.replace_accounts(FID, [], provider="simplefin")
    _assert_patched(loads)


def test_manual_account_and_snapshot_saves_patch_what_they_wrote(loads):
    _read_all()
    created = account_roles.upsert_manual_account(FID, "wt", display_name="Car loan", balance=900.0, role="other")
    _assert_patched(loads)
    balance_history.record_account_balance_snapshots(
        FID, [{"account_id": created["id"], "date": "2031-02-01", "balance": 850.0}]
    )
    _assert_patched(loads)
    assert balance_history.delete_account_balance_snapshot(FID, created["id"], "2031-02-01")
    _assert_patched(loads)
    assert account_roles.delete_manual_account(FID, created["id"])
    _assert_patched(loads)


def test_another_process_write_after_a_patch_still_loads(loads):
    _read_all()
    families.upsert_household_profile(FID, state="OR")
    loads.clear()
    forecast_cache.invalidate_family_cache(FID, domains=["household.identity"])  # e.g. another worker's save
    db.store.get_household_profile(family_id=FID)
    household_assumptions.get_assumptions(family_id=FID)
    assert sorted(loads) == ["household_assumptions", "household_profile"]


def test_a_save_that_writes_nothing_leaves_its_entity_to_load(loads):
    _read_all()
    assert accounts.toggle_account_net_worth(FID, "no_such_account") is None
    loads.clear()
    db.store.get_accounts(family_id=FID)
    db.store.get_tuition_ledger(family_id=FID)
    assert loads == ["accounts"]


def test_a_save_that_writes_nothing_while_another_process_bumps_its_domain_still_loads(loads):
    _read_all()

    def _no_op_write_meanwhile_bumped():
        forecast_cache.invalidate_family_cache(FID, domains=["accounts"])  # another worker's sync, not this write
        return None

    db.store.write_through(
        FID, db.store._resolve_active_db_path(None), ("monarch_accounts",), _no_op_write_meanwhile_bumped,
        {"accounts": db.store.unchanged},
    )
    loads.clear()
    db.store.get_accounts(family_id=FID)
    assert loads == ["accounts"]
