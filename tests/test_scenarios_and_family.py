"""
Unit Tests for Family Management & Scenario Studio Forecasting Engine
"""

import pytest
from app import app
import security
import forecast_engine
from pathlib import Path

import config
from scripts.seed_demo_families import seed_all_demo_families

TEST_DB = config.get_global_db_path("test")




@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user"] = "Test User"
            sess["user_family_id"] = 1
            sess["family_id"] = 1
            sess["role"] = "editor"
        yield client


def test_family_crud(client):
    # 1. Get family
    res = client.get("/api/family")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "Family" in data["family"]["name"]
    assert len(data["members"]) >= 4

    # 2. Add member
    add_res = client.post("/api/family/members", json={
        "name": "Test Child",
        "email": "testchild@example.com",
        "birthdate": "2015-05-01",
        "relationship": "child",
        "role": "viewer"
    })
    assert add_res.status_code == 200
    new_user_id = add_res.get_json()["user_id"]
    assert new_user_id > 0

    try:
        # 3. Update member
        upd_res = client.put(f"/api/family/members/{new_user_id}", json={
            "name": "Test Child Updated",
            "email": "testchild2@example.com",
            "birthdate": "2015-05-01",
            "relationship": "child",
            "role": "viewer"
        })
        assert upd_res.status_code == 200
    finally:
        # 4. Delete member
        del_res = client.delete(f"/api/family/members/{new_user_id}")
        assert del_res.status_code == 200


def test_scenario_multi_simulation(client):
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(data["scorecard"]) >= 1
    assert len(data["scenario_templates"]) >= 4
    assert len(data["comparison_curves"]) > 0
    assert len(data["events_catalog"]) >= 4

    # Verify Monarch Money past spend benchmarks and living budget presets are derived
    assert "spending_benchmarks" in data
    assert "spending_presets" in data
    assert len(data["spending_presets"]) >= 2
    preset_labels = [p["label"] for p in data["spending_presets"]]
    assert any("Baseline" in lbl for lbl in preset_labels)
    assert any("Target" in lbl or "Actual" in lbl or "Avg" in lbl for lbl in preset_labels)

    # Verify scenario templates contain Monarch-derived budget presets
    budget_tmpls = [t for t in data["scenario_templates"] if "template_budget_" in t.get("id", "")]
    assert len(budget_tmpls) >= 3

    # Verify milestone flags exist
    assert any("Enters College" in m["label"] for m in data["milestones"])
    assert any("Retirement" in m["label"] for m in data["milestones"])


def test_active_scenario_toggle(client):
    res = client.post("/api/scenarios/active", json={"scenario_id": "scen_baseline"})
    assert res.status_code == 200
    assert res.get_json()["active_scenario_id"] == "scen_baseline"


def test_dual_spouse_retirement_timelines(client):
    """Verifies independent primary and spouse retirement milestones and staggered schedules."""
    res = client.get("/api/scenarios?primary_retirement_age=48&spouse_retirement_age=55")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["primary_retirement_age"] == 48
    assert data["spouse_retirement_age"] == 55

    milestones = data["milestones"]
    has_primary_ret = any("Retirement" in m["label"] and "Age 48" in m["label"] for m in milestones)
    has_spouse_ret = any("Retirement" in m["label"] and "Age 55" in m["label"] for m in milestones)
    assert has_primary_ret, "Should contain independent Primary Retirement milestone at age 48"
    assert has_spouse_ret, "Should contain independent Spouse Retirement milestone at age 55"


def test_layered_cash_flow_series(client):
    """Verifies layered cash flow structure (Living, Gifting, Travel Go-Go, Debt Service, Inflows)."""
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    data = res.get_json()
    assert "active_cash_flow_series" in data
    series = data["active_cash_flow_series"]
    assert len(series) > 30

    row = series[0]
    expected_keys = [
        "year", "age_primary", "age_spouse",
        "living_core", "travel_gogo", "gifting",
        "events_outflow", "mortgage_debt_service", "total_outflow",
        "salary_savings", "social_security", "event_inflows",
        "total_inflow", "net_cash_flow"
    ]
    for k in expected_keys:
        assert k in row, f"Missing cash flow key: {k}"

    # Verify math consistency: total_inflow - total_outflow == net_cash_flow
    for r in series[:10]:
        calc_net = round(r["total_inflow"] - r["total_outflow"], 2)
        assert abs(calc_net - r["net_cash_flow"]) <= 0.05


def test_actuarial_longevity_100_percent_stack(client):
    """Verifies that Growing + Preserved + Broke + Deceased sums to exactly 100% across all years."""
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    data = res.get_json()
    assert "active_longevity_breakdown" in data
    longevity = data["active_longevity_breakdown"]
    assert len(longevity) > 30

    for entry in longevity:
        total_prob = round(entry["prob_growing"] + entry["prob_preserved"] + entry["prob_broke"] + entry["prob_deceased"], 1)
        assert abs(total_prob - 100.0) <= 0.5, f"Longevity probabilities must sum to 100% at year {entry['year']}, got {total_prob}%"
        assert entry["prob_deceased"] >= 0.0
        assert entry["prob_deceased"] <= 100.0


def test_arm_refinance_simulation():
    """Verifies that ARM refinance and reset events function correctly in the engine."""
    import forecast_engine
    catalog = forecast_engine.get_default_event_catalog(1)
    arm_evt = next((e for e in catalog if e.get("id") == "evt_refinance_mortgage_arm"), None)
    assert arm_evt is not None
    assert arm_evt["refinance_type"] == "arm"
    assert arm_evt["arm_fixed_years"] == 7
    assert arm_evt["arm_reset_rate"] == 0.055

    # Run scenario simulation directly with ARM event active
    res = forecast_engine.run_scenario_simulation(
        events=[arm_evt],
        liquid_start=5000000.0,
        retirement_start=2000000.0,
        real_estate_start=3000000.0,
        mortgage_start=1500000.0,
        other_start=0.0,
        equity_annual_growth=0.07,
        primary_retirement_age=50,
        spouse_retirement_age=52,
        annual_spending=350000.0,
        family_id=1
    )
    assert res is not None
    assert "schedule" in res
    sched = res["schedule"]
    assert len(sched) > 0

    # Year 2027 should show refinance to 7/1 ARM
    row_2027 = next((r for r in sched if r["year"] == 2027), None)
    assert row_2027 is not None
    events_2027 = " ".join(row_2027.get("events_occurred", []))
    assert "7/1 ARM" in events_2027

    # Year 2034 (2027 + 7) should record ARM rate reset
    row_2034 = next((r for r in sched if r["year"] == 2034), None)
    assert row_2034 is not None
    events_2034 = " ".join(row_2034.get("events_occurred", []))
    assert "ARM rate reset" in events_2034


