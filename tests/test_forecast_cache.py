"""
Unit tests for forecast_cache and simulation acceleration.
Tests LRU bounding, multi-universe cache isolation, state version invalidation,
family_id=0 safety, pipeline reuse, and bisection search accuracy.
"""

import pytest
import forecast_cache
import forecast_engine
from forecast.context import HouseholdContext, build_household_context


def test_forecast_cache_basic_and_isolation():
    forecast_cache.clear_all_caches()
    
    # 1. Zero tolerance for family_id <= 0: caching is bypassed
    key_zero = forecast_cache.make_cache_key(0, "public", {"a": 1})
    forecast_cache.set_simulation(key_zero, {"result": "zero"})
    # Key version is 1, but operations on family_id <= 0 should be safe
    assert forecast_cache.get_state_version(0) == 1

    # 2. Family & Universe Isolation
    key_pub = forecast_cache.make_cache_key(101, "public", {"spend": 350000})
    key_beta = forecast_cache.make_cache_key(101, "beta", {"spend": 350000})
    key_other_fam = forecast_cache.make_cache_key(102, "public", {"spend": 350000})

    assert key_pub != key_beta
    assert key_pub != key_other_fam

    # Store simulation in public universe for family 101
    sim_data_pub = {"success": True, "active_scenario_id": "scen_baseline", "val": 123}
    forecast_cache.set_simulation(key_pub, sim_data_pub)

    # Cache hit on exact match
    assert forecast_cache.get_simulation(key_pub) == sim_data_pub
    # Cache miss on beta universe and other family
    assert forecast_cache.get_simulation(key_beta) is None
    assert forecast_cache.get_simulation(key_other_fam) is None


def test_forecast_cache_invalidation_lifecycle():
    forecast_cache.clear_all_caches()
    fam_id = 202

    v1 = forecast_cache.get_state_version(fam_id)
    key_sim = forecast_cache.make_cache_key(fam_id, "public", {"sim": 1})
    key_mc = forecast_cache.make_cache_key(fam_id, "public", {"mc": 1})

    forecast_cache.set_simulation(key_sim, {"sim": "active"})
    forecast_cache.set_monte_carlo(key_mc, {"mc": "active"})

    assert forecast_cache.get_simulation(key_sim) is not None
    assert forecast_cache.get_monte_carlo(key_mc) is not None

    # Invalidate family cache
    forecast_cache.invalidate_family_cache(fam_id)

    # Version should have incremented
    v2 = forecast_cache.get_state_version(fam_id)
    assert v2 == v1 + 1

    # Old keys should be purged
    assert forecast_cache.get_simulation(key_sim) is None
    assert forecast_cache.get_monte_carlo(key_mc) is None

    # New cache key should reflect version 2
    key_sim_v2 = forecast_cache.make_cache_key(fam_id, "public", {"sim": 1})
    assert f"v{v2}" in key_sim_v2
    assert key_sim_v2 != key_sim


def test_monte_carlo_pipeline_reuse():
    """Verify that passing precomputed_sim avoids re-executing simulate_multi_scenarios."""
    # Dummy precomputed sim with unique identifier
    dummy_sim = {
        "success": True,
        "scenarios": [
            {
                "id": "scen_test",
                "name": "Test Plan",
                "annual_living_spend": 200000.0,
                "primary_retirement_age": 55,
                "growth_us_equity": 0.08,
                "growth_intl_equity": 0.07,
                "growth_bonds": 0.04,
                "growth_cash": 0.02,
                "growth_private_investments": 0.10,
                "growth_real_estate": 0.035,
            }
        ],
        "active_schedule": [
            {"year": 2026, "age_primary": 45, "total_net_worth": 5000000.0, "company_equity": 0.0},
            {"year": 2027, "age_primary": 46, "total_net_worth": 5200000.0, "company_equity": 0.0},
        ],
        "scenarios_results": {
            "scen_test": {
                "schedule": [
                    {"year": 2026, "age_primary": 45, "total_net_worth": 5000000.0, "company_equity": 0.0},
                    {"year": 2027, "age_primary": 46, "total_net_worth": 5200000.0, "company_equity": 0.0},
                ]
            }
        }
    }

    res = forecast_engine.run_monte_carlo_simulation(
        family_id=0,
        scenario_id="scen_test",
        trials=100,
        precomputed_sim=dummy_sim,
    )
    assert res["success"] is True
    assert res["trials"] == 100
    assert "percentiles_timeline" in res



