"""Domain-version producer, single-source data-depends, schema mechanism, placeholder rows and sync lifecycle."""

import re
import sqlite3
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: F401,E402  (import order: routes -> ssr must load through the app package first)
from wsgi import app as flask_app  # noqa: E402
import security  # noqa: E402
from account_sync import sync_lifecycle as lc  # noqa: E402
from config import get_family_db_path, get_global_db_path  # noqa: E402
from db import schema_migrations  # noqa: E402
from db.domain_versions import bump_domain_rows, load_domain_versions_row  # noqa: E402
from db.models import Base  # noqa: E402
from forecast import cache as forecast_cache  # noqa: E402
from forecast.cache import CANONICAL_DOMAINS  # noqa: E402
from hvl_common.db import get_db_connection  # noqa: E402
from ssr.section_depends import SECTION_DEPENDS, section_depends  # noqa: E402

LEGACY_HEAD = "0002_google_vault_escrow"


def _run_children(code: str, count: int, *args: str) -> list[subprocess.CompletedProcess]:
    script = f"import sys; sys.path.insert(0, {str(ROOT)!r})\n" + textwrap.dedent(code)
    procs = [
        subprocess.Popen([sys.executable, "-c", script, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(count)
    ]
    done = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        done.append(subprocess.CompletedProcess(p.args, p.returncode, out, err))
    return done


# --- F-DATA-2: the server producer ------------------------------------------------------------------------------


def test_domain_bumps_from_separate_processes_lose_nothing(tmp_path):
    state_db = tmp_path / "state.db"
    code = """
        from pathlib import Path
        from db.domain_versions import bump_domain_rows
        for _ in range(15):
            bump_domain_rows(Path(sys.argv[1]), 7, ["gifting", "estate"])
    """
    for res in _run_children(code, 4, str(state_db)):
        assert res.returncode == 0, res.stderr
    _, domains = load_domain_versions_row(state_db, 7)
    assert domains["gifting"] == 1 + 4 * 15
    assert domains["estate"] == 1 + 4 * 15


def test_bump_that_cannot_be_persisted_raises(tmp_path):
    with pytest.raises(Exception):
        bump_domain_rows(tmp_path, 7, ["gifting"])  # a directory is not a database


def test_state_version_only_moves_forward(tmp_path):
    state_db = tmp_path / "state.db"
    bump_domain_rows(state_db, 3, ["accounts"], state_version=9)
    bump_domain_rows(state_db, 3, ["accounts"], state_version=4)
    assert load_domain_versions_row(state_db, 3)[0] == 9


def test_domainless_mutation_bumps_request_union_not_nothing(tmp_path):
    fid, state_db = 7391, tmp_path / "state.db"
    with flask_app.test_request_context("/"):
        forecast_cache.bump_domain_versions(fid, ["gifting"], state_db=state_db)
        after = forecast_cache.bump_domain_versions(fid, None, state_db=state_db)
    assert after["gifting"] == 3, "a domain-less mutation in a request that recorded domains must still bump them"
    assert after["accounts"] == 1, "...but must not widen to unrelated domains"


def test_domainless_mutation_outside_any_recorded_domains_bumps_everything(tmp_path):
    fid, state_db = 7392, tmp_path / "state.db"
    with flask_app.test_request_context("/"):
        after = forecast_cache.bump_domain_versions(fid, None, state_db=state_db)
    assert all(after[d] == 2 for d in CANONICAL_DOMAINS)


def test_client_never_invents_domain_versions():
    banned = re.compile(r"\b(?:bumpDomains|inferDomainsFromMutationUrl)\b")
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / "static" / "js").rglob("*.js") if banned.search(p.read_text("utf-8"))]
    assert not hits, f"client-side version invention is back in: {hits}"


# --- F-UI-5: data-depends from one source -----------------------------------------------------------------------


def test_every_section_depends_entry_is_canonical():
    for section_id, domains in SECTION_DEPENDS.items():
        assert domains and set(domains) <= set(CANONICAL_DOMAINS), section_id


