"""
Tests for Multi-Universe Isolation and Demo Mode.
Validates:
1. /demo establishes an air-gapped guest session in the 'demo' universe.
2. Read operations in demo load 'The Jones Family' data cleanly.
3. Write operations in demo mode are rejected with HTTP 403 Forbidden.
4. Admin users can switch universes via /api/admin/switch_universe.
"""

from __future__ import annotations
import pytest
from app import app
import config
from scripts.seed_demo_families import seed_all_demo_families


@pytest.fixture(scope="module", autouse=True)
def ensure_demo_seeded():
    """Ensure the demo database is seeded with all personas before running demo universe tests."""
    demo_db = config.get_global_db_path("demo")
    seed_all_demo_families(db_path=demo_db, verbose=False)


ensure_beta_seeded = ensure_demo_seeded


def test_demo_route_initialization():
    """Verifies that visiting /demo establishes a read-only viewer session in the demo universe."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/demo", follow_redirects=False)
        assert res.status_code == 302
        assert res.headers["Location"].endswith(("/", "/?demo=1"))

        # Check auth status
        status_res = client.get("/api/auth/status")
        assert status_res.status_code == 200
        data = status_res.get_json()
        assert data["authenticated"] is True
        assert data["role"] == "viewer"
        assert data["universe"] == "demo"
        assert data["is_demo"] is True
        assert data["family_id"] == 1

        # Overview SSR in /demo must omit #overview-setup-checklist
        res_overview = client.get("/fragments/overview")
        assert res_overview.status_code == 200
        assert "overview-setup-checklist" not in res_overview.get_data(as_text=True)



def test_demo_read_access_jones_family():
    """Verifies that the demo session loads The Jones Family data without 500 errors."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.get("/demo")

        # Family Profile
        res_family = client.get("/api/family")
        assert res_family.status_code == 200
        fam_data = res_family.get_json()
        assert fam_data["success"] is True
        assert fam_data["family"]["name"] == "The Jones Family"
        assert len(fam_data["members"]) == 5  # Sarah, Alex, Maya, Ethan, Chloe

        # Equity Grants (Multi-Company via /api/dashboard & /fragments/equity)
        res_dash = client.get("/api/dashboard")
        assert res_dash.status_code == 200
        dash_data = res_dash.get_json()
        assert dash_data["success"] is True
        eq_data = dash_data["snapshot"]["company_equity"]
        assert len(eq_data.get("grants", [])) >= 3
        res_eq_frag = client.get("/fragments/equity")
        assert res_eq_frag.status_code == 200
        eq_html = res_eq_frag.get_data(as_text=True)
        assert "Nexus" in eq_html and "CloudFlow" in eq_html

        # Transcripts & Compensation via /fragments/compensation
        res_comp_frag = client.get("/fragments/compensation")
        assert res_comp_frag.status_code == 200
        assert "Dr. Sarah Jones, MD" in res_comp_frag.get_data(as_text=True)

        # Compensation
        res_comp = client.get("/api/compensation")
        assert res_comp.status_code == 200
        comp_data = res_comp.get_json()
        assert comp_data["success"] is True
        assert len(comp_data.get("history", [])) >= 5


def test_demo_write_rejection_forbidden():
    """Verifies that demo sessions are strictly read-only and cannot mutate data."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.get("/demo")

        # Attempt to add a family member
        res_add_member = client.post("/api/family/members", json={
            "name": "Intruder User",
            "email": "intruder@example.com",
            "relationship": "child"
        })
        assert res_add_member.status_code == 403
        assert "Forbidden" in res_add_member.get_json().get("error", "")

        # Attempt to update household assumptions
        res_update_assumptions = client.post("/api/settings/assumptions", json={
            "state": "NV",
            "annual_spending": 999999.0
        })
        assert res_update_assumptions.status_code == 403
        assert "Forbidden" in res_update_assumptions.get_json().get("error", "")


def test_admin_switch_universe():
    """Verifies that authenticated admin users can switch between universes."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Sign in as admin in public
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user"] = "Admin User"
            sess["user_email"] = "admin@example.com"
            sess["is_site_admin"] = True
            sess["role"] = "admin"
            sess["universe"] = "public"
            sess["family_id"] = 1

        # Switch to demo universe as admin
        res_switch = client.post("/api/admin/switch_universe", json={
            "universe": "demo",
            "family_id": 1,
            "as_viewer": False
        })
        assert res_switch.status_code == 200
        data = res_switch.get_json()
        assert data["success"] is True
        assert data["universe"] == "demo"
        assert data["role"] == "admin"

        # Now can write to demo as admin
        res_add_member = client.post("/api/family/members", json={
            "name": "Test Child 4",
            "email": "test4@example.com",
            "birthdate": "2020-01-01",
            "relationship": "child",
            "role": "viewer"
        })
        assert res_add_member.status_code == 200
        assert res_add_member.get_json()["success"] is True
        new_child_id = res_add_member.get_json().get("user_id")

        # Clean up test child so demo universe remains completely clean
        if new_child_id:
            res_del = client.delete(f"/api/family/members/{new_child_id}")
            assert res_del.status_code == 200
            assert res_del.get_json()["success"] is True

        # Switch back to public
        res_back = client.post("/api/admin/switch_universe", json={
            "universe": "public",
            "family_id": 1
        })
        assert res_back.status_code == 200
        assert res_back.get_json()["universe"] == "public"


