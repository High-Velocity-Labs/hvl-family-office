"""
Per-day account balance rows (`db/balance_snapshots.py`): a sync adds only the days it brings, settled days
are not rewritten, only `balance_sheet` is bumped, and a legacy `account_balance_history` blob moves to rows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import security
from db import balance_snapshots, data_migration
from db.balance_history import record_account_balance_snapshots
from db.session import get_orm_session
from db.vault import upsert_encrypted_store_payload
from forecast.cache import get_domain_versions
from hvl_common.db import get_db_connection


@pytest.fixture
def family_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "family_1.db"
    security.init_db(db_file)
    with get_db_connection(db_file) as conn:
        with conn:
            conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (1, 'Test Family')")
    return db_file


def _raw_rows(db_file: Path):
    with get_db_connection(db_file) as conn:
        return conn.execute(
            "SELECT account_id, snapshot_date, balance_enc FROM account_balance_snapshots ORDER BY snapshot_date"
        ).fetchall()


def test_write_snapshots_upserts_one_encrypted_row_per_day(family_db: Path):
    with get_orm_session(family_db, family_id=1, commit=True) as session:
        balance_snapshots.write_snapshots(session, 1, {"acc_a": {"2025-01-01": 100.0, "2025-01-02": 110.0}})
    with get_orm_session(family_db, family_id=1, commit=True) as session:
        balance_snapshots.write_snapshots(session, 1, {"acc_a": {"2025-01-02": 120.0}})

    rows = _raw_rows(family_db)
    assert [(r["account_id"], r["snapshot_date"]) for r in rows] == [("acc_a", "2025-01-01"), ("acc_a", "2025-01-02")]
    assert all("120" not in str(r["balance_enc"]) for r in rows)
    assert balance_snapshots.load_balance_history_map(1, family_db) == {
        "acc_a": {"2025-01-01": 100.0, "2025-01-02": 120.0}
    }


def test_refresh_window_skips_settled_days_and_writes_new_ones(family_db: Path):
    with get_orm_session(family_db, family_id=1, commit=True) as session:
        balance_snapshots.write_snapshots(session, 1, {"acc_a": {"2025-01-01": 100.0, "2025-03-01": 300.0}})
    batch = {"acc_a": {"2025-01-01": 999.0, "2025-02-01": 200.0, "2025-03-01": 301.0, "2025-03-05": 305.0}}
    with get_orm_session(family_db, family_id=1, commit=True) as session:
        written = balance_snapshots.write_snapshots(session, 1, batch, refresh_recent_days=7)

    assert written == {"acc_a": {"2025-02-01": 200.0, "2025-03-01": 301.0, "2025-03-05": 305.0}}
    assert balance_snapshots.load_balance_history_map(1, family_db)["acc_a"] == {
        "2025-01-01": 100.0,
        "2025-02-01": 200.0,
        "2025-03-01": 301.0,
        "2025-03-05": 305.0,
    }


def test_record_snapshots_bumps_only_balance_sheet_and_sets_latest_balance(family_db: Path):
    record_account_balance_snapshots(
        family_id=1,
        snapshots=[{"account_name": "Checking", "role": "cash_liquid", "date": "2025-01-01", "balance": 100.0}],
        db_path=family_db,
    )
    before = get_domain_versions(1, state_db=family_db)
    result = record_account_balance_snapshots(
        family_id=1,
        snapshots=[
            {"account_name": "Checking", "date": "2025-02-01", "balance": 250.0},
            {"account_name": "Checking", "date": "2024-12-01", "balance": 50.0},
        ],
        db_path=family_db,
    )
    after = get_domain_versions(1, state_db=family_db)

    assert result["recorded_count"] == 2
    changed = {k for k in after if after[k] != before.get(k)}
    assert "balance_sheet" in changed
    assert not changed & {"scenarios", "equity", "tax_profile", "household.members", "advisor.threads"}
    history = balance_snapshots.load_balance_history_map(1, family_db)
    (acc_id,) = history.keys()
    assert history[acc_id] == {"2024-12-01": 50.0, "2025-01-01": 100.0, "2025-02-01": 250.0}
    import db.accounts

    acc = next(a for a in db.accounts.list_accounts(family_id=1, db_path=family_db) if a["id"] == acc_id)
    assert float(acc["currentBalance"]) == 250.0


def test_legacy_history_blob_moves_to_rows(family_db: Path):
    legacy = {"acc_a": {"2025-01-01": "$1,000.50", "2025-01-02": 1100}}
    ciphertext = security.encrypt_data(legacy, key=security.get_family_key(family_db, 1))
    upsert_encrypted_store_payload(family_db, 1, "account_balance_history", "accounts", ciphertext)

    assert data_migration.migrate_encrypted_store_to_relational(family_db) >= 1

    assert balance_snapshots.load_balance_history_map(1, family_db) == {
        "acc_a": {"2025-01-01": 1000.5, "2025-01-02": 1100.0}
    }
    with get_db_connection(family_db) as conn:
        left = conn.execute(
            "SELECT COUNT(*) FROM family_encrypted_store WHERE key = 'account_balance_history'"
        ).fetchone()[0]
    assert left == 0


def test_legacy_blob_merges_into_rows_a_sync_already_wrote(family_db: Path):
    with get_orm_session(family_db, family_id=1, commit=True) as session:
        balance_snapshots.write_snapshots(session, 1, {"acc_a": {"2025-01-02": 1200.0}})
    legacy = {"acc_a": {"2025-01-01": 1000.0, "2025-01-02": 1100.0}, "acc_b": {"2024-06-01": 50.0}}
    ciphertext = security.encrypt_data(legacy, key=security.get_family_key(family_db, 1))
    upsert_encrypted_store_payload(family_db, 1, "account_balance_history", "accounts", ciphertext)

    data_migration.migrate_encrypted_store_to_relational(family_db)

    assert balance_snapshots.load_balance_history_map(1, family_db) == {
        "acc_a": {"2025-01-01": 1000.0, "2025-01-02": 1200.0},
        "acc_b": {"2024-06-01": 50.0},
    }


def test_series_save_and_account_writes_keep_the_cached_history(family_db: Path):
    with get_orm_session(family_db, family_id=1, commit=True) as session:
        balance_snapshots.write_snapshots(session, 1, {"acc_a": {"2025-01-01": 100.0}})
    before = get_domain_versions(1, state_db=family_db)
    security.db_save_encrypted(family_db, "historical_net_worth", "balance_history", [], family_id=1)
    after = get_domain_versions(1, state_db=family_db)
    assert after["balance_sheet"] != before["balance_sheet"]
    assert after["balance_sheet.history"] == before["balance_sheet.history"]