def test_templates_render_data_depends_from_the_single_table():
    macro = re.compile(r"""data-depends="\{\{ section_depends\('(section-[a-z]+)'\) \}\}\"""")
    seen = 0
    for path in [ROOT / "templates" / "index.html", *(ROOT / "templates" / "components").glob("*.html")]:
        text = path.read_text("utf-8")
        assert len(re.findall(r"data-depends=", text)) == len(macro.findall(text)), f"{path.name} hand-copies depends"
        for line in text.splitlines():
            m = macro.search(line)
            if m:
                seen += 1
                assert f'id="{m.group(1)}"' in line, f"{path.name}: macro id does not match its section"
    assert seen >= 22


def test_dashboard_metadata_and_template_global_share_the_table():
    from ssr.dashboard import SECTION_METADATA

    for section_id, meta in SECTION_METADATA.items():
        assert tuple(meta["depends"]) == SECTION_DEPENDS[section_id]
    with flask_app.test_request_context("/"):
        from flask import render_template_string

        rendered = render_template_string("{{ section_depends('section-overview') }}")
    assert rendered == section_depends("section-overview")
    assert "compensation" in rendered and "holdings" in rendered  # the old index.html placeholder had dropped these


def test_client_keeps_no_copy_of_section_depends():
    banned = re.compile(r"DEFAULT_SECTION_DEPENDS|__SECTION_DEPENDS__")
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / "static" / "js").rglob("*.js") if banned.search(p.read_text("utf-8"))]
    assert not hits


# --- F-DATA-3 / F-DATA-5: one schema mechanism, locked ----------------------------------------------------------


def _alembic_upto(db_path: Path, revision: str) -> None:
    from alembic import command
    from hvl_common.db import get_engine

    cfg = schema_migrations._alembic_config(db_path)
    with get_engine(db_path).begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def _table_columns(db_path: Path) -> dict[str, set[str]]:
    conn = sqlite3.connect(str(db_path))
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {n: {r[1] for r in conn.execute(f"PRAGMA table_info({n})")} for n in names}
    finally:
        conn.close()


def test_baseline_revision_is_frozen_and_does_not_read_live_models():
    text = (ROOT / "alembic" / "versions" / "0001_baseline_schema.py").read_text("utf-8")
    assert not re.search(r"^\s*(from|import)\s+db\b", text, re.M) and "metadata.create_all" not in text
    assert text.count("CREATE TABLE IF NOT EXISTS") >= len(Base.metadata.tables)


def test_head_is_derived_from_the_revision_scripts():
    assert schema_migrations.alembic_head_revision() == "0006_opaque_notification_keys"


def test_fresh_database_matches_the_models_exactly(tmp_path):
    """The drift guard: a model change without a new revision fails here."""
    db_path = tmp_path / "fresh.db"
    assert schema_migrations.upgrade_to_head(db_path) is True
    cols = _table_columns(db_path)
    for name, table in Base.metadata.tables.items():
        assert name in cols, f"{name} missing from a fresh upgrade"
        assert cols[name] == {c.name for c in table.columns}, f"{name} columns drifted from the models"
    assert schema_migrations.stamped_revision(db_path) == schema_migrations.alembic_head_revision()
    assert schema_migrations.upgrade_to_head(db_path) is False


def test_database_at_the_current_schema_upgrades_without_losing_data(tmp_path):
    db_path = tmp_path / "current.db"
    _alembic_upto(db_path, LEGACY_HEAD)
    assert schema_migrations.stamped_revision(db_path) == LEGACY_HEAD
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO families (family_id, name, settings) VALUES (5, 'Kept Family', '{\"a\": 1}')")
    conn.execute(
        "INSERT INTO users (family_id, name, relationship, role) VALUES (5, 'Kept User', 'self', 'editor')"
    )
    conn.commit()
    conn.close()

    assert schema_migrations.upgrade_to_head(db_path) is True
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT name, settings FROM families WHERE family_id = 5").fetchone() == ("Kept Family", '{"a": 1}')
    assert conn.execute("SELECT name FROM users WHERE family_id = 5").fetchone() == ("Kept User",)
    conn.close()
    assert schema_migrations.stamped_revision(db_path) == schema_migrations.alembic_head_revision()