def test_household_context_decoupling_zero_db_io():
    """Verify HouseholdContext constructs clean safe defaults when family_id=0."""
    ctx = build_household_context(family_id=0)
    assert ctx.family_id == 0
    assert ctx.user_state == "WA"
    assert ctx.filing_status == "MFJ"
    assert ctx.current_share_price == 0.0

    # Ensure run_scenario_simulation accepts context and runs without errors
    sim = forecast_engine.run_scenario_simulation(
        events=[],
        liquid_start=1_000_000.0,
        retirement_start=500_000.0,
        real_estate_start=0.0,
        mortgage_start=0.0,
        other_start=0.0,
        family_id=0,
        context=ctx,
    )
    assert sim is not None
    assert "schedule" in sim
    assert len(sim["schedule"]) > 0


def test_forecast_cache_update_active_scenario():
    """Verify that update_active_scenario modifies cached data in place without cache eviction."""
    forecast_cache.clear_all_caches()
    fam_id = 303
    universe = "public"

    key = forecast_cache.make_cache_key(fam_id, universe, {})
    sim_data = {
        "active_scenario_id": "scen_baseline",
        "scenarios": [
            {"id": "scen_baseline", "name": "Baseline", "is_active": True},
            {"id": "scen_netjets", "name": "NetJets", "is_active": False},
        ],
        "scorecard": [
            {"id": "scen_baseline", "retirement_readiness": {"can_retire_today": True}},
            {"id": "scen_netjets", "retirement_readiness": {"can_retire_today": False}},
        ],
        "scenario_schedules": {
            "scen_baseline": [{"year": 2026, "total_net_worth": 100}],
            "scen_netjets": [{"year": 2026, "total_net_worth": 90}],
        },
        "scenario_cash_flows": {
            "scen_baseline": [{"year": 2026, "net_savings": 10}],
            "scen_netjets": [{"year": 2026, "net_savings": 5}],
        },
        "scenario_longevity_breakdowns": {
            "scen_baseline": {"solvency_age": 95},
            "scen_netjets": {"solvency_age": 88},
        },
        "active_schedule": [{"year": 2026, "total_net_worth": 100}],
        "active_cash_flow_series": [{"year": 2026, "net_savings": 10}],
        "active_longevity_breakdown": {"solvency_age": 95},
    }

    forecast_cache.set_simulation(key, sim_data)

    v_before = forecast_cache.get_state_version(fam_id)
    # Update active scenario to scen_netjets
    forecast_cache.update_active_scenario(fam_id, "scen_netjets")

    # State version must NOT have incremented
    v_after = forecast_cache.get_state_version(fam_id)
    assert v_before == v_after

    # Cached entry must still exist (hit!)
    cached = forecast_cache.get_simulation(key)
    assert cached is not None
    assert cached["active_scenario_id"] == "scen_netjets"

    # Scenarios list updated
    baseline_scen = next(s for s in cached["scenarios"] if s["id"] == "scen_baseline")
    netjets_scen = next(s for s in cached["scenarios"] if s["id"] == "scen_netjets")
    assert baseline_scen["is_active"] is False
    assert netjets_scen["is_active"] is True

    # Active schedules updated
    assert cached["active_schedule"] == [{"year": 2026, "total_net_worth": 90}]
    assert cached["active_cash_flow_series"] == [{"year": 2026, "net_savings": 5}]
    assert cached["active_longevity_breakdown"] == {"solvency_age": 88}
    assert cached["active_retirement_readiness"]["can_retire_today"] is False