def test_children_edu_reserves_and_college_catalog():
    """Verifies that children education reserves and college events are dynamically created from DB."""
    children = forecast_engine.load_children_edu_reserves(family_id=1)
    assert len(children) >= 2
    c1 = children[0]
    c2 = children[1]

    assert c1["college_start"] >= 2026
    assert c1["current_529_balance"] > 100000.0

    assert c2["college_start"] >= 2026
    assert c2["current_529_balance"] > 100000.0

    catalog = forecast_engine.get_default_event_catalog(family_id=1)
    catalog_ids = {e["id"] for e in catalog}
    assert f"evt_college_{c1['first_name'].lower()}" in catalog_ids
    assert f"evt_college_{c2['first_name'].lower()}" in catalog_ids

    c1_evt = next(e for e in catalog if e["id"] == f"evt_college_{c1['first_name'].lower()}")
    assert c1_evt["category"] == "college"
    assert c1_evt["year"] == c1["college_start"]
    assert c1_evt["end_year"] == c1["college_start"] + 3
    assert c1_evt["use_529_reserves"] is True


def test_college_529_and_liquid_shortfall_drawdown():
    """Verifies 529 education reserve drawdown and fallback drawdown from liquid accounts."""
    # Test 1: Standard college event ($85k/yr) covered 100% by 529
    events_funded = [
        {
            "id": "evt_college_test",
            "name": "College Education",
            "category": "college",
            "year": 2029,
            "end_year": 2032,
            "annual_amount": 85000.0,
            "use_529_reserves": True,
            "child_user_id": 3,
        }
    ]
    res_funded = forecast_engine.run_scenario_simulation(
        events=events_funded,
        liquid_start=5000000.0,
        retirement_start=1500000.0,
        real_estate_start=3000000.0,
        mortgage_start=1650000.0,
        other_start=100000.0,
        equity_annual_growth=0.08,
        primary_birth_year=1977,
        spouse_birth_year=1979,
        primary_retirement_age=50,
        spouse_retirement_age=52,
        annual_spending=350000.0,
        annual_savings=250000.0,
        inflation_rate=0.025,
        view_mode="nominal",
        family_id=1,
    )
    sched_funded = res_funded["schedule"]
    row_2029 = next(r for r in sched_funded if r["year"] == 2029)
    ev_2029_str = " ".join(row_2029["events_occurred"])
    assert "100% funded by 529" in ev_2029_str
    assert row_2029["education_529_reserves"] > 0

    # Test 2: High tuition ($180k/yr) that exceeds 529 reserves, triggering liquid accounts shortfall drawdown
    events_shortfall = [
        {
            "id": "evt_college_shortfall",
            "name": "College Education (High Tuition)",
            "category": "college",
            "year": 2029,
            "end_year": 2032,
            "annual_amount": 180000.0,
            "use_529_reserves": True,
            "child_user_id": 3,
        }
    ]
    res_shortfall = forecast_engine.run_scenario_simulation(
        events=events_shortfall,
        liquid_start=5000000.0,
        retirement_start=1500000.0,
        real_estate_start=3000000.0,
        mortgage_start=1650000.0,
        other_start=100000.0,
        equity_annual_growth=0.08,
        primary_birth_year=1977,
        spouse_birth_year=1979,
        primary_retirement_age=50,
        spouse_retirement_age=52,
        annual_spending=350000.0,
        annual_savings=250000.0,
        inflation_rate=0.025,
        view_mode="nominal",
        family_id=1,
    )
    sched_shortfall = res_shortfall["schedule"]
    # Check years 2029 to 2032
    college_rows = [r for r in sched_shortfall if r["year"] in (2029, 2030, 2031, 2032)]
    assert len(college_rows) == 4
    # Year 4 should show shortfall or exhaustion drawn from liquid accounts
    last_col_year = college_rows[-1]
    last_ev_str = " ".join(last_col_year["events_occurred"])
    assert "drawn from liquid accounts" in last_ev_str


def test_per_child_k12_tuition_events():
    """Verifies that K-12 education generates an independent event for each child."""
    k12_children = forecast_engine.load_children_k12_tuition(family_id=1)
    assert len(k12_children) >= 2
    for c in k12_children:
        assert c["k12_start"] >= 2026
        assert c["k12_end"] >= c["k12_start"]
        assert c["annual_amount"] > 0

    catalog = forecast_engine.get_default_event_catalog(family_id=1)
    k12_events = [e for e in catalog if e.get("category") == "education" and e["id"].startswith("evt_k12_")]
    assert len(k12_events) >= 2

    scenarios = forecast_engine.get_default_scenarios(family_id=1)
    baseline = next(s for s in scenarios if s["id"] == "scen_baseline")
    for k12_ev in k12_events:
        assert k12_ev["id"] in baseline["event_ids"]


def test_multi_tenant_equity_companies_summary(client):
    """Verifies that equity companies and grant tallies are loaded per family."""
    import equity_engine
    f1_companies = equity_engine.load_equity_companies_summary(family_id=1)
    assert len(f1_companies) >= 1
    v = f1_companies[0]
    assert len(v["company_name"]) > 0
    assert v["current_fmv"] > 0
    assert "NSO" in v["grant_types"]
    assert v["total_vested_options"] > 0

    # An unseeded family without equity has empty list
    NON_EXISTENT_FAMILY_ID = 88888
    empty_companies = equity_engine.load_equity_companies_summary(family_id=NON_EXISTENT_FAMILY_ID)
    assert empty_companies == []

    # API returns equity_companies
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "equity_companies" in data
    assert len(data["equity_companies"][0]["company_name"]) > 0