def test_database_missing_the_late_tables_gets_them_and_keeps_existing_ones(tmp_path):
    db_path = tmp_path / "old.db"
    _alembic_upto(db_path, LEGACY_HEAD)
    conn = sqlite3.connect(str(db_path))
    for late in ("invite_tokens", "download_events", "family_id_allocator", "advisor_messages", "advisor_conversations"):
        conn.execute(f"DROP TABLE IF EXISTS {late}")
    conn.execute("INSERT INTO families (family_id, name) VALUES (6, 'Old Family')")
    conn.commit()
    conn.close()

    schema_migrations.upgrade_to_head(db_path)
    cols = _table_columns(db_path)
    for late in ("invite_tokens", "download_events", "family_id_allocator", "advisor_messages", "advisor_conversations"):
        assert late in cols
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT name FROM families WHERE family_id = 6").fetchone() == ("Old Family",)
    conn.close()


def test_unstamped_legacy_database_is_adopted_not_rebuilt(tmp_path):
    """A pre-Alembic file (built by the retired `migrations/*.sql` runner, frozen in tests/fixtures/legacy_migrations, no alembic_version) keeps its rows."""
    from hvl_common.db import run_migrations

    db_path = tmp_path / "legacy.db"
    run_migrations(db_path, ROOT / "tests" / "fixtures" / "legacy_migrations")
    assert schema_migrations.stamped_revision(db_path) is None
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO families (family_id, name) VALUES (1, 'Legacy')")
    conn.commit()
    conn.close()

    schema_migrations.upgrade_to_head(db_path)
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT name FROM families WHERE family_id = 1").fetchone() == ("Legacy",)
    conn.close()
    assert schema_migrations.stamped_revision(db_path) == schema_migrations.alembic_head_revision()


def test_concurrent_processes_migrate_one_database_exactly_once(tmp_path):
    db_path = tmp_path / "race.db"
    code = """
        from pathlib import Path
        from db.schema_migrations import upgrade_to_head
        print("RAN" if upgrade_to_head(Path(sys.argv[1])) else "SKIPPED")
    """
    results = _run_children(code, 4, str(db_path))
    for res in results:
        assert res.returncode == 0, res.stderr
    outcomes = sorted(r.stdout.strip().splitlines()[-1] for r in results)
    assert outcomes == ["RAN", "SKIPPED", "SKIPPED", "SKIPPED"]
    assert schema_migrations.stamped_revision(db_path) == schema_migrations.alembic_head_revision()


def test_migration_lock_blocks_a_second_holder(tmp_path):
    db_path = tmp_path / "locked.db"
    code = """
        from pathlib import Path
        from db.schema_migrations import migration_lock
        with migration_lock(Path(sys.argv[1])):
            print("HELD", flush=True)
    """
    with schema_migrations.migration_lock(db_path):
        child = subprocess.Popen(
            [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r})\n" + textwrap.dedent(code), str(db_path)],
            stdout=subprocess.PIPE, text=True,
        )
        with pytest.raises(subprocess.TimeoutExpired):
            child.communicate(timeout=1.5)
    out, _ = child.communicate(timeout=30)
    assert "HELD" in out