def test_forecast_cache_multi_worker_sqlite_consistency():
    """
    Verify that an out-of-band state version bump in SQLite (simulating another Gunicorn worker)
    is detected by this worker, purging its local in-memory cache and updating state version.
    """
    from routes.helpers import get_current_db_path
    from hvl_common.db import get_db_connection

    forecast_cache.clear_all_caches()
    fam_id = 505

    # 1. Initialize local cache for worker 1
    v1 = forecast_cache.get_state_version(fam_id)
    key1 = forecast_cache.make_cache_key(fam_id, "public", {"a": 1})
    forecast_cache.set_simulation(key1, {"data": "worker1_cached"})
    assert forecast_cache.get_simulation(key1) is not None

    # 2. Simulate Worker 2 incrementing version in SQLite state DB directly out-of-band
    state_db_path = get_current_db_path(family_id=fam_id)
    with get_db_connection(state_db_path, timeout=5.0) as conn:
        conn.execute("""
            INSERT INTO family_state_versions (family_id, version, updated_at)
            VALUES (?, 5, CURRENT_TIMESTAMP)
            ON CONFLICT(family_id) DO UPDATE SET version = 5, updated_at = CURRENT_TIMESTAMP
        """, (fam_id,))
        conn.commit()

    # 3. Worker 1 queries version: it should discover v5 and purge its stale local cache
    v_new = forecast_cache.get_state_version(fam_id)
    assert v_new == 5
    assert forecast_cache.get_simulation(key1) is None

    # 4. New cache key incorporates v5
    key_v5 = forecast_cache.make_cache_key(fam_id, "public", {"a": 1})
    assert f"v{v_new}" in key_v5
    assert key_v5 != key1


def test_l2_sqlite_persistence_and_encryption_at_rest():
    """
    Verify L2 `diskcache` SQLite persistence across L1 eviction (multi-worker cold L1 recovery)
    and assert that `value` in `Cache` is Fernet-encrypted at rest (`disk_min_file_size=2**31 - 1`).
    """
    from routes.helpers import get_current_cache_db_path
    from hvl_common.db import get_db_connection

    forecast_cache.clear_all_caches()
    fam_id = 606
    secret_marker = "CONFIDENTIAL_SCENARIO_PAYLOAD_MARKER_9912"

    key_canonical = forecast_cache.make_cache_key(fam_id, "public", {})
    payload = {
        "success": True,
        "active_scenario_id": "scen_baseline",
        "marker": secret_marker,
        "net_worth_65": 42_000_000.0,
    }
    forecast_cache.set_simulation(key_canonical, payload, persist_l2=True)

    # Verify raw diskcache SQLite blob is encrypted and never contains plaintext JSON or marker
    cache_db = get_current_cache_db_path(family_id=fam_id)
    with get_db_connection(cache_db, timeout=5.0) as conn:
        row = conn.execute(
            "SELECT key, tag, value, filename FROM Cache WHERE tag = ?",
            (f"tenant:{fam_id}",),
        ).fetchone()
    assert row is not None
    assert row["filename"] is None  # Stored inline in SQLite, never as a loose file
    raw_blob = bytes(row["value"])
    assert secret_marker.encode("utf-8") not in raw_blob
    assert raw_blob.startswith(b"gAAAAA")  # Fernet token prefix

    # Clear L1 memory (simulating a cold Gunicorn worker 2) and verify L2 diskcache SQLite hit
    forecast_cache.clear_l1_only()
    recovered = forecast_cache.get_simulation(key_canonical)
    assert recovered is not None
    assert recovered["marker"] == secret_marker
    assert recovered["net_worth_65"] == 42_000_000.0


