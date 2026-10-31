"""Regression tests for the effective-plan layers, the single schema mechanism and universe-keyed seeding."""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

import config
from household_factory import build_household
from plan_kwargs import TEST_PLAN
from scripts import seed_demo_families

FID = 41  # an id no other test uses


def _row_counts(global_db: Path, family_id: int) -> dict[str, int]:
    fam_db = global_db.parent / "families" / f"{family_id}.db"
    conn = sqlite3.connect(fam_db)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE family_id = ?", (family_id,)).fetchone()[0]
            for table in ("users", "compensation", "tuition")
        }
    finally:
        conn.close()


def test_universe_of_db_path_uses_directory_names_not_substrings(tmp_path):
    root = tmp_path / "fo_pytest_data_x"
    for universe in ("public", "demo", "sandbox", "test"):
        assert seed_demo_families._universe_of_db_path(root / universe / "global.db") == universe
        assert seed_demo_families._universe_of_db_path(root / universe / "families" / "3.db") == universe
    assert seed_demo_families._universe_of_db_path(root / "beta" / "global.db") == "demo"


def _forget(global_db: Path, family_id: int) -> None:
    for db in (global_db, global_db.parent / "families" / f"{family_id}.db"):
        if db.exists():
            conn = sqlite3.connect(db)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM families WHERE family_id = ?", (family_id,))
            conn.commit()
            conn.close()
    (global_db.parent / "families" / f"{family_id}.db").unlink(missing_ok=True)


def test_same_family_id_in_two_universes_does_not_clobber():
    """Building one family id in 'public' must leave the same id in 'test' untouched (the data dir is named *pytest*)."""
    test_db = config.get_global_db_path("test")
    public_db = config.get_global_db_path("public")
    try:
        build_household(test_db, family_id=FID)
        before = _row_counts(test_db, FID)
        assert before["compensation"] > 0 and before["tuition"] > 0

        build_household(public_db, family_id=FID)

        assert _row_counts(test_db, FID) == before
        assert _row_counts(public_db, FID) == before
    finally:
        _forget(test_db, FID)
        _forget(public_db, FID)


# ---------------------------------------------------------------- F-ENG-7: one effective plan, one event schema


def _scen(sid, events, parent=None, **extra):
    return {"id": sid, "name": sid, "event_ids": list(events), "parent_id": parent, **extra}


def test_legacy_full_list_children_are_migrated_to_added_and_excluded_lists():
    from forecast.event_schema_migration import migrate_legacy_event_lists

    scenarios = [
        _scen("scen_baseline", ["a", "b", "c"], is_baseline=True),
        _scen("child", ["a", "c", "d"], parent="scen_baseline"),
        _scen("grandchild", ["a", "c", "d", "e"], parent="child"),
        _scen("inherits_all", [], parent="scen_baseline"),
        _scen("explicit", ["a", "b", "c", "z"], parent="scen_baseline", added_event_ids=["z"], excluded_event_ids=[]),
    ]
    assert migrate_legacy_event_lists(scenarios) is True
    by_id = {s["id"]: s for s in scenarios}
    assert (by_id["child"]["added_event_ids"], by_id["child"]["excluded_event_ids"]) == (["d"], ["b"])
    assert (by_id["grandchild"]["added_event_ids"], by_id["grandchild"]["excluded_event_ids"]) == (["e"], [])
    assert (by_id["inherits_all"]["added_event_ids"], by_id["inherits_all"]["excluded_event_ids"]) == ([], [])
    assert by_id["explicit"]["added_event_ids"] == ["z"]
    assert "added_event_ids" not in by_id["scen_baseline"]
    assert migrate_legacy_event_lists(scenarios) is False, "idempotent"


def test_hierarchy_resolves_a_migrated_legacy_child_to_its_saved_selection():
    from forecast.event_schema_migration import migrate_legacy_event_lists
    from forecast.hierarchy import resolve_scenario_hierarchy

    scenarios = [
        _scen("scen_baseline", ["a", "b", "c"], is_baseline=True),
        _scen("child", ["a", "c", "d"], parent="scen_baseline"),
        _scen("grandchild", ["a", "c", "d", "e"], parent="child"),
    ]
    migrate_legacy_event_lists(scenarios)
    resolved = {s["id"]: s for s in resolve_scenario_hierarchy(scenarios)}
    assert resolved["child"]["event_ids"] == ["a", "c", "d"]
    assert resolved["grandchild"]["event_ids"] == ["a", "c", "d", "e"]