def test_discard_placeholder_family_rows_only_removes_unclaimed_placeholders(tmp_path):
    import db

    db_path = tmp_path / "demo.db"
    schema_migrations.upgrade_to_head(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO families (family_id, name, encryption_key_enc, support_access_enabled) VALUES (1, 'Family 1', NULL, 0)")
    conn.execute("INSERT INTO families (family_id, name, settings) VALUES (2, 'Family 2', '{\"is_demo\": true}')")
    conn.execute("INSERT INTO families (family_id, name, encryption_key_enc) VALUES (3, 'Family 3', 'wrapped-key')")
    conn.execute("INSERT INTO families (family_id, name) VALUES (4, 'Family 4')")
    conn.execute("INSERT INTO users (family_id, name, relationship, role) VALUES (4, 'Someone', 'self', 'editor')")
    conn.commit()
    conn.close()

    assert db.families.discard_placeholder_family_rows(db_path) == 1
    conn = sqlite3.connect(str(db_path))
    assert sorted(r[0] for r in conn.execute("SELECT family_id FROM families")) == [2, 3, 4]
    conn.close()


# --- F-SYNC-2: lifecycle FSM ------------------------------------------------------------------------------------

T0 = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def test_fsm_start_finish_and_restart():
    run = lc.start_run(None, now=T0, lease_seconds=60)
    assert run["state"] == lc.RUNNING
    done = lc.finish_run(run, run["run_id"], lc.SUCCEEDED, now=T0)
    assert done["state"] == lc.SUCCEEDED and done["lease_expires_at"] is None
    assert lc.start_run(done, now=T0, lease_seconds=60)["state"] == lc.RUNNING


def test_fsm_overlapping_run_is_refused_until_the_lease_expires():
    run = lc.start_run(None, now=T0, lease_seconds=60)
    with pytest.raises(lc.SyncInProgress):
        lc.start_run(run, now=T0 + timedelta(seconds=30), lease_seconds=60)
    taken = lc.start_run(run, now=T0 + timedelta(seconds=61), lease_seconds=60)
    assert taken["took_over_from"] == run["run_id"] and taken["run_id"] != run["run_id"]


def test_fsm_illegal_transitions_raise():
    with pytest.raises(lc.SyncTransitionError):
        lc.finish_run(None, "x", lc.SUCCEEDED, now=T0)  # idle -> succeeded
    run = lc.start_run(None, now=T0, lease_seconds=60)
    done = lc.finish_run(run, run["run_id"], lc.FAILED, now=T0, error="boom")
    with pytest.raises(lc.SyncTransitionError):
        lc.finish_run(done, run["run_id"], lc.SUCCEEDED, now=T0)  # failed -> succeeded
    with pytest.raises(lc.SyncTransitionError):
        lc.finish_run(run, "someone-else", lc.SUCCEEDED, now=T0)  # lease lost


FID = 9052
UNI = "test"


@pytest.fixture()
def fam_db():
    fam = get_family_db_path(FID, universe=UNI)
    security.init_db(fam)
    security.init_db(get_global_db_path(universe=UNI))
    with get_db_connection(fam) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO families (family_id, name, settings, support_access_enabled) VALUES (?, ?, ?, 1)",
            (FID, "Sync Lifecycle Test", "{}"),
        )
        conn.commit()
    security.update_family(fam, family_id=FID, name="Sync Lifecycle Test")
    security.db_save_encrypted(fam, "last_sync_metadata", "sync", {}, family_id=FID)
    return fam


def test_lifecycle_is_stored_per_provider_without_clobbering(fam_db):
    from db.sync_metadata import load_provider_sync_entry, merge_provider_sync_entry

    merge_provider_sync_entry(fam_db, FID, "monarch", {"timestamp": "2026-10-29T10:00:00+00:00", "status": "success",
                                                       "last_upstream_refresh_ts": "2026-10-29T09:00:00+00:00"})
    monarch_run = lc.begin_sync(fam_db, FID, "monarch")
    merge_provider_sync_entry(fam_db, FID, "simplefin", {"timestamp": "2026-10-29T11:00:00+00:00", "status": "success"})
    lc.finish_sync(fam_db, FID, "monarch", monarch_run, lc.PARTIAL, error="one account failed")

    monarch = load_provider_sync_entry(fam_db, FID, "monarch")
    assert monarch["last_upstream_refresh_ts"] == "2026-10-29T09:00:00+00:00"
    assert monarch["run"]["state"] == lc.PARTIAL and monarch["run"]["error"] == "one account failed"
    assert lc.current_sync_run(fam_db, FID, "simplefin") == {"state": lc.IDLE}


def test_second_begin_while_running_is_refused_and_survives_a_merge(fam_db):
    from db.sync_metadata import merge_provider_sync_entry

    run_id = lc.begin_sync(fam_db, FID, "monarch")
    merge_provider_sync_entry(fam_db, FID, "monarch", {"timestamp": "2026-10-29T10:00:00+00:00", "status": "success"})
    assert lc.current_sync_run(fam_db, FID, "monarch")["run_id"] == run_id
    with pytest.raises(lc.SyncInProgress):
        lc.begin_sync(fam_db, FID, "monarch")
    lc.finish_sync(fam_db, FID, "monarch", run_id, lc.SUCCEEDED)