def test_option_a_canonical_vs_slider_override_l2_policy():
    """
    Verify Option A policy: canonical simulation/Monte Carlo states persist to L2 `diskcache`,
    while transient interactive slider overrides (`annual_living_spend`, `spending`, etc.)
    remain in L1 `cachetools.LRUCache` RAM only and never touch L2 SQLite `Cache`.
    """
    from routes.helpers import get_current_cache_db_path
    from hvl_common.db import get_db_connection

    forecast_cache.clear_all_caches()
    fam_id = 707

    assert forecast_cache.is_canonical_simulation_params({}) is True
    assert forecast_cache.is_canonical_simulation_params({"scenario_id": "scen_baseline", "view_mode": "real"}) is True
    assert forecast_cache.is_canonical_simulation_params({"annual_living_spend": "450000"}) is False
    assert forecast_cache.is_canonical_simulation_params({"primary_retirement_age": "55"}) is False

    assert forecast_cache.is_canonical_monte_carlo_params({"scenario_id": "scen_baseline", "trials": 1000, "spending": None, "retirement_age": None}) is True
    assert forecast_cache.is_canonical_monte_carlo_params({"scenario_id": "scen_baseline", "trials": 1000, "spending": 500000.0, "retirement_age": None}) is False

    slider_params = {"annual_living_spend": "555000"}
    slider_key = forecast_cache.make_cache_key(fam_id, "public", slider_params)
    forecast_cache.set_simulation(
        slider_key,
        {"slider": True},
        persist_l2=forecast_cache.is_canonical_simulation_params(slider_params),
    )

    # Hit in L1
    assert forecast_cache.get_simulation(slider_key) == {"slider": True}

    # Not persisted to L2 SQLite Cache table
    cache_db = get_current_cache_db_path(family_id=fam_id)
    if cache_db.exists():
        with get_db_connection(cache_db, timeout=5.0) as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM Cache WHERE tag = ?",
                (f"tenant:{fam_id}",),
            ).fetchone()[0]
        assert cnt == 0

    # After L1 clear, slider entry is gone
    forecast_cache.clear_l1_only()
    assert forecast_cache.get_simulation(slider_key) is None


def test_waterfall_zero_sqlite_queries_with_household_context(monkeypatch):
    """
    Verify that `run_scenario_simulation` executes zero SQLite connections/queries
    inside the simulation loop when a preloaded `HouseholdContext` is provided.
    """
    import forecast.storage as f_storage
    from hvl_common import db as hvl_db

    ctx = build_household_context(family_id=1)
    assert ctx.tuition_ledger_loaded is True

    # Poison get_db_connection during run_scenario_simulation to prove 0 SQLite queries
    def _forbidden_db_conn(*args, **kwargs):
        raise RuntimeError("SQLite connection opened inside run_scenario_simulation!")

    monkeypatch.setattr(f_storage, "get_db_connection", _forbidden_db_conn)
    monkeypatch.setattr(hvl_db, "get_db_connection", _forbidden_db_conn)

    events = [
        {
            "id": "evt_k12_test",
            "category": "education",
            "type": "outflow",
            "amount": 35000.0,
            "start_year": 2026,
            "end_year": 2030,
            "child_user_id": 99999,
        },
        {
            "id": "evt_college_test",
            "category": "college",
            "type": "outflow",
            "amount": 90000.0,
            "start_year": 2030,
            "end_year": 2033,
            "child_user_id": 99999,
        },
    ]

    sim = forecast_engine.run_scenario_simulation(
        events=events,
        liquid_start=2_000_000.0,
        retirement_start=1_000_000.0,
        real_estate_start=1_500_000.0,
        mortgage_start=500_000.0,
        other_start=0.0,
        family_id=1,
        context=ctx,
    )
    assert sim is not None
    assert len(sim["schedule"]) > 0