def test_demo_persona_switching():
    """Verifies switching between different demo personas in the demo universe."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        # 1. Fetch available personas
        res_families = client.get("/api/demo/families")
        fam_list = res_families.get_json().get("families", [])
        assert len(fam_list) == 6
        assert set(["jones", "miller", "chen", "ramirez", "taylor", "foster"]) == set([f["slug"] for f in fam_list])

        # 2. Switch to The Millers (FIRE)
        res_miller = client.get("/demo/miller")
        assert res_miller.status_code == 302
        res_fam = client.get("/api/family")
        assert res_fam.status_code == 200
        assert res_fam.get_json()["family"]["name"] == "The Miller Family"

        # 3. Switch to The Chens (Founder)
        res_chen = client.get("/demo/chen")
        assert res_chen.status_code == 302
        res_fam_chen = client.get("/api/family")
        assert res_fam_chen.status_code == 200
        assert res_fam_chen.get_json()["family"]["name"] == "The Chen Family"

        # 4. Switch to The Ramirezes (Teacher & Electrician)
        res_ramirez = client.get("/demo/ramirez")
        assert res_ramirez.status_code == 302
        res_fam_ram = client.get("/api/family")
        assert res_fam_ram.status_code == 200
        assert res_fam_ram.get_json()["family"]["name"] == "The Ramirez Family"

        # 5. Switch to The Taylors (Nurse & Logistics)
        res_taylor = client.get("/demo/taylor")
        assert res_taylor.status_code == 302
        res_fam_taylor = client.get("/api/family")
        assert res_fam_taylor.status_code == 200
        assert res_fam_taylor.get_json()["family"]["name"] == "The Taylor Family"

        # 6. Switch to The Fosters (Single Mom & PT)
        res_foster = client.get("/demo/foster")
        assert res_foster.status_code == 302
        res_fam_foster = client.get("/api/family")
        assert res_fam_foster.status_code == 200
        assert res_fam_foster.get_json()["family"]["name"] == "The Foster Family"


def test_demo_families_hierarchical_plans():
    """Verifies that all demo personas have rich parent, child, and grandchild plans in /api/scenarios."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Check all 6 main demo personas
        expected_hierarchies = {
            "jones": {
                "root": "scen_baseline",
                "children": ["scen_jones_early_retire", "scen_jones_aggressive_equity"],
                "grandchild": "scen_jones_tahoe_retreat",
                "grandchild_parent": "scen_jones_early_retire",
            },
            "miller": {
                "root": "scen_baseline",
                "children": ["scen_miller_global_travel", "scen_miller_conservative_guardrail"],
                "grandchild": "scen_miller_islands_cabin",
                "grandchild_parent": "scen_miller_global_travel",
            },
            "chen": {
                "root": "scen_baseline",
                "children": ["scen_chen_secondary_tender", "scen_chen_delay_exit"],
                "grandchild": "scen_chen_suburban_home",
                "grandchild_parent": "scen_chen_secondary_tender",
            },
            "ramirez": {
                "root": "scen_baseline",
                "children": ["scen_ramirez_early_retire_62", "scen_ramirez_boost_savings"],
                "grandchild": "scen_ramirez_workshop_solar",
                "grandchild_parent": "scen_ramirez_early_retire_62",
            },
            "taylor": {
                "root": "scen_baseline",
                "children": ["scen_taylor_accelerate_debt", "scen_taylor_work_to_67"],
                "grandchild": "scen_taylor_retire_63",
                "grandchild_parent": "scen_taylor_accelerate_debt",
            },
            "foster": {
                "root": "scen_baseline",
                "children": ["scen_foster_work_to_67", "scen_foster_independent_clinic"],
                "grandchild": "scen_foster_clinic_early_retire",
                "grandchild_parent": "scen_foster_independent_clinic",
            },
        }

        for slug, spec in expected_hierarchies.items():
            client.get(f"/demo/{slug}")
            res = client.get("/api/scenarios")
            assert res.status_code == 200
            data = res.get_json()
            assert data["success"] is True

            sc_map = {s["id"]: s for s in data.get("scorecard", [])}
            assert spec["root"] in sc_map
            root = sc_map[spec["root"]]
            assert root.get("depth") == 0
            assert root.get("parent_id") is None

            for c_id in spec["children"]:
                assert c_id in sc_map, f"Missing child {c_id} for {slug}"
                child = sc_map[c_id]
                assert child.get("depth") == 1
                assert child.get("parent_id") == spec["root"]

            gc_id = spec["grandchild"]
            assert gc_id in sc_map, f"Missing grandchild {gc_id} for {slug}"
            gc = sc_map[gc_id]
            assert gc.get("depth") == 2
            assert gc.get("parent_id") == spec["grandchild_parent"]

        # Blank tenant has only baseline
        client.get("/demo/empty")
        res_empty = client.get("/api/scenarios")
        data_empty = res_empty.get_json()
        assert len(data_empty.get("scorecard", [])) == 1
        assert data_empty["scorecard"][0]["id"] == "scen_baseline"
        assert data_empty["scorecard"][0].get("depth") == 0