def test_parent_child_scenario_hierarchy(client):
    """
    Verifies parent-child scenario hierarchy:
    1. Child scenario inherits assumptions and events from parent scenario.
    2. Overriding a parameter on child scenario applies specifically to that child.
    3. Grandchild scenario inherits cascaded events and unoverridden parameters.
    4. Circular hierarchy attempts are rejected with 400.
    5. Deleting a parent re-parents its children gracefully.
    """
    client.delete("/api/scenarios/scen_test_grandchild")
    client.delete("/api/scenarios/scen_test_child")
    try:
        # 1. Create Child Scenario inheriting from Baseline Plan
        res_child = client.post("/api/scenarios", json={
            "id": "scen_test_child",
            "name": "Child Scenario: Pay For College",
            "parent_id": "scen_baseline",
            "color": "#10B981",
            "event_ids": ["evt_lifestyle_netjets"],  # Specific addition
        })
        assert res_child.status_code == 200

        # 2. Create Grandchild Scenario inheriting from Child Scenario
        res_grandchild = client.post("/api/scenarios", json={
            "id": "scen_test_grandchild",
            "name": "Grandchild Scenario: Vacation Property",
            "parent_id": "scen_test_child",
            "color": "#F59E0B",
            "primary_retirement_age": 55,  # Explicit override
            "event_ids": ["evt_lifestyle_netjets", "evt_capital_windfall"],
        })
        assert res_grandchild.status_code == 200

        # 3. Simulate and verify hierarchy resolution
        res_sim = client.get("/api/scenarios")
        assert res_sim.status_code == 200
        data = res_sim.get_json()
        assert data["success"] is True

        scorecard = {s["id"]: s for s in data["scorecard"]}
        assert "scen_test_child" in scorecard
        assert "scen_test_grandchild" in scorecard

        child_scen = scorecard["scen_test_child"]
        grandchild_scen = scorecard["scen_test_grandchild"]

        assert child_scen["parent_id"] == "scen_baseline"
        assert child_scen["depth"] == 1
        assert "evt_lifestyle_netjets" in child_scen["event_ids"]

        assert grandchild_scen["parent_id"] == "scen_test_child"
        assert grandchild_scen["depth"] == 2
        assert grandchild_scen["primary_retirement_age"] == 55
        assert grandchild_scen["overrides"].get("primary_retirement_age") == 55
        # Inherits events from both baseline and parent
        assert "evt_lifestyle_netjets" in grandchild_scen["event_ids"]
        assert "evt_capital_windfall" in grandchild_scen["event_ids"]

        # 4. Circular hierarchy protection
        res_cycle = client.post("/api/scenarios", json={
            "id": "scen_test_child",
            "name": "Child Scenario: Pay For College",
            "parent_id": "scen_test_grandchild",  # Circular: grandchild cannot be parent of child
        })
        assert res_cycle.status_code == 400
        assert "Circular" in res_cycle.get_json()["error"]
    finally:
        # 5. Clean up test scenarios
        del1 = client.delete("/api/scenarios/scen_test_grandchild")
        assert del1.status_code == 200
        del2 = client.delete("/api/scenarios/scen_test_child")
        assert del2.status_code == 200


def test_sanitize_text_helper():
    """Unit test for routes.helpers.sanitize_text."""
    from routes.helpers import sanitize_text

    # Basic stripping
    assert sanitize_text("  hello world  ") == "hello world"
    assert sanitize_text("") == ""
    assert sanitize_text(None, default="default") == "default"

    # Control characters stripped
    assert sanitize_text("Hello\x00\x08World") == "HelloWorld"
    # Single-line strips newlines
    assert sanitize_text("Hello\nWorld\r\n", multiline=False) == "HelloWorld"
    # Multiline preserves newlines
    assert sanitize_text("Hello\nWorld\r\n", multiline=True) == "Hello\nWorld"

    # Length boundary
    with pytest.raises(ValueError, match="exceeds maximum length of 10 characters"):
        sanitize_text("12345678901", max_length=10, field_name="Test Field")

    # Required check
    with pytest.raises(ValueError, match="is required"):
        sanitize_text("   ", required=True, field_name="Required Field")


def test_input_max_length_rejections(client):
    """Verifies that API endpoints cleanly reject oversized input strings with HTTP 400."""
    # 1. Scenario name too long (> 100 chars)
    long_scen_name = "A" * 105
    res = client.post("/api/scenarios", json={
        "id": "scen_oversized",
        "name": long_scen_name,
    })
    assert res.status_code == 400
    assert "exceeds maximum length of 100 characters" in res.get_json()["error"]

    # 2. Scenario description too long (> 500 chars)
    long_desc = "B" * 550
    res = client.post("/api/scenarios", json={
        "id": "scen_oversized_desc",
        "name": "Valid Scenario Name",
        "description": long_desc,
    })
    assert res.status_code == 400
    assert "exceeds maximum length of 500 characters" in res.get_json()["error"]

    # 3. Event name too long (> 100 chars)
    long_evt_name = "E" * 120
    res = client.post("/api/events", json={
        "id": "evt_oversized",
        "name": long_evt_name,
    })
    assert res.status_code == 400
    assert "exceeds maximum length of 100 characters" in res.get_json()["error"]

    # 4. Family name too long (> 100 chars)
    long_fam_name = "F" * 110
    res = client.post("/api/family", json={
        "name": long_fam_name,
    })
    assert res.status_code == 400
    assert "exceeds maximum length of 100 characters" in res.get_json()["error"]

    # 5. Member name too long (> 100 chars)
    long_member_name = "M" * 105
    res = client.post("/api/family/members", json={
        "name": long_member_name,
        "email": "test@example.com",
    })
    assert res.status_code == 400
    assert "exceeds maximum length of 100 characters" in res.get_json()["error"]

    # 6. Valid scenario saves cleanly and strips control characters
    try:
        res_valid = client.post("/api/scenarios", json={
            "id": "scen_sanitized_test",
            "name": "  Sanitized \x00 Plan Name  ",
            "description": "Clean description\nwith multiple lines",
        })
        assert res_valid.status_code == 200

        # Verify saved state has stripped control characters and whitespace
        state = forecast_engine.load_scenario_state(family_id=1)
        saved = next((s for s in state.get("scenarios", []) if s["id"] == "scen_sanitized_test"), None)
        assert saved is not None
        assert saved["name"] == "Sanitized  Plan Name"
        assert "\x00" not in saved["name"]
    finally:
        # Clean up test scenario
        client.delete("/api/scenarios/scen_sanitized_test")