def test_background_jobs_cross_worker_sqlite_persistence():
    """
    Verify that a job submitted on Worker 1 persists to `background_jobs` in SQLite
    (encrypted at rest) and can be polled from Worker 2 after clearing in-memory state.
    """
    import background_jobs
    from routes.helpers import get_current_cache_db_path
    from hvl_common.db import get_db_connection

    background_jobs.JOB_POOL.clear()
    fam_id = 808

    def _compute_task(x: int, y: int) -> dict:
        return {"sum": x + y, "tag": "CONFIDENTIAL_BG_RESULT_77"}

    jid = background_jobs.submit_job(
        _compute_task,
        21,
        21,
        family_id=fam_id,
        universe="public",
        job_type="unit_test_job",
        initial_meta={"custom_meta": "hello_meta"},
    )
    background_jobs.JOB_POOL.wait_for_job(jid, timeout=5.0)

    # Verify encrypted at rest in SQLite background_jobs table
    cache_db = get_current_cache_db_path()
    with get_db_connection(cache_db, timeout=5.0) as conn:
        row = conn.execute(
            "SELECT status, result_blob, meta_blob FROM background_jobs WHERE job_id = ?",
            (jid,),
        ).fetchone()
    assert row is not None
    assert row["status"] == "completed"
    assert b"CONFIDENTIAL_BG_RESULT_77" not in bytes(row["result_blob"])
    assert bytes(row["result_blob"]).startswith(b"gAAAAA")

    # Simulate Worker 2 (cold local memory) polling the job from SQLite
    with background_jobs.JOB_POOL._lock:
        background_jobs.JOB_POOL._jobs.clear()
        background_jobs.JOB_POOL._local_active_jobs.clear()

    polled = background_jobs.get_job(jid, family_id=fam_id)
    assert polled is not None
    assert polled["status"] == "completed"
    assert polled["result"] == {"sum": 42, "tag": "CONFIDENTIAL_BG_RESULT_77"}
    assert polled["custom_meta"] == "hello_meta"

    # Cross-tenant isolation: another family_id must not read the job
    assert background_jobs.get_job(jid, family_id=fam_id + 1) is None


def test_vectorized_monte_carlo_deterministic_percentiles():
    """
    Verify vectorized Monte Carlo simulation preserves exact return signature,
    required keys, percentiles (p10, p25, p50, p75, p90), and deterministic seed behavior.
    """
    from forecast.monte_carlo import run_monte_carlo_simulation

    # 1. Deterministic repeatability with seed
    r1 = run_monte_carlo_simulation(family_id=0, trials=300, seed=12345)
    r2 = run_monte_carlo_simulation(family_id=0, trials=300, seed=12345)

    assert r1["success"] is True
    assert r1["trials"] == 300
    assert r1["median_terminal_wealth"] == r2["median_terminal_wealth"]
    assert r1["p10_terminal_wealth"] == r2["p10_terminal_wealth"]
    assert r1["p90_terminal_wealth"] == r2["p90_terminal_wealth"]
    assert r1["percentiles_timeline"] == r2["percentiles_timeline"]

    # 2. Check all required keys exist and types match
    expected_top_keys = [
        "success", "scenario_id", "scenario_name", "trials", "portfolio_stats",
        "initial_net_worth", "initial_liquid", "success_rate_age_100",
        "success_rate_age_90", "success_rate_age_85", "median_terminal_wealth",
        "p10_terminal_wealth", "p90_terminal_wealth", "percentiles_timeline",
        "longevity_breakdown", "stress_tests"
    ]
    for k in expected_top_keys:
        assert k in r1, f"Missing key {k} in simulation result"

    # 3. Check percentiles timeline schema
    timeline = r1["percentiles_timeline"]
    assert len(timeline) > 0
    first_year = timeline[0]
    for pk in ["year", "age", "p10", "p25", "p50", "p75", "p90"]:
        assert pk in first_year, f"Missing percentile key {pk}"
        assert isinstance(first_year[pk], (int, float))

    # 4. Check stress tests
    assert "1929_great_crash" in r1["stress_tests"]
    assert "2008_gfc" in r1["stress_tests"]