def test_run_provider_sync_records_outcomes_and_overlap(fam_db):
    seen = {}

    def _body():
        seen["inner"] = lc.run_provider_sync(fam_db, FID, "monarch", lambda: {"success": True})
        return {"success": True, "status": "partial", "error": "x"}

    out = lc.run_provider_sync(fam_db, FID, "monarch", _body)
    assert out["status"] == "partial"
    assert seen["inner"]["in_progress"] is True and seen["inner"]["success"] is False
    assert lc.current_sync_run(fam_db, FID, "monarch")["state"] == lc.PARTIAL

    with pytest.raises(RuntimeError):
        lc.run_provider_sync(fam_db, FID, "monarch", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert lc.current_sync_run(fam_db, FID, "monarch")["state"] == lc.FAILED

    lc.run_provider_sync(fam_db, FID, "monarch", lambda: {"success": False, "status": "not_connected"})
    assert lc.current_sync_run(fam_db, FID, "monarch")["state"] == lc.IDLE


def test_snapshot_does_not_pin_prior_income_so_the_household_default_applies(monkeypatch):
    """The main snapshot path must hand the simulator None, not a hard-coded 500000, for prior W-2 income."""
    import inspect

    from account_sync import snapshot
    from services import equity_engine

    assert inspect.signature(snapshot.get_financial_snapshot).parameters["prior_w2_income"].default is None
    seen = {}

    def _fake(**kw):
        seen.update(kw)
        raise RuntimeError("stop after capturing the simulator call")

    monkeypatch.setattr(equity_engine, "simulate_valuation_scenario", _fake)
    with pytest.raises(RuntimeError, match="stop after capturing"):
        snapshot.get_financial_snapshot(family_id=1, grants=[])
    assert seen["prior_w2_income"] is None


def test_ensure_demo_database_drops_a_placeholder_row_before_seeding(tmp_path, monkeypatch):
    import config
    from scripts import seed_demo_families
    from services import auth_session

    demo_db = tmp_path / "demo" / "global.db"
    demo_db.parent.mkdir(parents=True)
    schema_migrations.upgrade_to_head(demo_db)
    with sqlite3.connect(str(demo_db)) as conn:
        conn.execute("INSERT INTO families (family_id, name, encryption_key_enc, support_access_enabled) "
                     "VALUES (1, 'Family 1', NULL, 0)")

    seeded = []

    def _seed(db_path, verbose=False):
        if seeded:
            raise AssertionError("seeded twice")
        with sqlite3.connect(str(db_path)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM families WHERE name = 'Family 1'").fetchone()[0] == 0
        seeded.append(Path(db_path))

    monkeypatch.setattr(config, "get_global_db_path", lambda universe=None: demo_db)
    monkeypatch.setattr(config, "get_family_db_path", lambda fid, universe=None: tmp_path / "missing.db")
    monkeypatch.setattr(seed_demo_families, "seed_all_demo_families", _seed)
    monkeypatch.setattr(auth_session, "_VERIFIED_DEMO_DB_STATE", None)
    auth_session.ensure_demo_database()
    assert seeded == [demo_db]


def test_siri_token_rows_are_deleted_and_other_tokens_kept(tmp_path):
    db_path = tmp_path / "global.db"
    _alembic_upto(db_path, "0004_retire_legacy_schema_mechanisms")
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE mcp_tokens (token_id INTEGER PRIMARY KEY, owner_id INTEGER, user_email TEXT, token_hash TEXT)"
    )
    conn.executemany(
        "INSERT INTO mcp_tokens (owner_id, user_email, token_hash) VALUES (?, ?, ?)",
        [(1, "siri:a@example.com", "h1"), (1, "SIRI:b@example.com", "h2"), (1, "a@example.com", "h3")],
    )
    conn.commit()
    conn.close()

    assert schema_migrations.upgrade_to_head(db_path) is True
    conn = sqlite3.connect(str(db_path))
    assert [r[0] for r in conn.execute("SELECT user_email FROM mcp_tokens")] == ["a@example.com"]
    conn.close()
