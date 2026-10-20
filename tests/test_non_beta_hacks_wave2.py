"""
tests/test_non_beta_hacks_wave2.py: Unit tests for Wave 2 & Wave 3 non-beta hacks cleanup:
- Relational load/save symmetry for family_gifts, career_compensation, company_equity_grants
- Read-time DB mutation elimination for load_scenario_state() and rebuild_historical_net_worth_from_snapshots()
- Monolithic family_office.db dual-write retirement in _sync_auth_records_to_peer_db
"""

from __future__ import annotations

from pathlib import Path
import pytest

import db.scenarios
from db.balance_history import rebuild_historical_net_worth_from_snapshots, save_balance_history_map
from db.data_migration import try_relational_load, try_relational_save
import forecast.storage
from forecast.storage import load_scenario_state
import security


@pytest.fixture
def temp_family_db(tmp_path: Path):
    db_file = tmp_path / "family_1.db"
    security.init_db(db_file)
    with security.get_db_connection(db_file) as conn:
        with conn:
            conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (1, 'Test Family')")
    return db_file


def test_roundtrip_family_gifts(temp_family_db: Path):
    data = {
        "annual_exclusion_limits": {},
        "recipients": [
            {
                "name": "Jane Doe",
                "relationship": "Child",
                "member_count": 1,
                "notes": "College student",
                "gifts": [
                    {"year": 2024, "amount": 18000.0, "notes": "Tuition contribution"},
                    {"year": 2025, "amount": 19000.0, "notes": "Annual exclusion"},
                ],
            }
        ],
    }
    assert try_relational_save(temp_family_db, "family_gifts", data, family_id=1) is True
    handled, loaded = try_relational_load(temp_family_db, "family_gifts", family_id=1)
    assert handled is True
    assert isinstance(loaded, dict)
    assert "recipients" in loaded
    assert len(loaded["recipients"]) == 1
    rec = loaded["recipients"][0]
    assert rec["name"] == "Jane Doe"
    assert rec["relationship"] == "Child"
    assert len(rec["gifts"]) == 2
    assert rec["gifts"][0]["year"] == 2024
    assert rec["gifts"][0]["amount"] == 18000.0
    assert rec["gifts"][1]["amount"] == 19000.0


def test_roundtrip_career_compensation(temp_family_db: Path):
    data = {
        "history": [
            {
                "year": 2025,
                "company": "Apex Dynamics",
                "salary": 275000.0,
                "bonus": 85000.0,
                "notes": "Performance review",
            },
            {
                "year": 2024,
                "company": "Apex Dynamics",
                "salary": 250000.0,
                "bonus": 60000.0,
                "notes": "Annual bonus",
            },
        ]
    }
    assert try_relational_save(temp_family_db, "career_compensation", data, family_id=1) is True
    handled, loaded = try_relational_load(temp_family_db, "career_compensation", family_id=1)
    assert handled is True
    assert isinstance(loaded, list)
    assert len(loaded) == 2
    row_2025 = next(r for r in loaded if r["year"] == 2025)
    assert row_2025["company"] == "Apex Dynamics"
    assert row_2025["salary"] == 275000.0
    assert row_2025["bonus"] == 85000.0


def test_roundtrip_company_equity_grants(temp_family_db: Path):
    data = {
        "equityGrants": [
            {
                "grant_label": "Founder Preferred Grant",
                "grant_type": "iso",
                "strike_price": 4.25,
                "shares_granted": 40000.0,
                "shares_vested": 20000.0,
                "shares_unvested": 20000.0,
                "shares_exercised": 0.0,
                "cost_basis": 4.25,
                "grant_date": "2023-03-01",
                "fully_vested_date": "2027-03-01",
                "vesting_schedule": {"2024": 10000, "2025": 10000, "2026": 10000, "2027": 10000},
            }
        ]
    }
    assert try_relational_save(temp_family_db, "company_equity_grants", data, family_id=1) is True
    handled, loaded = try_relational_load(temp_family_db, "company_equity_grants", family_id=1)
    assert handled is True
    assert isinstance(loaded, list)
    assert len(loaded) == 1
    grant = loaded[0]
    assert grant["grant_label"] == "Founder Preferred Grant"
    assert grant["grant_type"] == "iso"
    assert grant["strike_price"] == 4.25
    assert grant["shares_granted"] == 40000.0
    assert grant["shares_vested"] == 20000.0
    assert grant["vesting_schedule"] == {"2024": 10000, "2025": 10000, "2026": 10000, "2027": 10000}


