"""Backend leftovers: plan defaults come from the resolver, schema is alembic-only, no invented figures."""

import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_profile_defaults_resolve_through_effective_plan(tmp_path):
    from forecast.capital_market_assumptions import DEFAULT_RETIREMENT_AGE, DEFAULT_SS_CLAIM_AGE
    from forecast.hierarchy import EffectivePlan
    from forecast.orchestrator_series import resolve_profile_defaults

    empty = resolve_profile_defaults(0, tmp_path / "none.db", [])
    assert isinstance(empty, EffectivePlan)
    assert empty.primary_retirement_age == DEFAULT_RETIREMENT_AGE
    assert empty.primary_ss_claim_age == empty.spouse_ss_claim_age == DEFAULT_SS_CLAIM_AGE

    baseline = {"id": "scen_baseline", "primary_retirement_age": 58, "ss_claim_age": 70, "annual_savings": 0}
    plan = resolve_profile_defaults(0, tmp_path / "none.db", [baseline])
    assert plan.primary_retirement_age == 58
    assert plan.primary_ss_claim_age == plan.spouse_ss_claim_age == 70
    assert plan.annual_savings == 0


def test_waterfall_has_no_ss_claim_age_parameter():
    import inspect
    from forecast.waterfall import run_scenario_simulation

    assert "ss_claim_age" not in inspect.signature(run_scenario_simulation).parameters


def test_monte_carlo_needs_resolved_values_not_defaults():
    from forecast.monte_carlo import run_monte_carlo_simulation

    sim = {
        "success": True, "scenarios": [{"id": "s", "portfolio_weights": {"us_equity": 1.0}}],
        "scorecard": [{"id": "s", "retirement_readiness": {}}],
        "scenario_schedules": {"s": [{"year": 2026, "to_todays_dollars": 1.0, "age_primary": 40}]},
    }
    res = run_monte_carlo_simulation(scenario_id="s", precomputed_sim=sim, sandbox=False)
    assert res["success"] is False


def test_monte_carlo_route_maps_unavailable_to_503(monkeypatch):
    import routes.scenarios as rs

    body = {"success": False, "error_code": "monte_carlo_unavailable", "error": "try again"}
    monkeypatch.setattr(rs, "get_or_compute_monte_carlo", lambda **kw: dict(body))
    from wsgi import app

    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(authenticated=True, user="Test User", user_family_id=1, family_id=1, role="editor")
    resp = client.get("/api/scenarios/monte-carlo")
    assert resp.status_code == 503 and resp.get_json() == body


@pytest.mark.parametrize("table", ["bug_reports", "download_events", "portal_telemetry_events", "family_id_allocator"])
def test_alembic_creates_lazy_tables_in_every_universe_db(tmp_path, table):
    import security

    for name in ("public", "sandbox", "demo"):
        path = tmp_path / name / "global.db"
        security.init_db(path)
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone()


def test_lazy_table_creation_is_gone():
    import db.bugs, db.family_id_allocator, db.models_ops, db.telemetry, db.vault

    assert not hasattr(db.models_ops, "ensure_orm_table_on_conn")
    assert not hasattr(db.bugs, "_ensure_bug_reports_table")
    assert not hasattr(db.telemetry, "_ensure_download_events_table")
    assert not hasattr(db.telemetry, "_ensure_portal_telemetry_table")
    assert not hasattr(db.family_id_allocator, "ensure_family_id_allocator_table")
    assert not hasattr(db.vault, "ensure_init_db_tables")


def test_guide_gifting_text_comes_from_statutory_limits():
    from datetime import date
    from services.statutory_limits import annual_gift_exclusion
    from ssr.guide_content import GUIDE_DATA

    text = str(GUIDE_DATA["section-gifting"]) if "section-gifting" in GUIDE_DATA else str(GUIDE_DATA)
    assert f"${annual_gift_exclusion(date.today().year):,.0f}" in text


def test_no_invented_paycheck_or_placeholder_names():
    for rel in ("services/advisor/tools_tabs.py", "services/advisor/fallback.py", "ssr/compensation_ssr.py"):
        text = (ROOT / rel).read_text()
        assert "remaining_paychecks\", 12" not in text and "remaining_paychecks', 12" not in text, rel
        assert "Primary Earner" not in text, rel
    assert "or 12" not in (ROOT / "templates/components/compensation.html").read_text().split("input-paychecks")[1][:300]
    assert "Benchmark comparison ready" not in (ROOT / "templates/components/equity.html").read_text()