def test_asset_class_growth_rates_and_inheritance(client):
    """Test custom asset class expected returns, scorecard calculation, and parent-child inheritance."""
    client.delete("/api/scenarios/scen_asset_growth_parent")
    try:
        # 1. Create parent plan with customized asset growth rates
        parent_payload = {
            "id": "scen_asset_growth_parent",
            "name": "Aggressive Equities Plan",
            "description": "Plan with aggressive US stock returns and private funds",
            "growth_us_equity": 0.105,
            "growth_intl_equity": 0.080,
            "growth_bonds": 0.040,
            "growth_cash": 0.030,
            "growth_private_investments": 0.130,
            "growth_real_estate": 0.045,
        }
        create_res = client.post("/api/scenarios", json=parent_payload)
        assert create_res.status_code == 200
        assert create_res.get_json()["success"] is True

        # 2. Verify GET /api/scenarios reflects these rates and calculates blended return
        get_res = client.get("/api/scenarios")
        assert get_res.status_code == 200
        data = get_res.get_json()
        assert "asset_weights" in data
        scorecard = data.get("scorecard", [])
        parent_scen = next((s for s in scorecard if s["id"] == "scen_asset_growth_parent"), None)
        assert parent_scen is not None
        assert parent_scen["growth_us_equity"] == 0.105
        assert parent_scen["growth_private_investments"] == 0.130
        assert parent_scen["blended_liquid_growth"] > 0.072  # higher than default 7.2% due to 10.5% US equity

        # 3. Clone to create a child plan inheriting from parent
        clone_res = client.post("/api/scenarios/scen_asset_growth_parent/clone")
        assert clone_res.status_code == 200
        child_id = clone_res.get_json()["scenario"]["id"]

        # 4. Verify child inherited parent's asset growth rates
        get_child = client.get("/api/scenarios")
        child_scen = next((s for s in get_child.get_json()["scorecard"] if s["id"] == child_id), None)
        assert child_scen is not None
        assert child_scen["growth_us_equity"] == 0.105
        assert child_scen["growth_private_investments"] == 0.130
        assert child_scen["blended_liquid_growth"] == parent_scen["blended_liquid_growth"]

        # 5. Override one asset growth rate on child
        upd_res = client.post("/api/scenarios", json={
            "id": child_id,
            "name": child_scen["name"],
            "growth_us_equity": 0.120,
        })
        assert upd_res.status_code == 200

        # 6. Verify override takes effect on child while remaining rates remain inherited
        get_upd = client.get("/api/scenarios")
        updated_child = next((s for s in get_upd.get_json()["scorecard"] if s["id"] == child_id), None)
        assert updated_child["growth_us_equity"] == 0.120
        assert updated_child["growth_private_investments"] == 0.130
        assert updated_child["blended_liquid_growth"] > parent_scen["blended_liquid_growth"]

        # 7. Clean up (deleting parent should cascade delete child)
        del_res = client.delete("/api/scenarios/scen_asset_growth_parent")
        assert del_res.status_code == 200
        assert child_id in del_res.get_json()["deleted_ids"]
    finally:
        client.delete("/api/scenarios/scen_asset_growth_parent")


def test_child_scenario_event_deselection_and_inheritance(client):
    client.delete("/api/scenarios/scen_test_events_parent")
    try:
        # 1. Fetch available events from catalog
        get_scens = client.get("/api/scenarios")
        assert get_scens.status_code == 200
        catalog = get_scens.get_json().get("events_catalog", [])
        assert len(catalog) >= 2
        ev1 = catalog[0]["id"]
        ev2 = catalog[1]["id"]

        # 2. Create parent plan with both events
        create_parent = client.post("/api/scenarios", json={
            "id": "scen_test_events_parent",
            "name": "Events Parent Plan",
            "event_ids": [ev1, ev2],
            "is_baseline": False,
        })
        assert create_parent.status_code == 200

        # 3. Clone to create a child plan
        clone_res = client.post("/api/scenarios/scen_test_events_parent/clone")
        assert clone_res.status_code == 200
        child_id = clone_res.get_json()["scenario"]["id"]

        # 4. Verify child initially inherits both events
        get_data = client.get("/api/scenarios")
        scorecard = get_data.get_json()["scorecard"]
        child_scen = next((s for s in scorecard if s["id"] == child_id), None)
        assert child_scen is not None
        assert set(child_scen["event_ids"]) == {ev1, ev2}
        assert child_scen["excluded_event_ids"] == []

        # 5. Untick/deselect ev2 in the child plan
        untick_res = client.post("/api/scenarios", json={
            "id": child_id,
            "name": child_scen["name"],
            "event_ids": [ev1],
        })
        assert untick_res.status_code == 200

        # 6. Verify unticked event is cleanly excluded in child, but remains in parent
        get_after_untick = client.get("/api/scenarios")
        sc_after = get_after_untick.get_json()["scorecard"]
        parent_scen = next(s for s in sc_after if s["id"] == "scen_test_events_parent")
        child_after = next(s for s in sc_after if s["id"] == child_id)

        assert set(parent_scen["event_ids"]) == {ev1, ev2}
        assert child_after["event_ids"] == [ev1]
        assert ev2 in child_after["excluded_event_ids"]

        # Verify event details flag
        ev_details = child_after.get("events_details", [])
        assert len(ev_details) == 1
        assert ev_details[0]["id"] == ev1
        assert ev_details[0]["is_inherited"] is True

        # 7. Re-tick ev2 in the child plan
        retick_res = client.post("/api/scenarios", json={
            "id": child_id,
            "name": child_scen["name"],
            "event_ids": [ev1, ev2],
        })
        assert retick_res.status_code == 200

        # 8. Verify ev2 is restored to active event_ids and excluded_event_ids is empty
        get_after_retick = client.get("/api/scenarios")
        child_retick = next(s for s in get_after_retick.get_json()["scorecard"] if s["id"] == child_id)
        assert set(child_retick["event_ids"]) == {ev1, ev2}
        assert child_retick["excluded_event_ids"] == []

        # 9. Clean up
        del_res = client.delete("/api/scenarios/scen_test_events_parent")
        assert del_res.status_code == 200
        assert child_id in del_res.get_json()["deleted_ids"]
    finally:
        client.delete("/api/scenarios/scen_test_events_parent")