def test_hierarchy_has_no_legacy_branch_a_child_without_lists_inherits_everything():
    from forecast.hierarchy import resolve_scenario_hierarchy

    scenarios = [_scen("scen_baseline", ["a", "b"], is_baseline=True), _scen("child", ["a"], parent="scen_baseline")]
    child = next(s for s in resolve_scenario_hierarchy(scenarios) if s["id"] == "child")
    assert child["event_ids"] == ["a", "b"]


def test_state_level_layers_copy_moves_onto_the_baseline_plan():
    from forecast.event_schema_migration import migrate_scenario_state

    state = {"active_baseline_layers": ["l1"], "scenarios": [_scen("scen_baseline", [], is_baseline=True), _scen("l1", [])]}
    assert migrate_scenario_state(state) is True
    assert "active_baseline_layers" not in state
    assert state["scenarios"][0]["active_baseline_layers"] == ["l1"]
    own = {"active_baseline_layers": ["stale"], "scenarios": [_scen("scen_baseline", [], is_baseline=True, active_baseline_layers=["l2"])]}
    migrate_scenario_state(own)
    assert own["scenarios"][0]["active_baseline_layers"] == ["l2"], "the Baseline Plan's copy wins"


def test_active_baseline_layers_is_stored_once_on_the_baseline_plan():
    from services import scenario_overlay_service as overlay

    class FakeEngine:
        def __init__(self):
            self.state = {"scenarios": [_scen("scen_baseline", [], is_baseline=True), _scen("l1", [])]}

        def load_scenario_state(self, family_id=0):
            return self.state

        def save_scenario_state(self, state, family_id=0):
            self.state = state

    class FakeCache:
        def invalidate_family_cache(self, family_id):
            pass

    eng = FakeEngine()
    ok, _, active, layers = overlay.toggle_baseline_layer(1, "l1", engine=eng, cache=FakeCache())
    assert (ok, active, layers) == (True, True, ["l1"])
    assert "active_baseline_layers" not in eng.state
    assert eng.state["scenarios"][0]["active_baseline_layers"] == ["l1"]
    assert overlay.get_active_baseline_layers(1, engine=eng) == ["l1"]


def test_a_suspended_layer_keeps_its_place_but_is_not_applied():
    from forecast.hierarchy import resolve_scenario_hierarchy

    scenarios = [
        _scen("scen_baseline", ["a"], is_baseline=True, annual_living_spend=100,
              active_baseline_layers=["l1", "l2"], suspended_baseline_layers=["l1"]),
        _scen("l1", [], parent="scen_baseline", added_event_ids=["x"], annual_living_spend=80),
        _scen("l2", [], parent="scen_baseline", added_event_ids=["y"]),
        _scen("child", [], parent="scen_baseline"),
    ]
    by_id = {s["id"]: s for s in resolve_scenario_hierarchy(scenarios)}
    base = by_id["scen_baseline"]
    assert base["event_ids"] == ["a", "y"]
    assert base["annual_living_spend"] == 100
    assert base["active_baseline_layers"] == ["l2"]
    assert base["suspended_baseline_layers"] == ["l1"]
    assert [(lyr["id"], lyr["suspended"]) for lyr in base["baseline_layers"]] == [("l1", True), ("l2", False)]
    assert (by_id["l1"]["is_baseline_layer"], by_id["l1"]["is_suspended_baseline_layer"]) == (False, True)
    assert by_id["l1"]["event_ids"] == ["a", "y", "x"], "a switched-off layer resolves like any child of the Baseline"
    assert by_id["child"]["event_ids"] == ["a", "y"]

    scenarios[0]["suspended_baseline_layers"] = []
    base_on = next(s for s in resolve_scenario_hierarchy(scenarios) if s["id"] == "scen_baseline")
    assert base_on["event_ids"] == ["a", "x", "y"] and base_on["annual_living_spend"] == 80


