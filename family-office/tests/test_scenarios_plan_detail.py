"""The forecasting page ships only the selected plan's year-by-year series and loads the rest on demand
(ssr/scenarios_plan_detail.py): another plan's series via /api/scenarios/plan-series and the schedule table rows
via /fragments/scenarios/schedule, both from the forecast the page was rendered from."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl

import pytest

from wsgi import app
from forecast import engine as forecast_engine
from ssr.scenarios_plan_detail import PLAN_SERIES_KEYS, client_scenarios_payload


@pytest.fixture
def auth_client():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["universe"] = "test"
        sess["family_id"] = 1
        sess["user_email"] = "test@example.com"
        sess["role"] = "editor"
        sess["is_demo"] = False
    return client


def _page_data(client, query: str = "") -> dict:
    html = client.get(f"/fragments/scenarios{query}").get_data(as_text=True)
    match = re.search(r'<script id="ssr-scenarios-data" type="application/json">(.*?)</script>', html, re.S)
    assert match, "the forecasting fragment carries its data script"
    return json.loads(match.group(1))


def test_client_payload_keeps_only_the_selected_plans_series():
    sim = {"selected_scenario_id": "a", "other": 1, **{key: {"a": [1], "b": [2]} for key in PLAN_SERIES_KEYS}}
    payload = client_scenarios_payload(sim)
    assert all(payload[key] == {"a": [1]} for key in PLAN_SERIES_KEYS)
    assert payload["other"] == 1
    assert sim["scenario_schedules"] == {"a": [1], "b": [2]}, "the cached forecast itself is left whole"
    assert client_scenarios_payload({}) == {}


def test_the_page_carries_one_plans_series_and_the_rest_load_from_its_cached_forecast(auth_client, monkeypatch):
    data = _page_data(auth_client, "?view_mode=real")
    selected = data["selected_scenario_id"]
    assert all(list(data[key]) == [selected] for key in PLAN_SERIES_KEYS)
    assert dict(parse_qsl(data["plan_detail_query"]))["view_mode"] == "real"
    other = next((s["id"] for s in data["scenarios"] if s["id"] != selected), None)
    if other is None:
        pytest.skip("the seeded household has one plan")

    def no_rerun(*_args, **_kwargs):
        raise AssertionError("the plan series must come from the page's cached forecast")

    monkeypatch.setattr(forecast_engine, "simulate_multi_scenarios", no_rerun)
    res = auth_client.get(f"/api/scenarios/plan-series?{data['plan_detail_query']}&plan_id={other}")
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True and body["plan_id"] == other
    assert body["scenario_schedules"] and body["scenario_cash_flows"]

    rows = auth_client.get(f"/fragments/scenarios/schedule?{data['plan_detail_query']}").get_data(as_text=True)
    assert rows.count("<tr>") == len(data["scenario_schedules"][selected])

    missing = auth_client.get(f"/api/scenarios/plan-series?{data['plan_detail_query']}&plan_id=no_such_plan")
    assert missing.status_code == 404


def test_plan_detail_needs_a_session():
    client = app.test_client()
    assert client.get("/api/scenarios/plan-series?plan_id=scen_baseline").status_code in (302, 401)
    assert client.get("/fragments/scenarios/schedule").status_code in (302, 401)