def test_spending_and_savings_presets(client):
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True

    # 1. Living spend presets
    assert "spending_presets" in data
    spend_presets = data["spending_presets"]
    assert isinstance(spend_presets, list)
    assert len(spend_presets) >= 2
    for p in spend_presets:
        assert "id" in p
        assert "label" in p
        assert "spend" in p
        assert isinstance(p["spend"], (int, float))

    # 2. Annual savings presets
    assert "savings_presets" in data
    savings_presets = data["savings_presets"]
    assert isinstance(savings_presets, list)
    assert len(savings_presets) >= 2
    savings_values = [p["savings"] for p in savings_presets]
    assert 0.0 in savings_values
    assert 70000.0 in savings_values
    for p in savings_presets:
        assert "id" in p
        assert "label" in p
        assert "savings" in p
        assert isinstance(p["savings"], (int, float))


def test_real_estate_arm_and_dynamic_event_wizards(client):
    """Verify Real Estate ARM mortgage simulation, rate reset, and dynamic catalog values."""
    # 1. Test Real Estate 7/1 ARM simulation
    arm_event = {
        "id": "evt_test_re_arm",
        "name": "Purchase Vacation Property (7/1 ARM)",
        "category": "real_estate",
        "event_type": "single_spike",
        "year": 2027,
        "end_year": 2027,
        "purchase_price": 1000000.0,
        "down_payment_pct": 0.20,
        "mortgage_term": "7_1_arm",
        "interest_rate": 0.045,
        "arm_fixed_years": 7,
        "arm_reset_rate": 0.065,
        "annual_ongoing_carrying_cost": 15000.0,
    }
    res = forecast_engine.run_scenario_simulation(
        events=[arm_event],
        liquid_start=5000000.0,
        retirement_start=1000000.0,
        real_estate_start=0.0,
        mortgage_start=0.0,
        other_start=0.0,
        equity_annual_growth=0.05,
        primary_birth_year=1980,
        spouse_birth_year=1982,
        primary_retirement_age=60,
        spouse_retirement_age=60,
        annual_spending=200000.0,
        annual_savings=50000.0,
        inflation_rate=0.025,
        view_mode="nominal",
        family_id=1,
    )
    sched = res["schedule"]
    row_2027 = next(r for r in sched if r["year"] == 2027)
    ev_2027 = " ".join(row_2027.get("events_occurred", []))
    assert "+$1.00M property" in ev_2027

    # Check ARM reset year (2027 + 7 + 1 = 2035)
    row_2035 = next(r for r in sched if r["year"] == 2035)
    ev_2035 = " ".join(row_2035.get("events_occurred", []))
    assert "Real estate ARM reset" in ev_2035

    # 2. Test /api/scenarios exposes current_mortgage_balance and events_catalog
    api_res = client.get("/api/scenarios")
    assert api_res.status_code == 200
    data = api_res.get_json()
    assert "current_mortgage_balance" in data
    assert isinstance(data["current_mortgage_balance"], (int, float))
    assert "events_catalog" in data
    catalog_ids = [e["id"] for e in data["events_catalog"]]
    assert "evt_vacation_home_arm" in catalog_ids


def test_per_holding_equity_growth_presets(client):
    """Verifies that equity_growth_presets can be configured per holding, inherited, and applied."""
    from forecast_engine import resolve_scenario_hierarchy

    # 1. Test hierarchy resolution with holding presets
    parent = {
        "id": "scen_parent",
        "name": "Parent Plan",
        "equity_growth_presets": {"1": "aggressive", "2": "conservative"},
    }
    child = {
        "id": "scen_child",
        "name": "Child Plan",
        "parent_id": "scen_parent",
        "equity_growth_presets": {"2": "moderate"},
    }
    resolved = resolve_scenario_hierarchy([parent, child])
    r_child = next(s for s in resolved if s["id"] == "scen_child")
    # Holding 1 inherited from parent, holding 2 overridden
    assert r_child["equity_growth_presets"]["1"] == "aggressive"
    assert r_child["equity_growth_presets"]["2"] == "moderate"

    # 2. Test saving per-holding presets via API
    res = client.post("/api/scenarios", json={
        "id": "scen_holding_test",
        "name": "Holding Test Plan",
        "equity_growth_presets": {"1": "aggressive", "2": "flat"},
    })
    assert res.status_code == 200
    try:
        # Retrieve and verify
        get_res = client.get("/api/scenarios")
        assert get_res.status_code == 200
        scens = get_res.get_json().get("scenarios", [])
        saved = next((s for s in scens if s["id"] == "scen_holding_test"), None)
        assert saved is not None
        assert saved.get("equity_growth_presets", {}).get("1") == "aggressive"
        assert saved.get("equity_growth_presets", {}).get("2") == "flat"
    finally:
        client.delete("/api/scenarios/scen_holding_test")

    # 3. Test live GET query override with valid scenario_id and with 'null' scenario_id
    import json
    q_presets = json.dumps({"1": "aggressive"})
    live_res = client.get(f"/api/scenarios?scenario_id=scen_baseline&equity_growth_presets={q_presets}")
    assert live_res.status_code == 200
    live_scen = next(s for s in live_res.get_json()["scenarios"] if s["id"] == "scen_baseline")
    assert live_scen.get("equity_growth_presets", {}).get("1") == "aggressive"

    # Query with scenario_id=null should not fail or ignore presets
    null_res = client.get(f"/api/scenarios?scenario_id=null&equity_growth_presets={q_presets}")
    assert null_res.status_code == 200
    null_scen = next(s for s in null_res.get_json()["scenarios"] if s["id"] == "scen_baseline")
    assert null_scen.get("equity_growth_presets", {}).get("1") == "aggressive"