def test_suspending_a_layer_keeps_the_stack_and_unmerging_clears_it():
    from services import scenario_overlay_service as overlay

    class FakeEngine:
        def __init__(self):
            self.state = {"scenarios": [_scen("scen_baseline", [], is_baseline=True), _scen("l1", []), _scen("l2", [])]}

        def load_scenario_state(self, family_id=0):
            return self.state

        def save_scenario_state(self, state, family_id=0):
            self.state = state

    class FakeCache:
        def __init__(self):
            self.invalidations = 0

        def invalidate_family_cache(self, family_id):
            self.invalidations += 1

    eng, cache = FakeEngine(), FakeCache()
    kw = {"engine": eng, "cache": cache}
    ok, err, _, _ = overlay.set_baseline_layer_suspended(1, "l1", **kw)
    assert (ok, cache.invalidations) == (False, 0) and "not merged" in err

    overlay.toggle_baseline_layer(1, "l1", **kw)
    overlay.toggle_baseline_layer(1, "l2", **kw)
    assert overlay.set_baseline_layer_suspended(1, "l1", **kw) == (True, None, True, ["l1"])
    assert overlay.get_active_baseline_layers(1, engine=eng) == ["l1", "l2"], "switching off keeps the stack order"
    assert overlay.set_baseline_layer_suspended(1, "l1", suspended=True, **kw) == (True, None, True, ["l1"])
    assert overlay.set_baseline_layer_suspended(1, "l1", **kw) == (True, None, False, [])

    overlay.set_baseline_layer_suspended(1, "l2", suspended=True, **kw)
    overlay.reorder_baseline_layers(1, ["l2", "l1"], **kw)
    assert overlay.get_suspended_baseline_layers(1, engine=eng) == ["l2"]
    overlay.toggle_baseline_layer(1, "l2", active=False, **kw)
    assert overlay.get_suspended_baseline_layers(1, engine=eng) == []
    overlay.toggle_baseline_layer(1, "l2", active=True, **kw)
    assert overlay.get_suspended_baseline_layers(1, engine=eng) == [], "a fresh merge starts switched on"


def test_waterfall_takes_every_plan_value_from_the_caller():
    from forecast.waterfall import run_scenario_simulation

    signature = inspect.signature(run_scenario_simulation)
    for name in TEST_PLAN:
        assert signature.parameters[name].default is inspect.Parameter.empty, name
    with pytest.raises(TypeError):
        run_scenario_simulation([], 0.0, 0.0, 0.0, 0.0, 0.0)


def test_effective_plan_feeds_the_waterfall_its_plan_values():
    from forecast.hierarchy import resolve_effective_plan

    base = {
        "primary_retirement_age": 60, "spouse_retirement_age": 62, "annual_living_spend": 0.0, "annual_savings": 5.0,
        "inflation_rate": 0.03, "primary_ss_claim_age": 68, "spouse_ss_claim_age": 70,
    }
    plan = resolve_effective_plan({}, base, {}, True)
    assert plan.simulation_kwargs() == {
        "primary_retirement_age": 60, "spouse_retirement_age": 62, "annual_spending": 0.0, "annual_savings": 5.0,
        "inflation_rate": 0.03, "primary_ss_claim_age": 68, "spouse_ss_claim_age": 70,
    }


# ---------------------------------------------------------------- F-DATA-3: one schema mechanism (Alembic)

LEGACY_SQL = Path(__file__).resolve().parent / "fixtures" / "legacy_migrations"
EXPECTED_INDEXES = {
    "idx_users_email_hash", "idx_adv_conv_fam", "idx_adv_conv_pinned", "idx_adv_msg_conv", "idx_users_family_relationship",
    "idx_equity_companies_family", "idx_equity_grants_family_company", "idx_fmv_history_company_date",
    "idx_account_roles_family", "idx_compensation_family_year", "idx_tuition_family_child_year",
    "idx_gift_recipients_family", "idx_gifts_family_year", "idx_monarch_accounts_family", "idx_monarch_holdings_family_acc",
    "idx_tax_transcript_records_family", "idx_tuition_year_records_family", "idx_forecast_scenarios_family",
    "idx_forecast_events_family_scen", "idx_philanthropy_donations_family_yr",
}


