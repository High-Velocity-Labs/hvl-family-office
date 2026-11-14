"""Household amounts and gift-recipient names written before their columns were encrypted are encrypted once by
`db.plaintext_columns`, and stay readable (and, for recipients, findable by name) afterwards."""

from __future__ import annotations

import sqlite3

import pytest

from db import equity, gifting
from db.models import EquityGrantRecord
from db.plaintext_columns import encrypt_plaintext_columns
from db.session import get_orm_session, resolve_db_path
from sqlalchemy import select

FID = 1


@pytest.fixture
def db_path():
    path = resolve_db_path(None, family_id=FID)
    gifting.upsert_gift_recipient(family_id=FID, recipient_group_name="Sweep Test Group", db_path=path)
    yield path
    gifting.delete_recipient_gifts(family_id=FID, recipient_group_name="Sweep Test Group", db_path=path)


def _raw(path, sql, params=()):
    with sqlite3.connect(path) as conn:
        return conn.execute(sql, params).fetchall()


def _write_plaintext(path):
    """Puts values back the way the old plain columns stored them."""
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE household_profile SET annual_spending = 123456.0 WHERE family_id = ?", (FID,))
        conn.execute(
            "UPDATE gift_recipients SET recipient_group_name = 'Sweep Test Group' WHERE family_id = ? AND "
            "recipient_id = (SELECT MAX(recipient_id) FROM gift_recipients WHERE family_id = ?)",
            (FID, FID),
        )


def test_new_writes_are_encrypted(db_path):
    names = _raw(db_path, "SELECT recipient_group_name FROM gift_recipients WHERE family_id = ?", (FID,))
    assert names and all(str(n[0]).startswith("gAAAAA") for n in names)


def test_the_sweep_encrypts_plaintext_rows_and_reads_still_match(db_path):
    _write_plaintext(db_path)
    assert _raw(db_path, "SELECT annual_spending FROM household_profile WHERE family_id = ?", (FID,)) == [(123456.0,)]

    assert encrypt_plaintext_columns(db_path) > 0

    spending = _raw(db_path, "SELECT annual_spending FROM household_profile WHERE family_id = ?", (FID,))
    assert str(spending[0][0]).startswith("gAAAAA")
    names = _raw(db_path, "SELECT recipient_group_name FROM gift_recipients WHERE family_id = ?", (FID,))
    assert all(str(n[0]).startswith("gAAAAA") for n in names)
    assert encrypt_plaintext_columns(db_path) == 0  # nothing left in the clear

    listed = [r["recipient_group_name"] for r in gifting.list_gift_recipients(family_id=FID, db_path=db_path)]
    assert "Sweep Test Group" in listed and listed == sorted(listed)


def test_a_recipient_is_found_by_name_through_the_ciphertext(db_path):
    before = len(gifting.list_gift_recipients(family_id=FID, db_path=db_path))
    result = gifting.upsert_gift_recipient(
        family_id=FID, recipient_group_name="Sweep Test Group", member_count=3, db_path=db_path
    )
    assert result["success"]
    rows = gifting.list_gift_recipients(family_id=FID, db_path=db_path)
    assert len(rows) == before  # updated in place, not added again
    assert next(r for r in rows if r["recipient_group_name"] == "Sweep Test Group")["member_count"] == 3


def test_the_sweep_encrypts_a_plaintext_vesting_schedule(db_path):
    cid, _, _, _ = equity.get_or_create_primary_company(family_id=FID, db_path=db_path)
    gid = equity.insert_grant(family_id=FID, company_id=cid, grant_label="Sweep Test Grant", db_path=db_path)
    try:
        schedule = '{"schedule": "4-year monthly, 1-year cliff", "cliff_months": 12}'
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE equity_grants SET vesting_schedule_json = ? WHERE grant_id = ?", (schedule, gid))

        assert encrypt_plaintext_columns(db_path) > 0

        raw = _raw(db_path, "SELECT vesting_schedule_json FROM equity_grants WHERE grant_id = ?", (gid,))
        assert str(raw[0][0]).startswith("gAAAAA")
        with get_orm_session(db_path, family_id=FID) as session:
            grant = session.scalars(select(EquityGrantRecord).where(EquityGrantRecord.grant_id == gid)).one()
            assert grant.vesting_schedule_json == schedule
        assert encrypt_plaintext_columns(db_path) == 0  # nothing left in the clear
    finally:
        equity.delete_grant(family_id=FID, grant_id_or_label=gid, db_path=db_path)


def test_zero_defaults_stay_plain(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE household_profile SET annual_savings = 0.0 WHERE family_id = ?", (FID,))
    encrypt_plaintext_columns(db_path)
    assert _raw(db_path, "SELECT annual_savings FROM household_profile WHERE family_id = ?", (FID,)) == [(0.0,)]


def test_the_sandbox_check_needs_no_key_to_see_an_entered_amount(tmp_path):
    """The sandbox reaper runs in another visitor's request, without this household's key."""
    from db.sandbox_repo import has_sandbox_user_data_in_db

    fam_db = tmp_path / "sandbox.db"
    with sqlite3.connect(fam_db) as conn:
        conn.execute(
            "CREATE TABLE household_profile (family_id INTEGER PRIMARY KEY, annual_spending, annual_savings, "
            "assumptions_json TEXT)"
        )
        conn.execute("INSERT INTO household_profile VALUES (42, 0.0, 0.0, '{}')")
    assert has_sandbox_user_data_in_db(fam_db, 42) is False
    with sqlite3.connect(fam_db) as conn:
        conn.execute("UPDATE household_profile SET annual_spending = 'gAAAAAnot-decryptable-here' WHERE family_id = 42")
    assert has_sandbox_user_data_in_db(fam_db, 42) is True