def test_scenarios_monte_carlo_api(client):
    """Verify GET /api/scenarios/monte-carlo returns percentile curves and crisis replays."""
    resp = client.get("/api/scenarios/monte-carlo?trials=300")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["trials"] == 300
    assert "success_rate_age_100" in data
    assert "percentiles_timeline" in data
    assert len(data["percentiles_timeline"]) >= 30
    assert "stress_tests" in data
    assert "1929_great_crash" in data["stress_tests"]
    assert "2008_gfc" in data["stress_tests"]
    assert data["stress_tests"]["2008_gfc"]["survived"] in (True, False)


def test_expanded_scenario_events_and_custom_icons(client):
    """Verifies new life-event simulation mechanics (home sale/downsize, renovation equity, sabbatical income scaling, grad school 529 draw, DAF tax offset) and custom icon SSR/API round-trip."""
    from forecast.waterfall import run_scenario_simulation
    from forecast.presets import get_default_event_catalog

    # 1. Verify default event catalog includes the 10 new presets with semantic evt-* icons
    catalog = get_default_event_catalog(family_id=1)
    cat_by_id = {e["id"]: e for e in catalog}
    expected_new_presets = {
        "evt_buy_primary_home": "evt-real-estate",
        "evt_home_sale_downsize": "evt-home-sale",
        "evt_home_renovation": "evt-renovation",
        "evt_wedding_celebration": "evt-wedding",
        "evt_child_home_downpayment": "evt-house-key",
        "evt_grad_school": "evt-grad-school",
        "evt_sabbatical_break": "evt-briefcase",
        "evt_philanthropy_daf": "evt-philanthropy",
        "evt_vehicle_purchase": "evt-car",
        "evt_rental_income_stream": "evt-rental-income",
    }
    for eid, expected_icon in expected_new_presets.items():
        assert eid in cat_by_id, f"Missing preset {eid} in default event catalog"
        assert cat_by_id[eid].get("icon") == expected_icon

    # 2. Verify simulation engine mechanics for Home Sale/Downsize, Renovation, Sabbatical, Grad School, and DAF
    base_sim = run_scenario_simulation(
        events=[],
        liquid_start=2000000.0,
        retirement_start=1000000.0,
        real_estate_start=2500000.0,
        mortgage_start=500000.0,
        other_start=0.0,
        view_mode="nominal",
        family_id=0,
    )
    sim_with_events = run_scenario_simulation(
        events=[
            {
                "id": "test_renovation",
                "name": "Kitchen & ADU Remodel",
                "category": "home_renovation",
                "year": 2027,
                "end_year": 2027,
                "amount": 300000.0,
                "value_retention_pct": 0.60,
            },
            {
                "id": "test_sabbatical",
                "name": "Career Sabbatical",
                "category": "sabbatical",
                "income_mode": "sabbatical",
                "year": 2028,
                "end_year": 2028,
                "income_multiplier_pct": 0.0,
                "annual_amount": 50000.0,
                "is_outflow": True,
            },
            {
                "id": "test_daf",
                "name": "DAF Front-Load",
                "category": "philanthropy_daf",
                "year": 2029,
                "end_year": 2029,
                "amount": 200000.0,
                "tax_deduction_rate": 0.35,
                "include_tax_offset": True,
            },
            {
                "id": "test_downsize",
                "name": "Downsize Primary Home",
                "category": "real_estate",
                "re_action": "downsize",
                "year": 2030,
                "end_year": 2030,
                "sale_price": 2000000.0,
                "replacement_price": 800000.0,
                "selling_cost_pct": 0.06,
                "mortgage_payoff_amount": 400000.0,
            },
        ],
        liquid_start=2000000.0,
        retirement_start=1000000.0,
        real_estate_start=2500000.0,
        mortgage_start=500000.0,
        other_start=0.0,
        view_mode="nominal",
        family_id=0,
    )

    sched_by_yr = {row["year"]: row for row in sim_with_events["schedule"]}
    base_by_yr = {row["year"]: row for row in base_sim["schedule"]}

    # 2027: Home renovation adds $180k (60% of $300k) to real estate before appreciation
    assert any("remodel outlay" in e for e in sched_by_yr[2027]["events_occurred"])
    assert sched_by_yr[2027]["real_estate_net"] > base_by_yr[2027]["real_estate_net"]

    # 2028: Sabbatical scales earned income to 0%
    assert any("Income at 0%" in e for e in sched_by_yr[2028]["events_occurred"])

    # 2029: DAF front-load logs tax deduction offset ($70k offset on $200k gift -> $130k net outflow)
    assert any("DAF contribution" in e and "tax deduction offset" in e for e in sched_by_yr[2029]["events_occurred"])
    assert sched_by_yr[2029]["yearly_outflow"] - base_by_yr[2029]["yearly_outflow"] == pytest.approx(130000.0, rel=1e-2)

    # 2030: Home sale/downsize injects net proceeds and reduces mortgage balance
    assert any("net proceeds" in e for e in sched_by_yr[2030]["events_occurred"])
    assert sched_by_yr[2030]["mortgage_balance"] < base_by_yr[2030]["mortgage_balance"]

    # 2b. Verify all 6 structural wealth/life events (state_relocation, roth_conversion, superfund_529, pe_capital_call, ltc_insurance, marital_settlement)
    cat_ids = {e["id"]: e for e in get_default_event_catalog(family_id=0)}
    for preset_id, expected_icon in [
        ("evt_state_relocation", "evt-relocation"),
        ("evt_roth_conversion_ladder", "evt-roth-ladder"),
        ("evt_529_superfund", "evt-529-superfund"),
        ("evt_pe_capital_call", "evt-j-curve"),
        ("evt_ltc_hybrid_policy", "evt-ltc-shield"),
        ("evt_marital_settlement", "evt-asset-split"),
    ]:
        assert preset_id in cat_ids, f"Missing preset {preset_id}"
        assert cat_ids[preset_id].get("icon") == expected_icon

    sim_structural = run_scenario_simulation(
        events=[
            {
                "id": "test_reloc",
                "name": "Relocate CA to WA",
                "category": "state_relocation",
                "from_state": "CA",
                "to_state": "WA",
                "tax_rate_savings_pct": 0.105,
                "moving_cost": 40000.0,
                "year": 2027,
                "end_year": 2027,
            },
            {
                "id": "test_roth",
                "name": "Roth Ladder",
                "category": "roth_conversion",
                "annual_amount": 150000.0,
                "conversion_tax_rate": 0.24,
                "year": 2028,
                "end_year": 2029,
            },
            {
                "id": "test_529",
                "name": "529 Superfund",
                "category": "superfund_529",
                "amount": 190000.0,
                "year": 2027,
                "end_year": 2027,
            },
            {
                "id": "test_pe",
                "name": "PE Fund Call & Harvest",
                "category": "pe_capital_call",
                "annual_amount": 100000.0,
                "year": 2027,
                "end_year": 2028,
                "harvest_year": 2031,
                "target_moic": 2.2,
            },
            {
                "id": "test_ltc",
                "name": "LTC Hybrid Shield",
                "category": "ltc_insurance",
                "annual_amount": 20000.0,
                "year": 2027,
                "end_year": 2028,
                "benefit_start_year": 2032,
                "benefit_end_year": 2033,
                "annual_benefit": 120000.0,
            },
            {
                "id": "test_split",
                "name": "Marital Split Stress",
                "category": "marital_settlement",
                "asset_split_pct": 0.50,
                "legal_settlement_cost": 50000.0,
                "annual_alimony": 40000.0,
                "year": 2034,
                "end_year": 2035,
            },
        ],
        liquid_start=3000000.0,
        retirement_start=1500000.0,
        real_estate_start=2000000.0,
        mortgage_start=0.0,
        other_start=0.0,
        view_mode="nominal",
        family_id=0,
    )
    struct_by_yr = {row["year"]: row for row in sim_structural["schedule"]}
    assert any("Relocated tax domicile CA → WA" in e for e in struct_by_yr[2027]["events_occurred"])
    assert any("5-year 529 superfund front-load" in e for e in struct_by_yr[2027]["events_occurred"])
    assert any("LP capital call drawdown" in e for e in struct_by_yr[2027]["events_occurred"])
    assert any("LTC hybrid policy premium" in e for e in struct_by_yr[2027]["events_occurred"])
    assert any("Converted $150k Trad → Roth" in e for e in struct_by_yr[2028]["events_occurred"])
    assert any("PE/VC J-curve distribution" in e for e in struct_by_yr[2031]["events_occurred"])
    assert any("tax-free LTC benefit shield payout" in e for e in struct_by_yr[2032]["events_occurred"])
    assert any("QDRO / marital asset division" in e for e in struct_by_yr[2034]["events_occurred"])
    assert any("spousal support / maintenance" in e for e in struct_by_yr[2035]["events_occurred"])

    # 3. Verify custom event with icon round-trips through POST /api/events and renders in SSR
    res_evt = client.post("/api/events", json={
        "id": "evt_custom_wedding_icon_test",
        "name": "Daughter Wedding Celebration",
        "category": "capital_outflow",
        "outflow_purpose": "wedding",
        "icon": "evt-wedding",
        "year": 2031,
        "end_year": 2031,
        "amount": 150000,
        "annual_amount": 150000,
        "is_outflow": True,
        "description": "Custom wedding event with interlocking rings icon.",
    })
    assert res_evt.status_code == 200
    try:
        scen_res = client.get("/api/scenarios")
        cat_list = scen_res.get_json().get("events_catalog", [])
        saved_evt = next((e for e in cat_list if e["id"] == "evt_custom_wedding_icon_test"), None)
        assert saved_evt is not None
        assert saved_evt.get("icon") == "evt-wedding"
    finally:
        client.delete("/api/events/evt_custom_wedding_icon_test")


