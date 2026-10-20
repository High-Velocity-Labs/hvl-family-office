"""
Tests for background job execution on IRS Transcript / W-2 uploads (/api/transcripts/upload,
/api/transcripts/status/<job_id>), Monarch credential/login sync (/api/settings/monarch_*),
and ProcessPoolExecutor offload for Monte Carlo simulations (forecast/monte_carlo.py).
"""

from __future__ import annotations
import io
import time
import pytest


def _make_sample_pdf_bytes() -> bytes:
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(200, 200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _sample_parsed_w2_payload(year: int = 2027) -> dict:
    return {
        "year": year,
        "doc_type": "w2",
        "w2": {
            "employer": "Apex Cloud Corp",
            "wages_box1": 550000.0,
            "base_salary_and_bonus": 420000.0,
            "nso_exercise_spread_box12_v": 130000.0,
            "federal_tax_withheld_box2": 150000.0,
            "social_security_tax_withheld_box4": 10918.2,
            "medicare_tax_withheld_box6": 7975.0,
            "deferred_compensation_401k_box12_d": 23500.0,
        },
        "totals": {
            "w2_wages": 550000.0,
            "w2_base_salary_and_bonus": 420000.0,
            "nso_exercise_spread": 130000.0,
            "federal_tax_withheld": 150000.0,
            "social_security_withheld": 10918.2,
            "medicare_withheld": 7975.0,
            "401k_deferred_comp": 23500.0,
            "ordinary_dividends": 0.0,
            "qualified_dividends": 0.0,
            "interest_income": 0.0,
            "stock_sales_proceeds": 0.0,
            "stock_sales_basis": 0.0,
            "realized_capital_gains": 0.0,
            "mortgage_interest_paid": 0.0,
            "approx_gross_income": 550000.0,
        },
    }


def test_transcripts_upload_sync_and_async_polling(monkeypatch, tmp_path):
    from app import app
    import ingest_tax_transcripts
    import security

    test_db = tmp_path / "test_async_tax.db"
    test_cache_db = tmp_path / "test_async_tax_cache.db"
    security.init_db(test_db)

    monkeypatch.setattr("routes.helpers.DB_PATH", test_db)
    monkeypatch.setattr("routes.tax.DB_PATH", test_db)
    monkeypatch.setattr("routes.compensation.DB_PATH", test_db)
    monkeypatch.setattr("ingest_tax_transcripts.DB_PATH", test_db)
    monkeypatch.setattr("background_jobs._resolve_job_cache_db_path", lambda universe=None: test_cache_db)
    monkeypatch.setattr("background_jobs._resolve_job_primary_db_path", lambda universe=None: test_db)

    monkeypatch.setattr(
        ingest_tax_transcripts,
        "parse_transcript_pdf",
        lambda *args, **kwargs: _sample_parsed_w2_payload(2027),
    )

    pdf_bytes = _make_sample_pdf_bytes()

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user"] = "testuser"
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["role"] = "editor"
            sess["universe"] = "public"

        # 1. Default in test mode runs synchronously
        resp_sync = client.post(
            "/api/transcripts/upload",
            data={"file": (io.BytesIO(pdf_bytes), "w2_2027.pdf"), "adult": "Primary Taxpayer"},
            content_type="multipart/form-data",
        )
        assert resp_sync.status_code == 200
        sync_json = resp_sync.get_json()
        assert sync_json["success"] is True
        assert sync_json["data"]["year"] == 2027
        assert sync_json["compensation_synced"] is True

        # 2. Explicit async=true queues background job and polls /api/transcripts/status/<job_id>
        monkeypatch.setattr(
            ingest_tax_transcripts,
            "parse_transcript_pdf",
            lambda *args, **kwargs: _sample_parsed_w2_payload(2028),
        )
        resp_async = client.post(
            "/api/transcripts/upload?async=true",
            data={"file": (io.BytesIO(pdf_bytes), "w2_2028.pdf"), "adult": "Primary Taxpayer"},
            content_type="multipart/form-data",
        )
        assert resp_async.status_code == 200
        async_json = resp_async.get_json()
        assert async_json["success"] is True
        assert async_json["status"] == "processing"
        job_id = async_json["job_id"]
        assert job_id

        # Poll until completed
        final_status = None
        for _ in range(50):
            poll_resp = client.get(f"/api/transcripts/status/{job_id}")
            assert poll_resp.status_code == 200
            poll_json = poll_resp.get_json()
            if poll_json.get("status") != "processing":
                final_status = poll_json
                break
            time.sleep(0.02)

        assert final_status is not None
        assert final_status["status"] == "completed"
        assert final_status["success"] is True
        assert final_status["data"]["year"] == 2028
        assert final_status["compensation_synced"] is True

        # 3. Unknown job_id returns 404
        resp_missing = client.get("/api/transcripts/status/nonexistent-job-id")
        assert resp_missing.status_code == 404


def test_settings_monarch_credentials_and_login_async_queueing(monkeypatch, tmp_path):
    from app import app
    import monarch_service
    import security

    test_db = tmp_path / "test_async_settings.db"
    test_cache_db = tmp_path / "test_async_settings_cache.db"
    security.init_db(test_db)

    monkeypatch.setattr("routes.helpers.DB_PATH", test_db)
    monkeypatch.setattr("routes.settings.DB_PATH", test_db)
    monkeypatch.setattr("background_jobs._resolve_job_cache_db_path", lambda universe=None: test_cache_db)
    monkeypatch.setattr("background_jobs._resolve_job_primary_db_path", lambda universe=None: test_db)

    sync_calls = []

    def _fake_trigger_sync(family_id=0):
        sync_calls.append(family_id)
        return {"success": True, "accounts_count": 5, "family_id": family_id}

    monkeypatch.setattr(monarch_service, "trigger_monarch_sync", _fake_trigger_sync)
    monkeypatch.setattr(
        monarch_service,
        "login_monarch",
        lambda email, password, mfa_secret=None, family_id=0: {"success": True, "message": "Logged in"},
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user"] = "testuser"
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["role"] = "editor"
            sess["universe"] = "public"

        # 1. POST /api/settings/monarch_credentials with async=true
        resp_creds = client.post(
            "/api/settings/monarch_credentials",
            json={
                "email": "async@example.com",
                "password": "SecretPassword123!",
                "mfa_secret_key": "JBSWY3DPEHPK3PXP",
                "async": True,
            },
        )
        assert resp_creds.status_code == 200
        creds_json = resp_creds.get_json()
        assert creds_json["success"] is True
        assert creds_json["sync_status"] == "processing"
        job_id = creds_json["sync_job_id"]
        assert job_id

        # Poll /api/sync/status/<job_id>
        completed_sync = None
        for _ in range(50):
            st_resp = client.get(f"/api/sync/status/{job_id}")
            assert st_resp.status_code == 200
            st_json = st_resp.get_json()
            if st_json.get("status") != "processing":
                completed_sync = st_json
                break
            time.sleep(0.02)

        assert completed_sync is not None
        assert completed_sync["status"] == "completed"
        assert completed_sync["accounts_count"] == 5

        # 2. POST /api/settings/monarch_login with async=true
        resp_login = client.post(
            "/api/settings/monarch_login",
            json={
                "email": "async@example.com",
                "password": "SecretPassword123!",
                "async": True,
            },
        )
        assert resp_login.status_code == 200
        login_json = resp_login.get_json()
        assert login_json["success"] is True
        assert login_json["sync_status"] == "processing"
        assert login_json.get("sync_job_id")


def test_monte_carlo_kernel_and_process_pool_offload(monkeypatch):
    from forecast import monte_carlo

    years = [2026 + i for i in range(15)]
    ages = [45 + i for i in range(15)]
    num_years = len(years)
    port_stats = monte_carlo.compute_blended_portfolio_stats(0.60, 0.20, 0.15, 0.05, 0.0, 0.0)
    inflation_rate = 0.025
    mu_real = ((1.0 + port_stats["expected_return"]) / (1.0 + inflation_rate)) - 1.0
    sigma_port = port_stats["volatility"]
    drift = mu_real - 0.5 * (sigma_port ** 2)

    kernel_kwargs = dict(
        trials=400, seed=99, num_years=num_years, years=years, ages_primary=ages,
        initial_liquid=5_000_000.0, initial_re=1_500_000.0, initial_equity=2_000_000.0,
        initial_total_nw=8_500_000.0,
        yearly_net_cf=[100_000.0 if i < 5 else -200_000.0 for i in range(num_years)],
        yearly_re_equity=[1_500_000.0] * num_years,
        yearly_comp_equity=[2_000_000.0 if i < 5 else 0.0 for i in range(num_years)],
        yearly_non_liquid=[3_500_000.0 if i < 5 else 1_500_000.0 for i in range(num_years)],
        mu_real=mu_real, drift=drift, sigma_port=sigma_port, inflation_rate=inflation_rate,
        planned_ret_yr=2031, port_stats=port_stats, active_id="scen_baseline", scenario_name="Baseline Plan",
    )

    # 1. Direct kernel call
    res_direct = monte_carlo._execute_monte_carlo_kernel(**kernel_kwargs)
    assert res_direct["success"] is True
    assert res_direct["trials"] == 400
    assert len(res_direct["percentiles_timeline"]) == num_years
    assert "2008_gfc" in res_direct["stress_tests"]

    # 2. ProcessPoolExecutor offload via run_monte_carlo_simulation with FO_MC_PROCESS_POOL=1
    precomputed_sim = {
        "success": True, "active_scenario_id": "scen_baseline", "inflation_rate": inflation_rate,
        "scenarios": [{"id": "scen_baseline", "name": "Baseline Plan", "weight_us_equity": 0.60, "weight_intl_equity": 0.20, "weight_bonds": 0.15, "weight_cash": 0.05}],
        "scorecard": [{"id": "scen_baseline", "retirement_readiness": {"primary_planned_year": 2031}}],
        "scenario_schedules": {
            "scen_baseline": [
                {"year": years[i], "age_primary": ages[i], "liquid_assets": 5_000_000.0 if i == 0 else 0.0, "retirement_assets": 0.0, "real_estate_net": 1_500_000.0, "company_equity": 2_000_000.0 if i < 5 else 0.0, "net_cash_flow": 100_000.0 if i < 5 else -200_000.0}
                for i in range(num_years)
            ]
        },
    }

    monkeypatch.setenv("FO_MC_PROCESS_POOL", "1")
    try:
        res_pool = monte_carlo.run_monte_carlo_simulation(
            family_id=1,
            scenario_id="scen_baseline",
            trials=400,
            seed=99,
            precomputed_sim=precomputed_sim,
        )
    finally:
        monte_carlo._shutdown_mc_process_pool()

    assert res_pool["success"] is True
    assert res_pool["median_terminal_wealth"] == res_direct["median_terminal_wealth"]
    assert res_pool["p10_terminal_wealth"] == res_direct["p10_terminal_wealth"]
    assert res_pool["p90_terminal_wealth"] == res_direct["p90_terminal_wealth"]
    assert res_pool["percentiles_timeline"] == res_direct["percentiles_timeline"]
    hc = res_pool["historical_cohorts"]
    assert hc["total_cohorts"] == 98
    assert hc["start_year_min"] == 1928
    assert hc["start_year_max"] == 2025
    assert len(hc["percentiles_timeline"]) == num_years
    assert len(hc["worst_cohorts"]) == 6


def test_historical_cohorts_backtest_detects_severe_eras():
    """Verifies that aggressive withdrawal rates flag historical depression/stagflation cohorts (e.g., 1929, 1966)."""
    from forecast.historical_cohorts import run_historical_cohort_backtest

    num_years = 35
    years = [2026 + i for i in range(num_years)]
    ages = [55 + i for i in range(num_years)]
    res = run_historical_cohort_backtest(
        years=years,
        ages_primary=ages,
        initial_liquid=2_000_000.0,
        initial_re=0.0,
        initial_equity=0.0,
        yearly_net_cf=[-115_000.0] * num_years,  # 5.75% initial real withdrawal rate
        yearly_re_equity=[0.0] * num_years,
        yearly_comp_equity=[0.0] * num_years,
        yearly_non_liquid=[0.0] * num_years,
        port_stats={"w_us": 0.60, "w_intl": 0.20, "w_bonds": 0.15, "w_cash": 0.05},
    )
    assert res["total_cohorts"] == 98
    assert 0 < res["survived_cohorts"] < 98
    assert 1929 in res["failed_start_years"]
    assert res["worst_cohorts"][0]["survived"] is False
    assert res["worst_cohorts"][0]["depletion_age"] is not None


def test_spending_guardrails_improve_cohort_and_monte_carlo_survival():
    """Verifies that moderate & aggressive belt-tightening guardrails improve cohort survival & median terminal wealth."""
    from forecast.historical_cohorts import run_historical_cohort_backtest
    from forecast.monte_carlo_kernel import _execute_monte_carlo_kernel

    num_years = 35
    years = [2026 + i for i in range(num_years)]
    ages = [55 + i for i in range(num_years)]
    port_stats = {"w_us": 0.60, "w_intl": 0.20, "w_bonds": 0.15, "w_cash": 0.05}
    base_kwargs = dict(
        years=years,
        ages_primary=ages,
        initial_liquid=1_500_000.0,
        initial_re=0.0,
        initial_equity=0.0,
        yearly_net_cf=[-95_000.0] * num_years,
        yearly_re_equity=[0.0] * num_years,
        yearly_comp_equity=[0.0] * num_years,
        yearly_non_liquid=[0.0] * num_years,
        port_stats=port_stats,
    )

    res_off = run_historical_cohort_backtest(**base_kwargs, spending_guardrail_mode="off")
    res_mod = run_historical_cohort_backtest(**base_kwargs, spending_guardrail_mode="moderate")
    res_agg = run_historical_cohort_backtest(**base_kwargs, spending_guardrail_mode="aggressive")

    assert res_off["spending_guardrail_mode"] == "off"
    assert res_mod["spending_guardrail_mode"] == "moderate"
    assert res_agg["spending_guardrail_mode"] == "aggressive"
    assert res_mod["survived_cohorts"] >= res_off["survived_cohorts"]
    assert res_agg["survived_cohorts"] >= res_mod["survived_cohorts"]
    assert res_mod["median_terminal_wealth"] >= res_off["median_terminal_wealth"]
    assert res_agg["median_terminal_wealth"] >= res_mod["median_terminal_wealth"]

    # Verify kernel Monte Carlo execution with guardrails enabled
    mc_off = _execute_monte_carlo_kernel(
        trials=500, seed=42, num_years=num_years, years=years, ages_primary=ages,
        initial_liquid=1_500_000.0, initial_re=0.0, initial_equity=0.0, initial_total_nw=1_500_000.0,
        yearly_net_cf=[-95_000.0] * num_years, yearly_re_equity=[0.0] * num_years,
        yearly_comp_equity=[0.0] * num_years, yearly_non_liquid=[0.0] * num_years,
        mu_real=0.045, drift=0.038, sigma_port=0.12, inflation_rate=0.028, planned_ret_yr=2026,
        port_stats=port_stats, active_id="scen_baseline", scenario_name="Baseline Plan",
        spending_guardrail_mode="off",
    )
    mc_mod = _execute_monte_carlo_kernel(
        trials=500, seed=42, num_years=num_years, years=years, ages_primary=ages,
        initial_liquid=1_500_000.0, initial_re=0.0, initial_equity=0.0, initial_total_nw=1_500_000.0,
        yearly_net_cf=[-95_000.0] * num_years, yearly_re_equity=[0.0] * num_years,
        yearly_comp_equity=[0.0] * num_years, yearly_non_liquid=[0.0] * num_years,
        mu_real=0.045, drift=0.038, sigma_port=0.12, inflation_rate=0.028, planned_ret_yr=2026,
        port_stats=port_stats, active_id="scen_baseline", scenario_name="Baseline Plan",
        spending_guardrail_mode="moderate",
    )
    assert mc_mod["spending_guardrail_mode"] == "moderate"
    assert mc_mod["median_terminal_wealth"] >= mc_off["median_terminal_wealth"]
    assert mc_mod["success_rate_age_100"] >= mc_off["success_rate_age_100"]