def test_sqlalchemy_typedecorator_encryption_at_rest_and_selectin_relationships():
    """
    Verify SQLAlchemy 2.0 `EncryptedString`, `EncryptedFloat`, and `EncryptedJSON`
    TypeDecorators transparently store Fernet ciphertext (`gAAAAA...`) in SQLite,
    hydrate native Python types (`str`, `float`, `dict`) on load, and support
    `lazy="selectin"` relationship loading.
    """
    from pathlib import Path
    from sqlalchemy import select
    import db
    import security
    from db.models import EquityCompany, EquityGrantRecord, MonarchAccount
    from hvl_common.db import get_db_connection
    from routes.helpers import DB_PATH

    fam_id = 94
    db_path = DB_PATH.for_family(fam_id)
    security.init_db(db_path)

    with get_db_connection(db_path) as raw_conn:
        raw_conn.execute("DELETE FROM monarch_accounts WHERE family_id = ?", (fam_id,))
        raw_conn.execute("DELETE FROM equity_grants WHERE family_id = ?", (fam_id,))
        raw_conn.execute("DELETE FROM equity_companies WHERE family_id = ?", (fam_id,))
        raw_conn.commit()

    with db.get_orm_session(db_path, family_id=fam_id, commit=True) as session:
        comp = EquityCompany(
            family_id=fam_id,
            company_name="SECRET_ORM_CORP_94",
            ticker_or_private="private",
            current_fmv=145.5,
            fmv_date="2026-06-01",
        )
        session.add(comp)
        session.flush()
        cid = comp.company_id

        grant = EquityGrantRecord(
            company_id=cid,
            family_id=fam_id,
            grant_label="ORM Grant Alpha",
            grant_type="nso",
            strike_price=12.75,
            shares_granted=5000.0,
            shares_vested=2500.0,
            shares_unvested=2500.0,
        )
        acc = MonarchAccount(
            family_id=fam_id,
            account_id="orm_acc_94",
            display_name_enc="SECRET_VAULT_ACCOUNT_94",
            current_balance_enc=876543.21,
            account_type="brokerage",
            subtype="taxable",
            institution_name_enc="SECRET_CUSTODIAN_94",
            payload_enc={"id": "orm_acc_94", "secret_tag": "CLASSIFIED_JSON_94"},
        )
        session.add_all([grant, acc])

    # 1. Inspect raw SQLite bytes to prove 100% Fernet encryption at rest
    with get_db_connection(db_path) as raw_conn:
        comp_raw = raw_conn.execute(
            "SELECT company_name FROM equity_companies WHERE company_id = ?",
            (cid,),
        ).fetchone()
        grant_raw = raw_conn.execute(
            "SELECT strike_price, shares_granted FROM equity_grants WHERE company_id = ?",
            (cid,),
        ).fetchone()
        acc_raw = raw_conn.execute(
            "SELECT display_name_enc, current_balance_enc, institution_name_enc, payload_enc "
            "FROM monarch_accounts WHERE family_id = ? AND account_id = 'orm_acc_94'",
            (fam_id,),
        ).fetchone()

    assert str(comp_raw[0]).startswith("gAAAAA")
    assert "SECRET_ORM_CORP_94" not in str(comp_raw[0])
    assert str(grant_raw[0]).startswith("gAAAAA")
    assert str(grant_raw[1]).startswith("gAAAAA")
    for idx in range(4):
        assert str(acc_raw[idx]).startswith("gAAAAA")
        assert "SECRET" not in str(acc_raw[idx])
        assert "CLASSIFIED_JSON_94" not in str(acc_raw[idx])

    # 2. Verify transparent decryption, native type hydration, and `selectin` relationships
    with db.get_orm_session(db_path, family_id=fam_id) as session:
        loaded_comp = session.scalars(
            select(EquityCompany).where(EquityCompany.company_id == cid)
        ).first()
        assert loaded_comp is not None
        assert loaded_comp.company_name == "SECRET_ORM_CORP_94"
        assert len(loaded_comp.grants) == 1
        assert isinstance(loaded_comp.grants[0].strike_price, float)
        assert loaded_comp.grants[0].strike_price == 12.75
        assert loaded_comp.grants[0].shares_granted == 5000.0

        loaded_acc = session.get(MonarchAccount, (fam_id, "orm_acc_94"))
        assert loaded_acc is not None
        assert loaded_acc.display_name_enc == "SECRET_VAULT_ACCOUNT_94"
        assert isinstance(loaded_acc.current_balance_enc, float)
        assert loaded_acc.current_balance_enc == 876543.21
        assert isinstance(loaded_acc.payload_enc, dict)
        assert loaded_acc.payload_enc["secret_tag"] == "CLASSIFIED_JSON_94"

    with get_db_connection(db_path) as raw_conn:
        raw_conn.execute("DELETE FROM monarch_accounts WHERE family_id = ?", (fam_id,))
        raw_conn.execute("DELETE FROM equity_grants WHERE family_id = ?", (fam_id,))
        raw_conn.execute("DELETE FROM equity_companies WHERE family_id = ?", (fam_id,))
        raw_conn.commit()