def test_childless_household_clean_baseline_scenario():
    """Asserts that households without children or gift recipients have zero phantom education/gifting events in baseline plan."""
    # Test for unseeded/childless household (family_id=88888)
    scenarios = forecast_engine.get_default_scenarios(family_id=88888)
    baseline = next(s for s in scenarios if s.get("id") == "scen_baseline")
    assert baseline["event_ids"] == [], "Baseline plan for childless household must not contain phantom events"
    assert "per-child K-12" not in baseline["description"]
    assert "college 529" not in baseline["description"]
    assert "family gifting" not in baseline["description"]

    # Scenario templates must also omit tuition and gifting fallbacks
    templates = forecast_engine.get_scenario_templates(family_id=88888)
    for t in templates:
        assert "evt_k12_education" not in t.get("event_ids", [])
        assert "evt_college_undergrad" not in t.get("event_ids", [])
        assert "evt_family_gifting" not in t.get("event_ids", [])


def test_zero_hardcoded_financial_fallbacks(client):
    """Verifies that all assumptions, presets, estate distribution, and tax fallbacks cleanly default to 0."""
    from db.schemas import HouseholdProfileSchema
    import estate_engine
    import tax_engine
    from forecast.presets import build_living_budget_presets, build_annual_savings_presets

    # 1. Schema defaults
    schema = HouseholdProfileSchema()
    assert schema.annual_spending == 0.0
    assert schema.annual_savings == 0.0
    assert schema.retirement_age == 65

    # 2. Presets with zero/empty benchmarks
    presets = build_living_budget_presets({})
    assert presets == []
    savings_presets = build_annual_savings_presets(baseline_savings=0.0, annual_compensation=0.0)
    assert any(p["savings"] == 0.0 for p in savings_presets)

    # 3. Estate per-child inheritance is 0 with no kids
    estate_res = estate_engine.get_family_estate_profile(family_id=0)
    assert all(p["per_child_inheritance"] == 0.0 for p in estate_res["projections"])

    # 4. Tax arbitrage defaults
    arb = tax_engine.compare_state_tax_arbitrage(ordinary_spread=0.0)
    assert arb["home_value"] == 0.0
    assert arb["annual_household_spend"] == 0.0

    # 5. Forecast waterfall for household with $140,044.34 liquid cash and $0 mortgage/spending/gifting
    sim = forecast_engine.run_scenario_simulation(
        events=[],
        liquid_start=140044.34,
        retirement_start=0.0,
        real_estate_start=0.0,
        mortgage_start=0.0,
        other_start=0.0,
        annual_spending=0.0,
        annual_savings=0.0,
        family_id=0,
    )
    yr0_sched = sim["schedule"][0]
    yr0_cf = sim["cash_flow_series"][0]
    assert yr0_cf["living_core"] == 0.0
    assert yr0_cf["gifting"] == 0.0
    assert yr0_sched["net_portfolio_draw"] == 0.0
    assert yr0_sched["starting_liquid"] == 140044.34
    assert yr0_sched["liquid_assets"] >= 140044.34


