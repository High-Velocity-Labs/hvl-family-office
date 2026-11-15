"""A repository save patches the kept entities it changed (db/store.py `write_through`): the next read loads nothing
and returns what a fresh load from the database returns. Entities whose domains the save bumps through other tables
stay kept; another process's write to the same domains still makes the next read load."""

from __future__ import annotations

import pytest

import db
import security
from db import account_roles, accounts, balance_history, balance_snapshots, education, families
from db import equity as equity_repo
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
    "family_members": lambda: db.store.get_family_members(family_id=FID),
    "deletion_status": lambda: db.store.get_deletion_status(family_id=FID),
    "equity_grants": lambda: db.store.get_equity_grants(family_id=FID),
    "equity_companies_summary": lambda: db.store.get_equity_companies_summary(family_id=FID),
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


def _db_path():
    return db.store._resolve_active_db_path(None)


def test_equity_saves_patch_the_grants_and_the_companies(loads):
    _read_all()
    company = equity_repo.create_company(FID, "Company WT", current_fmv=12.0, fmv_date="2031-01-01")
    _assert_patched(loads)
    assert equity_repo.create_company(FID, "company wt", current_fmv=13.0, fmv_date="2031-02-01") == company
    _assert_patched(loads)
    assert equity_repo.record_fmv_valuation(FID, 14.5, "2031-06-01", company_id=company)[0] == company
    _assert_patched(loads)
    grant = equity_repo.insert_grant(
        FID, company, "WT grant", "rsu", 0.0, 1000.0, 250.0, 750.0, "2030-01-01", "2034-01-01"
    )
    _assert_patched(loads)
    assert equity_repo.update_grant(FID, grant, "WT grant", "rsu", company, 0.0, 1000.0, 500.0, 500.0)
    _assert_patched(loads)
    assert equity_repo.delete_grant(FID, grant)
    _assert_patched(loads)
    equity_repo.update_grant(FID, "no such grant", "x")  # matches nothing, bumps nothing: the grants load again
    loads.clear()
    db.store.get_equity_grants(family_id=FID)
    assert loads == ["equity_grants"]


def test_member_saves_patch_the_members_and_a_delete_the_tuition_it_cascades(loads):
    path = _db_path()
    _read_all()
    uid = security.add_family_member(path, FID, "Member WT", birthdate="2020-05-01", relationship="child")
    _assert_patched(loads)
    assert security.update_family_member(path, FID, uid, "Member WT2", birthdate="2020-05-01")
    _assert_patched(loads)
    education.upsert_tuition_record(FID, uid, "2088-2089", 9000.0, school_name="School C")
    _assert_patched(loads)
    assert security.delete_family_member(path, FID, uid)
    _assert_patched(loads)


def test_cancelling_a_deletion_patches_its_status(loads):
    path = _db_path()
    security.schedule_family_deletion(path, family_id=FID, requested_by="Editor")
    assert _read_all()["deletion_status"] is not None
    assert security.cancel_family_deletion(path, family_id=FID)
    _assert_patched(loads)
    assert db.store.get_deletion_status(family_id=FID) is None


def test_merging_a_legacy_history_blob_patches_only_the_days_it_filled(loads):
    created = account_roles.upsert_manual_account(FID, "wt_legacy", display_name="Legacy", balance=10.0, role="other")
    balance_history.record_account_balance_snapshots(
        FID, [{"account_id": created["id"], "date": "2031-03-01", "balance": 40.0}]
    )
    _read_all()
    blob = {created["id"]: {"2031-03-01": 1.0, "2031-03-02": 41.0}}
    assert balance_snapshots.merge_legacy_snapshots(FID, blob)
    _assert_patched(loads)
    assert balance_snapshots.load_balance_history_map(family_id=FID)[created["id"]]["2031-03-01"] == 40.0


def test_an_encrypted_store_save_keeps_every_entity(loads):
    path = _db_path()
    _read_all()
    security.db_save_encrypted(path, "write_through_test_blob", "test", {"a": 1}, family_id=FID)
    _assert_patched(loads)
    security.db_save_encrypted(path, "annual_donations", "philanthropy", {}, family_id=FID)
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