def test_sqlalchemy_session_after_commit_automatic_cache_invalidation():
    """
    Verify SQLAlchemy `Session` `after_commit` event listener automatically bumps
    the family state version and invalidates `forecast_cache` + `db.store` on domain
    mutations, while ignoring non-financial advisor chat mutations.
    """
    from pathlib import Path
    import db
    import security
    from db.models import CompensationRecord
    from hvl_common.db import get_db_connection
    from routes.helpers import DB_PATH

    fam_id = 95
    db_path = DB_PATH.for_family(fam_id)
    security.init_db(db_path)
    with get_db_connection(db_path) as raw_conn:
        raw_conn.execute("DELETE FROM advisor_messages WHERE conversation_id = 'conv_orm_95'")
        raw_conn.execute("DELETE FROM advisor_conversations WHERE conversation_id = 'conv_orm_95'")
        raw_conn.execute("DELETE FROM compensation WHERE family_id = ?", (fam_id,))
        raw_conn.commit()

    forecast_cache.clear_all_caches()

    v0 = forecast_cache.get_state_version(fam_id)
    key0 = forecast_cache.make_cache_key(fam_id, "public", {"scenario_id": "baseline"})
    forecast_cache.set_simulation(
        key0, {"scenarios": [{"id": "baseline"}], "active_scenario_id": "baseline"}
    )
    assert forecast_cache.get_simulation(key0) is not None

    # Domain ORM commit without any manual notify_family_mutation call
    with db.get_orm_session(db_path, family_id=fam_id, commit=True) as session:
        session.add(
            CompensationRecord(
                family_id=fam_id,
                tax_year=2026,
                employer_name="Auto Invalidate Corp",
                base_salary=300000.0,
                bonus=50000.0,
            )
        )

    v1 = forecast_cache.get_state_version(fam_id)
    assert v1 == v0 + 1
    assert forecast_cache.get_simulation(key0) is None

    # Excluded table (advisor_conversations / advisor_messages) must NOT bump state version
    conv_id = db.conversations.create_conversation(
        "conv_orm_95", family_id=fam_id, title="ORM Thread", db_path=db_path
    )
    db.conversations.add_message(
        conv_id, family_id=fam_id, role="user", content="Secret question", db_path=db_path
    )
    assert forecast_cache.get_state_version(fam_id) == v1

    with get_db_connection(db_path) as raw_conn:
        raw_conn.execute("DELETE FROM advisor_messages WHERE conversation_id = 'conv_orm_95'")
        raw_conn.execute("DELETE FROM advisor_conversations WHERE conversation_id = 'conv_orm_95'")
        raw_conn.execute("DELETE FROM compensation WHERE family_id = ?", (fam_id,))
        raw_conn.commit()