def test_household_customizable_and_reorderable_widgets(client):
    """Verifies per-household widget customization, custom sort order, and reset across Overview and Forecasting."""
    get_res = client.get("/api/widgets/preferences")
    assert get_res.status_code == 200
    prefs = get_res.get_json()
    assert prefs["success"] is True
    assert "ov_kpi_grid" in prefs["overview_widgets"]
    assert "scen_retirement_readiness" in prefs["scenarios_widgets"]

    try:
        # 1. Reorder & customize Overview widgets (place Steady-State Burn FIRST, before KPI Grid)
        custom_ov = ["ov_steady_state_burn", "ov_kpi_grid", "ov_net_worth_chart"]
        post_ov = client.post("/api/widgets/preferences", json={"page": "overview", "active_ids": custom_ov})
        assert post_ov.status_code == 200
        assert post_ov.get_json()["active_ids"] == custom_ov

        ov_frag = client.get("/fragments/overview").get_data(as_text=True)
        ov_grid = ov_frag.partition('id="overview-widgets-grid"')[2]
        pos_burn = ov_grid.find('data-widget-id="ov_steady_state_burn"')
        pos_kpi = ov_grid.find('data-widget-id="ov_kpi_grid"')
        assert pos_burn != -1 and pos_kpi != -1 and pos_burn < pos_kpi
        assert "btn-widget-move" not in ov_frag
        assert "widget-drag-handle" in ov_frag

        # 2. Customize & reorder Forecasting (Scenarios) widgets independently (core widgets cannot be removed)
        custom_scen = ["scen_roth_tax_window", "scen_steady_state_burn"]
        post_scen = client.post("/api/widgets/preferences", json={"page": "scenarios", "active_ids": custom_scen})
        assert post_scen.status_code == 200
        assert post_scen.get_json()["active_ids"] == [
            "scen_chart_networth",
            "scen_retirement_readiness",
            "scen_roth_tax_window",
            "scen_steady_state_burn",
        ]

        scen_frag = client.get("/fragments/scenarios").get_data(as_text=True)
        scen_grid = scen_frag.partition('id="scenarios-widgets-grid"')[2]
        pos_roth = scen_grid.find('data-widget-id="scen_roth_tax_window"')
        pos_sburn = scen_grid.find('data-widget-id="scen_steady_state_burn"')
        assert pos_roth != -1 and pos_sburn != -1 and pos_roth < pos_sburn
        assert 'data-widget-id="scen_chart_networth"' in scen_grid
        assert 'data-widget-id="scen_retirement_readiness"' in scen_grid
        assert "btn-widget-move" not in scen_frag
        assert "widget-drag-handle" in scen_frag

        # 3. Verify GET query-param preview (`?widgets=...`) works for Demo / read-only sessions without POST
        demo_ov = client.get("/fragments/overview?widgets=ov_lifetime_forecast_chart,ov_retirement_readiness,ov_kpi_grid").get_data(as_text=True)
        demo_ov_grid = demo_ov.partition('id="overview-widgets-grid"')[2]
        assert demo_ov_grid.find('data-widget-id="ov_lifetime_forecast_chart"') < demo_ov_grid.find('data-widget-id="ov_kpi_grid"')
        assert "Signature Chart" not in demo_ov
        assert "SIGNATURE FORECAST CHART" not in demo_ov

        # 4. Verify cookie-based widget persistence in Demo mode and full-width Forecasting companion charts
        client.set_cookie("hvl_widgets_overview", "ov_cash_flow_chart,ov_kpi_grid")
        client.set_cookie("hvl_widgets_scenarios", "scen_chart_cashflow,scen_chart_montecarlo")
        cookie_ov = client.get("/fragments/overview?demo=1").get_data(as_text=True)
        cookie_ov_grid = cookie_ov.partition('id="overview-widgets-grid"')[2]
        assert cookie_ov_grid.find('data-widget-id="ov_cash_flow_chart"') < cookie_ov_grid.find('data-widget-id="ov_kpi_grid"')

        cookie_scen = client.get("/fragments/scenarios?demo=1").get_data(as_text=True)
        cookie_scen_grid = cookie_scen.partition('id="scenarios-widgets-grid"')[2]
        assert 'data-widget-id="scen_chart_cashflow"' in cookie_scen_grid
        assert 'data-widget-id="scen_chart_montecarlo"' in cookie_scen_grid
        assert 'data-default-wide="true" style="grid-column: 1 / -1;' in cookie_scen_grid
        assert 'btn-toggle-chart-width' in cookie_scen_grid
    finally:
        client.delete_cookie("hvl_widgets_overview")
        client.delete_cookie("hvl_widgets_scenarios")
        client.post("/api/widgets/preferences", json={"page": "overview", "reset": True})
        client.post("/api/widgets/preferences", json={"page": "scenarios", "reset": True})
