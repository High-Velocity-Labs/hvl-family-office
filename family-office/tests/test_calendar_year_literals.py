"""
F-ENG-12 (no hard-coded calendar year acts as "now") and F-ENG-14 (estate and advisor amounts
state their dollars). Date-sensitive tests run as if it were 1 March 2027.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from forecast import presets
from forecast.dollar_basis import dollar_basis_for_view, dollar_basis_label
from services import estate_engine, statutory_limits

REPO = Path(__file__).resolve().parent.parent


def _fixed_today(monkeypatch, module, year, month=3, day=1):
    class _Fixed(date):
        @classmethod
        def today(cls):
            return date(year, month, day)

    monkeypatch.setattr(module, "date", _Fixed)


def _catalog(as_of_year=None):
    return presets.get_default_event_catalog(family_id=0, children_k12=[], children_edu=[], as_of_year=as_of_year)


YEAR_FIELDS = ("year", "end_year", "harvest_year", "benefit_start_year", "benefit_end_year")


def _year_fields(event):
    return {k: v for k, v in event.items() if k in YEAR_FIELDS}


# --- presets -------------------------------------------------------------------------------

def test_catalog_in_2027_has_no_event_before_2027(monkeypatch):
    _fixed_today(monkeypatch, presets, 2027)
    catalog = _catalog()
    assert catalog
    for ev in catalog:
        for field, value in _year_fields(ev).items():
            assert value >= 2027, f"{ev['id']}.{field}={value} is before the plan's first year"
    assert min(ev["year"] for ev in catalog) == 2027


def test_catalog_built_in_2027_has_the_same_relative_years_as_2026():
    c26, c27 = _catalog(2026), _catalog(2027)
    assert [e["id"] for e in c26] == [e["id"] for e in c27]
    for a, b in zip(c26, c27):
        assert {k: v + 1 for k, v in _year_fields(a).items()} == _year_fields(b), a["id"]


def test_catalog_descriptions_follow_the_shifted_years():
    ev = next(e for e in _catalog(2027) if "harvest_year" in e)
    assert str(ev["harvest_year"]) in ev["description"]
    assert "2035" not in ev["description"]


# --- statutory table -------------------------------------------------------------------------

def test_gift_exclusion_lookups_all_come_from_the_one_table(monkeypatch):
    assert statutory_limits.annual_gift_exclusion(2026) == statutory_limits.ANNUAL_GIFT_EXCLUSION_BY_TAX_YEAR[2026]
    # A year with no published figure uses the latest published one.
    assert statutory_limits.annual_gift_exclusion(2031) == statutory_limits.annual_gift_exclusion(2026)
    monkeypatch.setattr(statutory_limits, "ANNUAL_GIFT_EXCLUSION_BY_TAX_YEAR", {2026: 19_000.0, 2028: 20_000.0})
    assert statutory_limits.annual_gift_exclusion(2027) == 19_000.0
    assert statutory_limits.annual_gift_exclusion(2040) == 20_000.0
    assert statutory_limits.annual_gift_exclusion_couple(2040) == 40_000.0
    assert statutory_limits.section_529_superfund_limit(2040) == 100_000.0


def test_gift_exclusion_consumers_follow_the_table(monkeypatch):
    from app import app

    monkeypatch.setattr(statutory_limits, "ANNUAL_GIFT_EXCLUSION_BY_TAX_YEAR", {2000: 7_000.0})
    superfund = next(e for e in presets.build_standard_milestone_events(2027) if e["id"] == "evt_529_superfund")
    assert superfund["amount"] == 35_000.0
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update({"authenticated": True, "user": "Test User", "user_email": "admin@example.com",
                     "user_family_id": 1, "family_id": 1, "role": "editor", "auth_method": "Google OAuth"})
    data = client.get("/api/gifting").get_json()
    assert data["annual_exclusion_per_donor"] == 7_000.0 and data["annual_exclusion_couple"] == 14_000.0
    for info in data["recipient_limits"].values():
        assert info["limit_from_couple"] == info["num_people"] * 14_000.0


def test_no_gift_exclusion_literal_outside_the_table():
    for rel in ("routes/gifting.py", "db/education_funding.py", "ssr/planning.py",
                "forecast/presets_family_edu.py", "forecast/presets_milestones.py"):
        text = (REPO / rel).read_text()
        assert not re.search(r"\b(19000|38000|190000)(\.0)?\b", text), rel


# --- no "now" literal anywhere -------------------------------------------------------------------

YEAR = re.compile(r"\b(2025|2026|2027|2028|2029)\b")
SCAN_DIRS = ("forecast", "services", "ssr", "routes", "db", "templates", "static/js")

# (path fragment, line fragment): years that are law, tax-table vintages, data keys or illustrative copy.
# A fragment may be "" to allow every year literal in that file.
ALLOWED = (
    ("historical_cohorts", ""),                       # 1928-2025 market-return dataset
    ("forecast/tax_indexing.py", ""),                 # statutory base year of the tax tables
    ("services/tax_engine.py", ""), ("services/tax_calculations.py", ""),   # tax-table vintage, WA 2028 law
    ("services/estate_engine.py", ""),                # OBBBA 2026 exemption, WA law date
    ("services/statutory_limits.py", ""),             # the table keyed by tax year
    ("forecast/waterfall_equity.py", "2028"), ("services/advisor/tools_core.py", "2028"),
    ("services/advisor/tools_scenarios.py", "2026, 2027, 2028"),  # comment giving the offsets' 2026 values
    ("services/advisor/context.py", ""),              # prompt text on enacted law
    ("ssr/overview.py", "2028"), ("ssr/equity.py", "2028"),       # WA millionaire-tax start
    ("", "k12_cap"),                                  # 529 K-12 $20k cap, effective 2026 (law)
    ("ssr/arbitrage_ssr.py", ""),                     # Monarch benchmark keys actual_2025 / annualized_2026
    ("forecast/presets.py", "2025"), ("forecast/presets.py", "2026"),  # labels of those same benchmark keys
    ("forecast/storage.py", "2018-2025"), ("forecast/storage_education.py", "2026-2027"),
    ("routes/education.py", "2026-2027"),             # input-format example
    ("templates/components/estate.html", "2026 Law"),
    ("templates/components/pillars_estate_tax_phil_gift_features.html", "2025"),
    ("templates/components/equity.html", "2028"),
    ("templates/playbooks.html", ""), ("templates/projectionlab.html", ""), ("templates/features.html", ""),
    ("templates/components/admin_release_sandboxes.html", ""),    # sandbox demo copy
    ("static/js/features.js", ""), ("ssr/guide_content.py", "2025"), ("static/js/equity_chart.js", ""),
)


def _allowed(rel: str, line: str) -> bool:
    return any((frag in rel) and (sub in line) for frag, sub in ALLOWED)


def test_no_unlisted_calendar_year_literal_in_runtime_code():
    offenders = []
    for d in SCAN_DIRS:
        for path in (REPO / d).rglob("*"):
            if not path.is_file() or path.suffix not in (".py", ".html", ".js") or "dist" in path.parts or "bundle" in path.name:
                continue
            rel = path.relative_to(REPO).as_posix()
            for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                if YEAR.search(line) and "1928" not in line and not _allowed(rel, line):
                    offenders.append(f"{rel}:{n}: {line.strip()[:110]}")
    assert not offenders, "calendar-year literals that may act as 'now':\n" + "\n".join(offenders)


# --- SSR builders and templates read the plan's start year ---------------------------------------------

def test_ssr_builders_use_the_sims_start_year():
    from ssr.plan_year import plan_start_year
    from ssr.scenarios_shelf import build_schedule_and_inspector

    sim = {"start_year": 2027, "active_schedule": [
        {"year": 2026, "total_net_worth": 1_000.0},
        {"year": 2027, "total_net_worth": 9_000_000.0, "age_primary": 50, "age_spouse": 48},
    ], "active_cash_flow_series": [{"year": 2027, "total_inflow": 5.0, "total_outflow": 4.0}]}
    assert plan_start_year(sim) == 2027
    out = build_schedule_and_inspector(sim, {}, "scen_baseline", "A", "B")
    assert "9M" in str(out) or "9.0M" in str(out) or "9,000" in str(out)  # the 2027 row feeds the inspector


def test_templates_show_the_current_year_not_2026(monkeypatch):
    import app as app_module
    import ssr.planning as ssr_planning

    _fixed_today(monkeypatch, app_module, 2027)
    _fixed_today(monkeypatch, ssr_planning, 2027)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess.update({"authenticated": True, "user": "Test User", "user_email": "admin@example.com",
                     "user_family_id": 1, "family_id": 1, "role": "editor", "auth_method": "Google OAuth"})
    for url in ("/fragments/gifting", "/fragments/philanthropy"):
        resp = client.get(url)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-active-year="2027"' in html, url  # the default active year is now, not 2026
        assert "(2026" not in html and "Budget)" not in html.replace("(2027 Budget)", ""), url
    index = client.get("/").get_data(as_text=True)
    assert 'data-current-year="2027"' in index


# --- estate: identical whichever view the plan was saved in -------------------------------------------

def _schedule(view_mode: str, start_year: int = 2026, inflation: float = 0.03):
    rows = []
    for age in range(50, 101):
        i = age - 50
        todays_nw = 10_000_000.0 + 400_000.0 * i
        pi = (1 + inflation) ** i
        nominal = view_mode == "nominal"
        rows.append({
            "year": start_year + i, "age": age, "age_primary": age,
            "total_net_worth": round(todays_nw * (pi if nominal else 1.0), 2),
            "company_equity": 0.0,
            "to_todays_dollars": round(1.0 / pi, 10) if nominal else 1.0,
        })
    return rows


def _estate_profile(monkeypatch, view_mode: str):
    import account_sync
    from forecast import cache as forecast_cache
    from forecast import engine as forecast_engine

    sim = {"success": True, "view_mode": view_mode, "active_schedule": _schedule(view_mode)}
    monkeypatch.setattr(account_sync, "get_financial_snapshot", lambda **kw: {})
    monkeypatch.setattr(forecast_cache, "get_cached_estate", lambda *a, **k: None)
    monkeypatch.setattr(forecast_cache, "set_cached_estate", lambda *a, **k: None)
    monkeypatch.setattr(forecast_cache, "get_simulation", lambda ck: None)
    monkeypatch.setattr(forecast_cache, "set_simulation", lambda ck, res: None)
    monkeypatch.setattr(forecast_engine, "simulate_multi_scenarios", lambda **kw: sim)
    return estate_engine.get_family_estate_profile(family_id=987654)


def test_estate_result_is_identical_in_either_saved_view(monkeypatch):
    real = _estate_profile(monkeypatch, "real")
    nominal = _estate_profile(monkeypatch, "nominal")
    assert real["dollar_basis"] == nominal["dollar_basis"] == "todays_dollars"
    assert real["projections"], "expected age-80/85/90/95 projections"
    assert len(real["projections"]) == len(nominal["projections"])
    for a, b in zip(real["projections"], nominal["projections"]):
        assert a["projected_gross_estate"] == pytest.approx(b["projected_gross_estate"], abs=0.05)
        assert a["total_estate_tax"] == pytest.approx(b["total_estate_tax"], abs=0.05)
        assert a["dollar_basis"] == "todays_dollars"
    assert real["current_net_worth"] == pytest.approx(nominal["current_net_worth"], abs=0.05)
    # The age-95 gross estate is the plan's today's-dollar value, not the inflated nominal figure.
    assert real["projections"][-1]["projected_gross_estate"] == pytest.approx(10_000_000.0 + 400_000.0 * 45, abs=0.05)


# --- advisor: every amount names its dollars ---------------------------------------------------------

def _advisor_run(monkeypatch, view_mode: str):
    from forecast import engine as forecast_engine
    from services.advisor import tools_core

    sim = {
        "success": True, "view_mode": view_mode, "active_scenario_id": "scen_baseline", "active_schedule": _schedule(view_mode),
        "scorecard": [{"id": "scen_baseline", "is_baseline": True, "net_worth_65": 12_000_000.0,
                       "net_worth_85": 20_000_000.0, "net_worth_95": 24_000_000.0}],
    }
    monkeypatch.setattr(tools_core, "_resolve_tool_family_id", lambda fid: fid)
    monkeypatch.setattr(tools_core, "get_cash_flow_summary", lambda family_id=0: {"annual_spending": 300_000.0})
    monkeypatch.setattr(forecast_engine, "simulate_multi_scenarios", lambda **kw: sim)
    monkeypatch.setattr(forecast_engine, "run_monte_carlo_simulation", lambda **kw: {
        "success": True, "overall_success_rate": 91.0, "median_terminal_wealth": 18_000_000.0,
        "percentiles": {"p10": 4_000_000.0}, "dollar_basis": dollar_basis_for_view(view_mode),
    })
    return tools_core.simulate_financial_scenario(family_id=5, custom_spending=350_000.0, trials=100)


@pytest.mark.parametrize("view_mode,label", [("real", "today's dollars"), ("nominal", "future dollars")])
def test_advisor_tool_output_labels_every_amount(monkeypatch, view_mode, label):
    out = _advisor_run(monkeypatch, view_mode)
    assert out["success"] is True
    assert out["dollar_basis_label"] == label
    units = out["units"]
    for key in ("median_terminal_net_worth", "worst_10th_percentile_wealth", "nw_age_65", "nw_age_85", "nw_age_95",
                "baseline_nw_age_65", "baseline_nw_age_95"):
        assert units[key] == label, key
    assert units["simulated_spending"] == "today's dollars"
    money_keys = [k for k in out if k.startswith(("nw_age_", "baseline_nw_age_", "median_terminal", "worst_10th", "simulated_spending", "baseline_annual"))]
    assert set(money_keys) <= set(units)


def test_dollar_basis_names():
    assert dollar_basis_for_view("real") == "todays_dollars"
    assert dollar_basis_for_view("nominal") == "future_dollars"
    assert dollar_basis_label("future_dollars") == "future dollars"
