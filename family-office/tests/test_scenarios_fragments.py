"""Scenario event wizard and catalog: tables, option lists and cards are server-rendered, not built in the browser."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from flask import render_template

from wsgi import app
from services import scenario_benchmarks, statutory_limits
from services.tax_calculations import state_income_tax_rates
from ssr.scenario_event_catalog import build_event_catalog

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "static/js/scenarios"
CATALOG = [
    {"id": "e_college", "name": "Tuition <b>", "category": "college", "year": 2030, "end_year": 2034, "description": "x"},
    {"id": "e_house", "name": "Buy house", "category": "real_estate", "year": 2028},
    {"id": "e_odd", "name": "Mystery", "category": "zzz_unknown", "year": 2040},
]
PLANS = [{"id": "s1", "name": "Base", "event_ids": ["e_house"]}, {"id": "s2", "name": "Alt", "event_ids": ["e_house"]}]


@pytest.fixture
def auth_client():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(authenticated=True, universe="test", family_id=1, user_email="t@example.com", role="editor",
                    is_demo=False)
    return client


def _catalog(**kw):
    args = dict(events=CATALOG, scenarios=PLANS, query="", category="ALL")
    args.update(kw)
    return build_event_catalog(**args)


def _wizard_html():
    with app.test_request_context("/"):
        return "".join(
            render_template(f"components/scenarios/modals/{name}.html")
            for name in ("event_wizard_steps", "event_wizard_fields")
        )


def test_catalog_filters_by_group_search_and_other():
    assert _catalog()["total"] == 3
    assert [r["id"] for r in _catalog(category="education")["rows"]] == ["e_college"]
    assert [r["id"] for r in _catalog(category="other")["rows"]] == ["e_odd"]
    assert [r["id"] for r in _catalog(category="real_estate", query="house")["rows"]] == ["e_house"]
    assert _catalog(query="college education")["total"] == 1


def test_catalog_rows_carry_plan_usage_and_timing():
    rows = {r["id"]: r for r in _catalog()["rows"]}
    assert (rows["e_house"]["plan_count"], rows["e_house"]["plan_names"]) == (2, "Base, Alt")
    assert rows["e_odd"]["plan_count"] == 0
    assert rows["e_college"]["timing"] == "2030–2034" and rows["e_house"]["timing"] == "2028"


def test_catalog_fragment_escapes_names_and_marks_unused_events(auth_client, monkeypatch):
    from routes.fragments import scenario_event_catalog as route

    monkeypatch.setattr(route, "get_or_compute_scenarios", lambda **_: {"events_catalog": CATALOG, "scenarios": PLANS})
    html = auth_client.get("/fragments/scenario_event_catalog?category=ALL&q=").get_data(as_text=True)
    assert "Tuition &lt;b&gt;" in html and "Tuition <b>" not in html
    assert "Not in any plan" in html and "Active in 2 plans" in html
    assert 'btn-del-event' in html and 'data-id="e_odd"' in html
    empty = auth_client.get("/fragments/scenario_event_catalog?q=nomatchxyz").get_data(as_text=True)
    assert "No catalog events found" in empty


def test_wizard_options_fragment_is_get_only_and_rejects_unknown_kind(auth_client):
    assert auth_client.get("/fragments/scenario_wizard_options?kind=bogus").status_code == 400
    assert auth_client.post("/fragments/scenario_wizard_options?kind=children").status_code == 405
    assert auth_client.get("/fragments/scenario_wizard_options?kind=parents").status_code == 200


def test_wizard_options_fragment_renders_members_by_relationship(auth_client, monkeypatch):
    from routes.fragments import scenario_wizard_options as route

    members = [
        {"user_id": 7, "name": "Kid <1>", "relationship": "child", "birthdate": "2015-04-01"},
        {"user_id": 9, "name": "Grandma", "relationship": "parent"},
    ]
    monkeypatch.setattr(route.security, "get_family_members", lambda *a, **k: members)
    kids = auth_client.get("/fragments/scenario_wizard_options?kind=children").get_data(as_text=True)
    assert '<option value="7">Kid &lt;1&gt; (Born 2015-04-01)</option>' in kids and "Grandma" not in kids
    parents = auth_client.get("/fragments/scenario_wizard_options?kind=parents").get_data(as_text=True)
    assert '<option value="9">Grandma (parent)</option>' in parents


def test_wizard_tiers_come_from_python_constants():
    html = _wizard_html()
    for _, _, cost in scenario_benchmarks.COLLEGE_TIERS + scenario_benchmarks.ELDERCARE_TIERS:
        assert f'data-annual-cost="{cost}"' in html
    for *_, cost, years in scenario_benchmarks.GRAD_PROGRAMS:
        assert f'data-annual-cost="{cost}" data-years="{years}"' in html
    assert re.search(r'<option value="private" data-annual-cost="85000" selected>', html)
    assert re.search(r'<option value="assisted_living" data-annual-cost="90000" selected>', html)


def test_superfund_values_are_the_statutory_amounts():
    per_donor = statutory_limits.section_529_superfund_limit(2026)
    values = [t["value"] for t in scenario_benchmarks.superfund_tiers(2026)]
    assert values == [f"{per_donor * 2:.0f}", f"{per_donor:.0f}", f"{per_donor * 4:.0f}"]
    html = _wizard_html()
    select = re.search(r'<select id="select-superfund-tier".*?</select>', html, re.S).group(0)
    assert all(re.fullmatch(r"\d+|custom", v) for v in re.findall(r'<option value="([^"]+)"', select))


def test_relocation_selects_carry_server_state_rates():
    html = _wizard_html()
    for code, rate in state_income_tax_rates().items():
        assert f'<option value="{code}" data-rate="{rate * 100:.4f}"' in html


def test_roth_presets_and_pe_tvpi_ids_agree_between_template_and_js():
    html = _wizard_html()
    roth = re.search(r'<select id="select-roth-preset".*?</select>', html, re.S).group(0)
    assert set(re.findall(r'<option value="([^"]+)"', roth)) == {p[0] for p in scenario_benchmarks.ROTH_PRESETS}
    assert 'id="input-pe-tvpi"' in html and "input-pe-moic" not in html


def test_scenario_js_holds_no_cost_tables_or_ids_missing_from_templates():
    syncers = (JS / "event_modals_syncers.js").read_text()
    for needle in ("stateRates", "progMap", "auto_bracket_", "fill_12", "'250000'"):
        assert needle not in syncers
    assert not re.search(r"\b(40000|48000|90000|144000)\b", (JS / "event_modals_payload.js").read_text())
    assert "TIER_ANNUAL_COST" not in (JS / "event_modals_save.js").read_text()
    for rel in ("event_modals_render.js", "event_modals_fields.js", "event_modals_presets.js",
                "event_modals_catalog.js", "state_icons.js"):
        assert not re.search(r"\.innerHTML\s*=", (JS / rel).read_text()), rel