def test_load_scenario_state_no_sqlite_write_on_pure_read(temp_family_db: Path, monkeypatch: pytest.MonkeyPatch):
    test_state = {
        "scenarios": [
            {"id": "scen_baseline", "name": "Baseline", "color": "#3b82f6", "equity_growth_preset": "moderate"}
        ],
        "events": [{"id": "ev1", "name": "Event 1"}],
        "active_scenario_id": "scen_baseline",
    }
    db.scenarios.save_scenario_state(family_id=1, state=test_state, db_path=temp_family_db)
    monkeypatch.setattr(forecast.storage, "get_db_path", lambda: temp_family_db)

    save_calls = []
    orig_save = db.scenarios.save_scenario_state

    def mock_save(*args, **kwargs):
        save_calls.append((args, kwargs))
        return orig_save(*args, **kwargs)

    monkeypatch.setattr(db.scenarios, "save_scenario_state", mock_save)

    # 1. Default read (persist_repairs=False) must NOT mutate SQLite
    res = load_scenario_state(family_id=1, persist_repairs=False)
    assert len(save_calls) == 0
    assert res["scenarios"][0]["color"] == "#1D4ED8"

    # 2. Explicit repair persistence (persist_repairs=True) saves repairs
    res_persisted = load_scenario_state(family_id=1, persist_repairs=True)
    assert len(save_calls) == 1
    assert res_persisted["scenarios"][0]["color"] == "#1D4ED8"


def test_rebuild_historical_net_worth_persist_flag(temp_family_db: Path, monkeypatch: pytest.MonkeyPatch):
    save_balance_history_map(
        family_id=1, history_map={"acc_test": {"2025-01-01": 75000.0}}, db_path=temp_family_db
    )

    encrypted_saves = []
    orig_db_save = security.db_save_encrypted

    def mock_db_save(path, key, *args, **kwargs):
        if key == "historical_net_worth":
            encrypted_saves.append(key)
        return orig_db_save(path, key, *args, **kwargs)

    monkeypatch.setattr(security, "db_save_encrypted", mock_db_save)

    # 1. persist=False: computes series without SQLite write
    series_false = rebuild_historical_net_worth_from_snapshots(
        family_id=1, db_path=temp_family_db, persist=False
    )
    assert len(encrypted_saves) == 0
    assert len(series_false) > 0

    # 2. persist=True: computes series and writes to SQLite
    series_true = rebuild_historical_net_worth_from_snapshots(
        family_id=1, db_path=temp_family_db, persist=True
    )
    assert len(encrypted_saves) == 1
    assert len(series_true) > 0


def test_session_auth_sync_does_not_write_legacy_monolithic(tmp_path: Path):
    from db.models import Family
    from db.session import get_orm_session

    uni_dir = tmp_path / "universe"
    fam_dir = uni_dir / "families"
    fam_dir.mkdir(parents=True)
    src_db = fam_dir / "1.db"
    legacy_db = uni_dir / "family_office.db"
    legacy_db.touch()

    security.init_db(src_db)
    with get_orm_session(src_db, family_id=1, commit=True) as sess:
        fam = sess.get(Family, 1)
        if fam is not None:
            fam.name = "Synced Family"
        else:
            sess.add(Family(family_id=1, name="Synced Family"))

    # Assert global.db was created/synced as expected
    global_db = uni_dir / "global.db"
    assert global_db.exists()

    # Assert legacy family_office.db was NOT mutated/initialized into a peer
    assert legacy_db.stat().st_size == 0