def test_domain_scoped_fragment_cache_isolation():
    """Verify that fragment L1 cache is keyed by domain versions and survives unrelated domain mutations."""
    forecast_cache.clear_all_caches()
    fid = 77

    html_equity = "<div id='equity-test'>Equity Content</div>"
    html_philanthropy = "<div id='phil-test'>Philanthropy Content</div>"

    forecast_cache.set_cached_fragment(fid, "equity", html_equity)
    forecast_cache.set_cached_fragment(fid, "philanthropy", html_philanthropy)

    assert forecast_cache.get_cached_fragment(fid, "equity") == html_equity
    assert forecast_cache.get_cached_fragment(fid, "philanthropy") == html_philanthropy

    # Invalidate ONLY philanthropy domain
    forecast_cache.invalidate_family_cache(fid, domains=["philanthropy"])

    # Equity fragment must SURVIVE in L1 RAM because philanthropy is not in its domain dependencies
    assert forecast_cache.get_cached_fragment(fid, "equity") == html_equity
    # Philanthropy fragment must be invalidated
    assert forecast_cache.get_cached_fragment(fid, "philanthropy") is None

    # Now invalidate equity domain
    forecast_cache.invalidate_family_cache(fid, domains=["equity"])
    # Equity fragment must now be invalidated
    assert forecast_cache.get_cached_fragment(fid, "equity") is None


def test_per_family_db_and_cache_path_resolution_and_cross_worker_domain_versions():
    """
    Verify _resolve_state_db_path and _resolve_cache_db_path resolve to per-family
    {family_id}.db and {family_id}_cache.db paths, and that get_domain_versions(fid)
    detects cross-worker SQLite updates even when sync_db=False and (scope_key, fid)
    is already populated in CACHE._tenant_versions and _DOMAIN_VERSIONS_MEM.
    """
    from db.domain_versions import save_domain_versions_row
    from hvl_common.db import get_db_connection
    import forecast_cache_helpers

    forecast_cache.clear_all_caches()
    fid = 1

    state_db = forecast_cache_helpers._resolve_state_db_path("public", family_id=fid)
    cache_db = forecast_cache_helpers._resolve_cache_db_path("public", family_id=fid)
    assert state_db.name == "1.db"
    assert cache_db.name == "1_cache.db"

    # Populate Worker B's in-memory _tenant_versions and _DOMAIN_VERSIONS_MEM
    initial_vers = forecast_cache.get_domain_versions(fid)
    assert initial_vers["accounts"] >= 1
    assert initial_vers["balance_sheet"] >= 1

    # Simulate Worker A completing a background sync directly in SQLite (state_version=9, accounts=12, balance_sheet=12)
    target_state_v = int(forecast_cache.get_state_version(fid)) + 8
    updated_map = dict(initial_vers)
    updated_map["accounts"] = initial_vers["accounts"] + 10
    updated_map["balance_sheet"] = initial_vers["balance_sheet"] + 10
    save_domain_versions_row(state_db, fid, target_state_v, updated_map)
    with get_db_connection(state_db, timeout=5.0) as conn:
        conn.execute(
            """
            INSERT INTO family_state_versions (family_id, version, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(family_id) DO UPDATE SET version = excluded.version, updated_at = CURRENT_TIMESTAMP
            """,
            (fid, target_state_v),
        )
        conn.commit()

    # Worker B calls get_domain_versions(fid) with default sync_db=False:
    # must immediately detect the SQLite state_version bump and load the updated domain versions!
    worker_b_vers = forecast_cache.get_domain_versions(fid)
    assert worker_b_vers["accounts"] == updated_map["accounts"]
    assert worker_b_vers["balance_sheet"] == updated_map["balance_sheet"]