def test_blank_tenant_zero_state_purity():
    """
    Invariant: An unseeded, empty household (Family 7) MUST return safe zeros,
    empty lists, or empty dicts across ALL endpoints.
    Guarantees zero leakage of Family 1 personal financials.
    """
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Switch to blank tenant
        res_empty = client.get("/demo/empty")
        assert res_empty.status_code == 302

        # 1. Compensation fragment & API
        res_comp_frag = client.get("/fragments/compensation")
        assert res_comp_frag.status_code == 200
        res_comp = client.get("/api/compensation")
        assert res_comp.status_code == 200
        data_comp = res_comp.get_json()
        assert data_comp.get("history") == []

        # 2. Dashboard & Equity Grants via canonical /api/dashboard
        res_dash = client.get("/api/dashboard")
        assert res_dash.status_code == 200
        data_dash = res_dash.get_json()
        snap = data_dash.get("snapshot", {})
        assert snap.get("true_net_worth") == 0.0
        assert snap.get("company_equity", {}).get("grants", []) == []

        # 3. Equity fragment
        res_eq_frag = client.get("/fragments/equity")
        assert res_eq_frag.status_code == 200


        # 4. Overview SSR in demo mode must omit #overview-setup-checklist even for blank/unconfigured demo persona
        res_ov_frag = client.get("/fragments/overview")
        assert res_ov_frag.status_code == 200
        assert "overview-setup-checklist" not in res_ov_frag.get_data(as_text=True)

        res_root = client.get("/")
        assert res_root.status_code == 200
        assert "overview-setup-checklist" not in res_root.get_data(as_text=True)


def test_demo_forecasting_historical_ribbon_isolation():
    """
    Verifies that demo personas have their own realistic, tailored historical ribbons (2018-2025)
    and that The Jones Family does NOT leak the primary user's $33.8M net worth or $3.032M salary.
    """
    import forecast_engine
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as client:
        # 1. Check The Jones Family (family_id=1 in demo universe)
        with client.session_transaction() as sess:
            sess.clear()
            sess["authenticated"] = True
            sess["is_demo"] = True
            sess["universe"] = "demo"
            sess["family_id"] = 1
            sess["role"] = "viewer"

        with app.test_request_context():
            from flask import session
            session["universe"] = "demo"
            session["is_demo"] = True
            session["family_id"] = 1
            res_jones = forecast_engine.simulate_multi_scenarios(family_id=1)
            ribbon_jones = res_jones.get("historical_ribbon", [])
            cfs_jones = res_jones.get("historical_cash_flow_series", [])
            assert len(ribbon_jones) == 8
            assert len(cfs_jones) == 8
            # Invariant: Must NOT match production user's $33.8M net worth or $3.032M salary
            assert ribbon_jones[-1]["true_net_worth"] == 6850000.0
            assert cfs_jones[-1]["household_salary"] == 1020000.0

        # 2. Check Other Demo Personas (Miller, Chen, Ramirez, Taylor, Foster)
        for fid in [2, 3, 4, 5, 6]:
            with app.test_request_context():
                from flask import session
                session["universe"] = "demo"
                session["is_demo"] = True
                session["family_id"] = fid
                res = forecast_engine.simulate_multi_scenarios(family_id=fid)
                ribbon = res.get("historical_ribbon", [])
                cfs = res.get("historical_cash_flow_series", [])
                assert len(ribbon) == 8, f"Family {fid} missing historical ribbon"
                assert len(cfs) == 8, f"Family {fid} missing cash flow series"

        # 3. Check Blank Household (family_id=7 in demo universe)
        with app.test_request_context():
            from flask import session
            session["universe"] = "demo"
            session["is_demo"] = True
            session["family_id"] = 7
            res_blank = forecast_engine.simulate_multi_scenarios(family_id=7)
            assert len(res_blank.get("historical_ribbon", [])) == 0
            assert len(res_blank.get("historical_cash_flow_series", [])) == 0