def _objects(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    finally:
        conn.close()


def _assert_at_head_with_everything_the_old_mechanisms_made(db_path: Path) -> None:
    from db import schema_migrations

    assert schema_migrations.stamped_revision(db_path) == schema_migrations.alembic_head_revision()
    names = _objects(db_path)
    needed = {
        "invite_tokens", "download_events", "family_id_allocator", "household_notifications", "push_subscriptions",
        "advisor_conversations", "advisor_messages", "family_domain_versions", "family_state_versions",
    }
    assert needed <= names
    assert EXPECTED_INDEXES <= names


def test_upgrade_from_a_fresh_database(tmp_path):
    from db import schema_migrations

    db_path = tmp_path / "fresh.db"
    assert schema_migrations.upgrade_to_head(db_path) is True
    _assert_at_head_with_everything_the_old_mechanisms_made(db_path)
    assert schema_migrations.upgrade_to_head(db_path) is False


def test_upgrade_from_a_database_at_revision_0002_keeps_its_rows(tmp_path):
    from alembic import command
    from hvl_common.db import get_engine

    from db import schema_migrations

    db_path = tmp_path / "at0002.db"
    cfg = schema_migrations._alembic_config(db_path)
    with get_engine(db_path).begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0002_google_vault_escrow")
    assert schema_migrations.stamped_revision(db_path) == "0002_google_vault_escrow"
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO families (family_id, name) VALUES (7, 'Kept')")
    conn.commit()
    conn.close()

    assert schema_migrations.upgrade_to_head(db_path) is True
    _assert_at_head_with_everything_the_old_mechanisms_made(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT name FROM families WHERE family_id = 7").fetchone() == ("Kept",)
    conn.close()


def test_upgrade_from_an_unstamped_legacy_database_keeps_its_rows_and_cleans_orphans(tmp_path):
    from hvl_common.db import run_migrations

    from db import schema_migrations

    db_path = tmp_path / "legacy.db"
    run_migrations(db_path, LEGACY_SQL)
    assert schema_migrations.stamped_revision(db_path) is None
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO families (family_id, name) VALUES (3, 'Legacy')")
    conn.execute("INSERT INTO encrypted_store VALUES ('k', 'c', 't', 'payload')")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO family_encrypted_store (family_id, key, category, encrypted_payload) VALUES (0, 'k', 'c', 'x')")
    conn.execute("INSERT INTO family_encrypted_store (family_id, key, category, encrypted_payload) VALUES (3, 'k', 'c', 'x')")
    conn.commit()
    conn.close()

    schema_migrations.upgrade_to_head(db_path)
    _assert_at_head_with_everything_the_old_mechanisms_made(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT name FROM families WHERE family_id = 3").fetchone() == ("Legacy",)
    assert conn.execute("SELECT COUNT(*) FROM encrypted_store").fetchone()[0] == 1, "single-tenant rows are never deleted"
    assert conn.execute("SELECT family_id FROM family_encrypted_store").fetchall() == [(3,)]
    conn.close()


def test_the_other_schema_mechanisms_are_gone():
    import db.conversations
    import db.schema_migrations
    import security.store

    root = Path(__file__).resolve().parent.parent
    assert not hasattr(db.conversations, "ensure_conversation_tables")
    assert not hasattr(db.schema_migrations, "migrate_database")
    assert not (root / "migrations").exists()
    import db.vault

    assert not hasattr(db.vault, "ensure_init_db_tables")
    assert not hasattr(security, "MIGRATIONS_DIR")
    assert "ensure_init_db_tables" not in inspect.getsource(security.store.init_db)
    assert "run_migrations" not in inspect.getsource(security.store)


# ---------------------------------------------------------------- F-DATA-2: a write and its domain bump commit together

BUMP_FID = 96


def _bump_db():
    import security
    from services.request_context import DB_PATH

    path = DB_PATH.for_family(BUMP_FID)
    security.init_db(path)
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM compensation WHERE family_id = ?", (BUMP_FID,))
    conn.commit()
    conn.close()
    return path


def _compensation_version(path: Path) -> int:
    from db.domain_versions import load_domain_versions_row

    row = load_domain_versions_row(path, BUMP_FID)
    return int(row[1].get("compensation", 1)) if row else 1


def _add_compensation(path: Path, employer: str) -> None:
    import db
    from db.models import CompensationRecord

    with db.get_orm_session(path, family_id=BUMP_FID, commit=True) as session:
        session.add(CompensationRecord(family_id=BUMP_FID, tax_year=2026, employer_name=employer, base_salary=1.0, bonus=0.0))


def test_a_committed_write_bumps_its_domains_exactly_once():
    path = _bump_db()
    before = _compensation_version(path)
    _add_compensation(path, "Once Corp")
    assert _compensation_version(path) == before + 1


def test_a_failed_bump_aborts_the_write(monkeypatch):
    import db.domain_versions as domain_versions

    path = _bump_db()
    before = _compensation_version(path)

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("bump failed")

    monkeypatch.setattr(domain_versions, "bump_rows_in_transaction", boom)
    with pytest.raises(sqlite3.OperationalError):
        _add_compensation(path, "Never Committed Corp")
    monkeypatch.undo()

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM compensation WHERE family_id = ?", (BUMP_FID,)).fetchone()[0] == 0
    conn.close()
    assert _compensation_version(path) == before


def test_a_rolled_back_write_bumps_nothing():
    import db
    from db.models import CompensationRecord

    path = _bump_db()
    before = _compensation_version(path)
    with pytest.raises(RuntimeError):
        with db.get_orm_session(path, family_id=BUMP_FID, commit=True) as session:
            session.add(CompensationRecord(family_id=BUMP_FID, tax_year=2026, employer_name="x", base_salary=1.0, bonus=0.0))
            session.flush()
            raise RuntimeError("abort")
    assert _compensation_version(path) == before
