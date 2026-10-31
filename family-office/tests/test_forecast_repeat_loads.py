"""A forecast run reads each household input once, however many plans it simulates, and path lookups do not
redo the one-time data-folder migration (each cost seconds per refresh on the 1-vCPU beta server)."""

from __future__ import annotations

import config
from forecast import orchestrator
from forecast.storage import load_scenario_state
from services import private_markets_service as pms


def test_the_legacy_folder_migration_runs_once_per_data_dir(tmp_path, monkeypatch):
    runs = []
    monkeypatch.setattr(config, "migrate_legacy_data_layout", lambda d: runs.append(d))
    monkeypatch.setattr(config, "_MIGRATED_DATA_DIRS", set())
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path))
    for _ in range(5):
        config.get_data_dir()
        config.get_universe_dir("test")
    assert runs == [tmp_path.resolve()]


def test_lp_call_schedule_is_a_pure_function_of_the_commitments():
    items = [{"unfunded_commitment": 300_000, "expected_call_horizon_years": 3}, {"unfunded_commitment": 0}]
    assert pms.lp_call_schedule(items, start_year=2030) == {2030: 100_000.0, 2031: 100_000.0, 2032: 100_000.0}
    assert pms.lp_call_schedule(items, accelerate=True, start_year=2030) == {2030: 150_000.0, 2031: 150_000.0}
    assert pms.lp_call_schedule([], start_year=2030) == {}


def test_a_forecast_reads_the_lp_commitments_once_for_all_plans(monkeypatch):
    loads = []
    real = orchestrator.get_lp_commitments
    monkeypatch.setattr(orchestrator, "get_lp_commitments", lambda family_id=0: loads.append(family_id) or real(family_id))
    plans = len(load_scenario_state(family_id=1).get("scenarios", []))
    orchestrator.simulate_multi_scenarios(family_id=1)
    assert plans > 1 and loads == [1]
