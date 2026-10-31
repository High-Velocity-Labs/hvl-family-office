"""The request-context accessors live outside routes/ and import standalone; routes.context only re-exports."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NOT_LAYERS = {"routes", "tests", "node_modules", "alembic", "scripts"}


@pytest.mark.parametrize("module", ["equity.simulator", "ssr.dashboard", "services.request_context"])
def test_module_imports_standalone(module):
    r = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]


def test_routes_context_reexports_same_objects():
    from routes import context as rc
    from services import request_context as sc

    for name in ("DB_PATH", "can_mutate", "get_current_family_id", "is_sandbox_session", "set_background_context"):
        assert getattr(rc, name) is getattr(sc, name)


def test_non_route_layers_do_not_import_routes_context():
    offenders = []
    for f in sorted(ROOT.rglob("*.py")):
        rel = f.relative_to(ROOT)
        if rel.parts[0] in NOT_LAYERS or rel.parts[0].startswith(".") or rel.name == "app.py":
            continue
        text = f.read_text()
        if "import routes.context" in text or "from routes.context" in text:
            offenders.append(str(rel))
    assert not offenders, offenders


def test_monte_carlo_requires_sandbox_argument():
    from forecast.monte_carlo import run_monte_carlo_simulation

    with pytest.raises(TypeError):
        run_monte_carlo_simulation(family_id=0, trials=100, precomputed_sim={"success": False})


def test_scenario_service_returns_error_state_on_pool_failure():
    from forecast.monte_carlo import MonteCarloPoolError
    from services import scenario_service

    class Cache:
        def make_cache_key(self, *a, **k):
            return "k"

        def get_monte_carlo(self, key):
            return None

        def get_simulation(self, key):
            return None

        def is_canonical_monte_carlo_params(self, params):
            return False

        def set_monte_carlo(self, *a, **k):
            raise AssertionError("an error state must not be cached")

    class Engine:
        def run_monte_carlo_simulation(self, **kw):
            assert kw["sandbox"] is False
            raise MonteCarloPoolError("timed out")

    res = scenario_service.get_or_compute_monte_carlo(1, "test", {}, engine=Engine(), cache=Cache())
    assert res["success"] is False and res["error_code"] == "monte_carlo_unavailable"
