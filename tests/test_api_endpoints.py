"""
Integration and End-to-End API tests for the HVL Family Office Flask application.
Verifies all routes return 200 OK and expected JSON payloads with zero runtime errors.
"""

import sys
from pathlib import Path
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app


def get_authenticated_client():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Test User"
        sess["user_family_id"] = 1
        sess["family_id"] = 1
        sess["role"] = "editor"
        sess["auth_method"] = "Google OAuth"
    return client


def test_auth_and_index():
    client = app.test_client()
    # Unauthenticated access to / redirects to /login
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    # Login page renders
    resp = client.get("/login")
    assert resp.status_code == 200

    # Authenticated access to / renders index.html
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Test User"
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Family Office" in resp.data


def test_favicon_route():
    client = app.test_client()
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.mimetype == "image/vnd.microsoft.icon"
    assert len(resp.data) > 0


def test_hvl_logo_mark_route():
    client = app.test_client()
    resp = client.get("/hvl-logo-mark.svg")
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"
    assert len(resp.data) > 0


def test_fo_logo_mark_route():
    client = app.test_client()
    resp = client.get("/fo-logo-mark.svg")
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"
    assert len(resp.data) > 0


def test_features_page_route():
    """Verifies that the /features tour page is publicly accessible and renders key pillars."""
    client = app.test_client()
    resp = client.get("/features")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "HVL Family Office" in html
    assert 'Compare Multiple "What-If" Scenarios Side-by-Side' in html
    assert "Private College" in html
    assert "In-State Public" in html
    assert "1,000-Trial Stochastic Monte Carlo" in html or "1,000-Trial Monte Carlo" in html
    assert "Education Modeling" in html
    assert "State Estate Taxes" in html or "State Death Tax" in html
    assert "Philanthropic Giving" in html
    assert "Annual Exclusion Gifting" in html
    assert "Compensation &amp; Payroll" in html or "Compensation & Payroll" in html
    assert "Asset Location" in html
    assert "AI Financial Advisor" in html or "AI Advisor" in html
    assert "How This Fits With" in html
    assert "Zero-Knowledge Vault Encryption" in html
    assert "Frequently Asked Questions" in html
    assert "The Jones" in html
    assert "/demo/" in html


def test_in_app_guide_drawer():
    """Verifies that the in-app guide drawer and per-section trigger elements render across all 11 modules without a duplicate top-bar button."""
    client = get_authenticated_client()
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "btn-open-page-guide" not in html
    assert "page-guide-drawer" in html
    assert "page-guide-select" in html
    assert "bundle-modules.min.js" in html
    assert "bundle.min.css" in html
    assert "btn-guide-trigger" in html
    assert 'data-section="section-overview"' in html

    sections = [
        "overview", "equity", "scenarios", "holdings", "arbitrage",
        "compensation", "philanthropy", "gifting", "estate", "college", "accounts",
    ]
    for sec in sections:
        frag_resp = client.get(f"/fragments/{sec}")
        assert frag_resp.status_code == 200
        frag_html = frag_resp.data.decode("utf-8")
        assert "btn-guide-trigger" in frag_html, f"Missing guide button in /fragments/{sec}"
        assert f'data-section="section-{sec}"' in frag_html, f"Missing data-section in /fragments/{sec}"


def test_api_dashboard():
    client = get_authenticated_client()
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "snapshot" in data
    assert "multi_year_projections" in data
    # Check that education assets are segregated
    assert data["snapshot"]["education_assets"] > 700000.0
    assert "private_investments" in data
    priv = data["private_investments"]
    assert len(priv["items"]) >= 11
    assert priv["total_invested"] > 800000.0
    assert priv["total_value"] > 800000.0


def test_api_philanthropy():
    client = get_authenticated_client()
    resp = client.get("/api/philanthropy")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "donations_by_year" in data
    assert "annual_budgets" in data
    years = list(data["donations_by_year"].keys())
    assert len(years) >= 10

    # Test updating budget for 2026
    resp = client.post("/api/philanthropy/budget", json={
        "year": "2026",
        "budget": 160000.0
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["budget"] == 160000.0

    # Test adding a grant with date
    resp_add = client.post("/api/philanthropy/grant", json={
        "year": "2026",
        "organization": "Test Wildlife Fund",
        "amount": 2500.0,
        "date": "2026-05-18",
        "description": "Annual Conservation Grant"
    })
    assert resp_add.status_code == 200
    assert resp_add.get_json()["success"] is True
    assert resp_add.get_json()["grant"]["date"] == "2026-05-18"

    # Get index of added grant
    resp_get = client.get("/api/philanthropy")
    donations_2026 = resp_get.get_json()["donations_by_year"]["2026"]["donations"]
    added_idx = next(i for i, d in enumerate(donations_2026) if d.get("organization") == "Test Wildlife Fund")

    # Test editing the grant via PUT /api/philanthropy/grant
    resp_edit = client.put("/api/philanthropy/grant", json={
        "year": "2026",
        "index": added_idx,
        "organization": "Test Wildlife Fund",
        "amount": 3000.0,
        "date": "05/18/2026",  # Verify MM/DD/YYYY normalization
        "description": "Updated conservation grant"
    })
    assert resp_edit.status_code == 200
    assert resp_edit.get_json()["success"] is True
    assert resp_edit.get_json()["grant"]["amount"] == 3000.0
    assert resp_edit.get_json()["grant"]["date"] == "2026-05-18"

    # Clean up by deleting the grant
    resp_del = client.delete("/api/philanthropy/grant", json={
        "year": "2026",
        "index": added_idx
    })
    assert resp_del.status_code == 200
    assert resp_del.get_json()["success"] is True


def test_api_gifting():
    client = get_authenticated_client()
    resp = client.get("/api/gifting")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "yearly_details" in data
    assert "recipient_limits" in data
    limits = data["recipient_limits"]
    # Verify multi-person recipient limits dynamically
    num_peoples = [info.get("num_people") for info in limits.values()]
    assert 1 in num_peoples
    assert 2 in num_peoples
    assert 3 in num_peoples
    assert 4 in num_peoples
    for info in limits.values():
        cnt = info["num_people"]
        assert info["limit_from_couple"] == cnt * 38000.0
        assert info["limit_from_single_donor"] == cnt * 19000.0
    years = list(data["yearly_details"].keys())
    assert len(years) >= 5

    # Test 1-click copy prior year endpoint
    resp_copy = client.post("/api/gifting/copy_previous_year", json={
        "to_year": "2027",
        "from_year": "2026"
    })
    assert resp_copy.status_code == 200
    data_copy = resp_copy.get_json()
    assert data_copy["success"] is True
    assert data_copy["total_given"] == 140000.0

    # Test in-place budget edit with recipient renaming
    resp_update = client.post("/api/gifting/budget", json={
        "year": "2026",
        "recipient": "Thanh & Lee Family",
        "old_recipient": "Thanh & Lee",
        "amount": 22000.0,
        "beneficiary_count": 2
    })
    assert resp_update.status_code == 200
    data_up = resp_update.get_json()
    assert data_up["success"] is True
    assert data_up["recipient"] == "Thanh & Lee Family"
    assert data_up["amount"] == 22000.0

    # Revert back to original name and amount for test purity
    resp_revert = client.post("/api/gifting/budget", json={
        "year": "2026",
        "recipient": "Thanh & Lee",
        "old_recipient": "Thanh & Lee Family",
        "amount": 20000.0,
        "beneficiary_count": 2
    })
    assert resp_revert.status_code == 200
    assert resp_revert.get_json()["success"] is True

    # Test adding a new recipient
    resp_add = client.post("/api/gifting/recipient", json={
        "recipient": "Test Uncle Bob",
        "num_people": 2,
        "relationship": "Uncle",
        "initial_amount": 15000.0,
        "year": "2026"
    })
    assert resp_add.status_code == 200
    data_add = resp_add.get_json()
    assert data_add["success"] is True
    assert data_add["recipient"] == "Test Uncle Bob"
    assert data_add["member_count"] == 2

    # Verify recipient appears in gifting list
    resp_check = client.get("/api/gifting")
    assert resp_check.status_code == 200
    data_check = resp_check.get_json()
    assert "Test Uncle Bob" in data_check["recipient_limits"]
    assert data_check["recipient_limits"]["Test Uncle Bob"]["limit_from_couple"] == 76000.0

    # Test deleting the recipient
    resp_del = client.delete("/api/gifting/recipient", json={
        "recipient": "Test Uncle Bob"
    })
    assert resp_del.status_code == 200
    assert resp_del.get_json()["success"] is True

    # Verify recipient removed
    resp_check2 = client.get("/api/gifting")
    assert "Test Uncle Bob" not in resp_check2.get_json()["recipient_limits"]


def test_api_college():
    client = get_authenticated_client()
    resp = client.get("/api/education")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "growth_projections_7pct" in data
    assert "tuition_records" in data
    assert "tuition_summary" in data
    assert len(data["tuition_records"]) >= 10
    assert data["total_529_assets"] > 0
    assert data["child1_529"] > 0
    assert data["child2_529"] > 0
    assert "child_529_balances" in data
    assert len(data["children"]) >= 2
    for child in data["children"]:
        assert child["current_529_balance"] > 0
        assert len(child["accounts"]) >= 1

    # Test adding and deleting a future tuition year
    resp_add = client.post("/api/education/tuition", json={
        "school_year": "2037-2038",
        "child1": 0,
        "child2": 52000,
        "notes": "Test Post-Grad"
    })
    assert resp_add.status_code == 200
    assert resp_add.get_json()["success"] is True

    resp_del = client.delete("/api/education/tuition/2037-2038")
    assert resp_del.status_code == 200
    assert resp_del.get_json()["success"] is True


def test_api_compensation():
    client = get_authenticated_client()
    resp = client.get("/api/compensation")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "history" in data
    assert len(data["history"]) >= 20


def test_google_oauth_routes():
    client = app.test_client()
    # Test OAuth config endpoint
    resp = client.get("/auth/google/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enabled"] is True
    assert "apps.googleusercontent.com" in data["client_id"]

    # Test OAuth login redirect endpoint
    resp_login = client.get("/auth/google/login")
    assert resp_login.status_code == 302
    assert "accounts.google.com" in resp_login.headers["Location"]


def test_compensation_add_edit_delete():
    client = get_authenticated_client()
    # 1. Add/Update compensation record for 2027
    resp = client.post("/api/compensation", json={
        "year": 2027,
        "company": "Acme Technologies Inc",
        "salary": 1950000.0,
        "bonus": 1250000.0,
        "source": "Projected W-2"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    # Find 2027 record
    r_2027 = next((h for h in data["history"] if h["year"] == 2027), None)
    assert r_2027 is not None
    assert r_2027["salary"] == 1950000.0
    assert r_2027["total_compensation"] == 3200000.0

    # 2. Get compensation history
    resp_get = client.get("/api/compensation")
    assert resp_get.status_code == 200
    assert any(h["year"] == 2027 for h in resp_get.get_json()["history"])

    # 3. Delete 2027 record
    resp_del = client.delete("/api/compensation/2027")
    assert resp_del.status_code == 200
    assert not any(h["year"] == 2027 for h in resp_del.get_json()["history"])


def test_equity_fmv_and_grant_api():
    client = get_authenticated_client()
    # Read original FMV so we can cleanly revert after testing
    resp_init = client.get("/api/dashboard")
    orig_price = ((resp_init.get_json() or {}).get("snapshot") or {}).get("company_equity", {}).get("share_price", 2733.0)

    # 1. Update 409A FMV
    resp_fmv = client.post("/api/equity/fmv", json={
        "price": 1250.0,
        "effective_date": "2026-10-10",
        "notes": "Verified 409A Valuation"
    })
    assert resp_fmv.status_code == 200
    data_fmv = resp_fmv.get_json()
    assert data_fmv["success"] is True
    assert data_fmv["price"] == 1250.0

    # 2. Add an equity grant
    resp_grant = client.post("/api/equity/grant", json={
        "nickname": "Test Grant 4 (A-999)",
        "grantDate": "2026-11-01",
        "fullyVestedDate": "2030-11-01",
        "quantityGranted": 500,
        "strikePrice": 1250.0,
        "unvestedQuantity": 500
    })
    assert resp_grant.status_code == 200
    data_grant = resp_grant.get_json()
    assert data_grant["success"] is True
    assert data_grant["grant"]["quantityGranted"] == 500

    # 3. Clean up test grant so it does not persist in DB
    grant_id = data_grant["grant"]["id"]
    resp_del = client.delete(f"/api/equity/grant/{grant_id}")
    assert resp_del.status_code == 200
    assert resp_del.get_json()["success"] is True

    # 4. Revert FMV back to original value
    client.post("/api/equity/fmv", json={
        "price": orig_price,
        "effective_date": "2026-10-10",
        "notes": "Restored Valuation"
    })

    # 5. Verify test grant is completely removed from DB
    resp_verify = client.get("/api/dashboard")
    assert resp_verify.status_code == 200
    grants = ((resp_verify.get_json() or {}).get("snapshot") or {}).get("company_equity", {}).get("grants", [])
    assert not any(g.get("grant_label") == "Test Grant 4 (A-999)" for g in grants)


def test_historical_networth_api():
    client = get_authenticated_client()
    # 1. Baseline check: returns current year (or seeded years) without fabricating fake 5-year scaled curves
    resp = client.get("/api/networth/history")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "historical_net_worth" in data
    assert len(data["historical_net_worth"]) >= 1
    h_2026 = data["historical_net_worth"][-1]
    assert h_2026["year"] == 2026
    assert h_2026["true_net_worth"] > 25000000.0

    # 2. Record historical snapshots with a multi-year gap (2022 and 2024) and verify linear interpolation fills 2023
    post_resp = client.post(
        "/api/accounts/history",
        json={
            "snapshots": [
                {"account_name": "Vanguard Brokerage", "date": "2022-12-31", "balance": 1000000.0, "role": "public_brokerage"},
                {"account_name": "Vanguard Brokerage", "date": "2024-12-31", "balance": 2000000.0, "role": "public_brokerage"},
            ]
        },
    )
    assert post_resp.status_code == 200
    post_data = post_resp.get_json()
    assert post_data["success"] is True
    years_map = {row["year"]: row for row in post_data["historical_net_worth"]}
    assert 2022 in years_map and 2023 in years_map and 2024 in years_map
    # 2023 should be smoothly interpolated halfway between 2022 (1M) and 2024 (2M)
    assert years_map[2022]["liquid_investments"] < years_map[2023]["liquid_investments"] < years_map[2024]["liquid_investments"]

    # 3. Verify CSV Import (Long format + Wide pivot format) and CSV Export ("Download Your Data")
    csv_resp = client.post(
        "/api/accounts/import_csv",
        json={
            "csv_text": "Date,Account Name,Balance,Role\n2021-12-31,Vanguard Brokerage,\"$800,000.00\",public_brokerage\n"
        },
    )
    assert csv_resp.status_code == 200
    csv_data = csv_resp.get_json()
    assert csv_data["success"] is True
    assert 2021 in csv_data["years_covered"]

    exp_resp = client.get("/api/accounts/export_csv")
    assert exp_resp.status_code == 200
    assert "text/csv" in exp_resp.headers.get("Content-Type", "")
    csv_body = exp_resp.get_data(as_text=True)
    assert "Vanguard Brokerage" in csv_body
    assert "2021-12-31" in csv_body



def test_investments_and_net_worth_integrity():
    """Verifies that private investments exclude company equity, and true net worth does not double count."""
    client = get_authenticated_client()
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True

    snap = data["snapshot"]
    # 1. Non-company net worth must not include company equity or crude tax liability
    assert "categories" in snap
    cats = snap["categories"]
    assert "manual_tax_offset" not in cats

    # 2. Private investments must not include primary company equity
    priv_items = data.get("private_investments", {}).get("items", [])
    comp_name = (snap.get("company_equity") or {}).get("company_name", "Primary Company").lower()
    assert not any(comp_name in (item.get("name") or "").lower() for item in priv_items)

    # 3. True net worth must strictly equal non_equity_net_worth + company_true_net
    non_equity = snap.get("non_equity_net_worth", 0.0)
    equity_data = snap.get("company_equity", {})
    comp_true_net = equity_data.get("true_net_post_tax_value", 0.0)
    assert round(snap["true_net_worth"], 2) == round(non_equity + comp_true_net, 2)
    # Must NOT spike to $78M+ from double counting
    assert snap["true_net_worth"] < 60000000.0


def test_monarch_status_and_account_roles_hiding():
    """Tests settings SSR fragment and /api/settings/account_roles is_hidden_from_family_office functionality."""
    client = get_authenticated_client()
    resp_frag = client.get("/fragments/settings")
    assert resp_frag.status_code == 200

    # Test getting account roles
    resp_roles = client.get("/api/settings/account_roles")
    assert resp_roles.status_code == 200
    roles_data = resp_roles.get_json()
    assert roles_data["success"] is True
    accounts = roles_data["accounts"]
    assert len(accounts) > 0
    # Verify is_hidden_from_family_office is present on all accounts
    assert all("is_hidden_from_family_office" in acc for acc in accounts)


def test_htmx_ssr_fragments_and_endpoints():
    """Verifies that shared design system/HTMX assets and HTML fragment routes operate with proper authentication."""
    client = app.test_client()

    # 1. Common shared design system and HTMX assets are publicly accessible
    assert client.get("/common/utils.js").status_code == 200
    assert client.get("/common/toast.js").status_code == 200
    assert client.get("/common/theme.css").status_code == 200
    assert client.get("/common/components.css").status_code == 200
    assert client.get("/common/icons.svg").status_code == 200
    assert client.get("/common/htmx.min.js").status_code == 200
    assert client.get("/common/idiomorph-ext.min.js").status_code == 200

    # 2. Unauthenticated access to /fragments/<name> redirects to /login
    resp = client.get("/fragments/scenarios")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    # 3. Authenticated access to valid fragments renders partial HTML (SSR)
    auth_client = get_authenticated_client()
    for frag in [
        "scenarios", "estate", "philanthropy", "gifting",
        "compensation", "college", "arbitrage", "holdings",
        "equity", "accounts", "settings", "overview"
    ]:
        resp = auth_client.get(f"/fragments/{frag}")
        assert resp.status_code == 200, f"Failed for fragment {frag}"
        assert len(resp.data) > 50, f"Fragment {frag} returned empty shell"

    # 4. Unknown fragment returns 404
    resp = auth_client.get("/fragments/nonexistent_partial")
    assert resp.status_code == 404


def test_ai_advisor_async_background_job_and_polling(monkeypatch):
    """Verifies that POST /api/ai-advisor/chat with async=True runs in background_jobs.EXECUTOR and GET /api/ai-advisor/jobs/<job_id> returns the completed reply."""
    import time
    from unittest.mock import MagicMock
    import routes.ai_advisor as ai_adv

    mock_resp = MagicMock()
    mock_resp.text = "Safe harbor test calculation reply."
    monkeypatch.setattr(ai_adv, "generate_content_with_tools", lambda *a, **k: mock_resp)

    client = get_authenticated_client()
    resp = client.post(
        "/api/ai-advisor/chat",
        json={
            "message": "What is our current safe harbor tax target?",
            "active_tab": "section-tax",
            "async": True,
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["status"] == "processing"
    job_id = data.get("job_id")
    assert job_id

    # Verify tenant isolation on job status lookup (different family_id gets 404)
    other_client = app.test_client()
    with other_client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Other Tenant"
        sess["user_family_id"] = 999
        sess["family_id"] = 999
        sess["role"] = "editor"
    iso_resp = other_client.get(f"/api/ai-advisor/jobs/{job_id}")
    assert iso_resp.status_code == 404

    # Poll until completed
    final_data = None
    for _ in range(40):
        poll_resp = client.get(f"/api/ai-advisor/jobs/{job_id}")
        assert poll_resp.status_code == 200
        pdata = poll_resp.get_json()
        if pdata.get("status") == "completed":
            final_data = pdata
            break
        time.sleep(0.05)

    assert final_data is not None, "Background AI advisor job did not complete within timeout"
    assert final_data["success"] is True
    assert final_data.get("reply")
    assert final_data.get("conversation_id")


def test_household_deletion_grace_period_restore_and_immediate_shred():
    """
    Verifies end-to-end household deletion lifecycle:
    1. Danger Zone UI and confirmation modal render in /fragments/settings.
    2. Demo/Viewer sessions are blocked (403) and mismatched confirmation names are rejected (400).
    3. 30-day soft-delete quarantine freezes the household, blocks dashboard/API routes with redirect to
       /account-recovery, and serves the /account-recovery interstitial page.
    4. POST /api/family/restore cancels the scheduled deletion and restores full access.
    5. POST /api/family/delete with immediate=True physically unlinks families/{id}.db and families/{id}_cache.db
       and purges the household from global.db.
    """
    import security
    from config import get_cache_db_path_for_universe, get_family_db_path, get_global_db_path
    from hvl_common.db import get_db_connection

    test_fid = 888
    uni = "test"
    fam_db = get_family_db_path(test_fid, universe=uni)
    cache_db = get_cache_db_path_for_universe(uni, family_id=test_fid)
    glob_db = get_global_db_path(universe=uni)

    try:
        # Provision isolated test family 888
        security.init_db(fam_db)
        security.init_db(glob_db)
        with get_db_connection(fam_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO families (family_id, name, settings, support_access_enabled) VALUES (?, ?, ?, 1)",
                (test_fid, "The Horizon Household", '{"primary_state": "WA", "tax_filing_status": "MFJ"}'),
            )
            conn.commit()
        security.update_family(fam_db, family_id=test_fid, name="The Horizon Household")
        security.add_family_member(
            db_path=fam_db,
            family_id=test_fid,
            name="Alex Horizon",
            email="alex.horizon.test@example.com",
            birthdate="1985-04-12",
            relationship="primary",
            role="editor",
        )
        # Create dummy cache db file to verify cache DB cleanup
        cache_db.write_bytes(b"SQLite format 3\x00")
        assert fam_db.exists()
        assert cache_db.exists()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["is_demo"] = False
            sess["universe"] = uni
            sess["user"] = "Alex"
            sess["user_display"] = "Alex Horizon"
            sess["user_email"] = "alex.horizon.test@example.com"
            sess["role"] = "editor"
            sess["user_role"] = "editor"
            sess["family_id"] = test_fid
            sess["user_family_id"] = test_fid

        # 1. Verify Danger Zone UI and modal in /fragments/settings
        frag_resp = client.get("/fragments/settings")
        assert frag_resp.status_code == 200
        frag_html = frag_resp.get_data(as_text=True)
        assert "danger-zone-delete-household-card" in frag_html
        assert "btn-open-delete-household-modal" in frag_html
        assert "delete-household-modal" in frag_html
        assert "The Horizon Household" in frag_html

        # 2. Mismatched confirmation name is rejected with 400
        bad_del = client.post("/api/family/delete", json={
            "confirm_name": "Wrong Name",
            "immediate": False,
        })
        assert bad_del.status_code == 400
        assert "must match your Family Office name" in bad_del.get_json()["error"]

        # 3. Demo session cannot delete household (403)
        demo_client = app.test_client()
        with demo_client.session_transaction() as dsess:
            dsess["authenticated"] = True
            dsess["is_demo"] = True
            dsess["universe"] = "demo"
            dsess["role"] = "viewer"
            dsess["family_id"] = 1
        demo_del = demo_client.post("/api/family/delete", json={"confirm_name": "The Jones Family"})
        assert demo_del.status_code == 403

        # 4. Schedule 30-day soft deletion
        sched_resp = client.post("/api/family/delete", json={
            "confirm_name": "The Horizon Household",
            "immediate": False,
        })
        assert sched_resp.status_code == 200
        sched_data = sched_resp.get_json()
        assert sched_data["success"] is True
        assert sched_data["mode"] == "grace_period"
        assert sched_data["redirect"] == "/account-recovery"
        assert sched_data["deletion_status"]["is_scheduled"] is True
        assert sched_data["deletion_status"]["days_remaining"] >= 29
        # L2 cache DB is unlinked immediately while main family DB remains frozen for 30 days
        assert not cache_db.exists()
        assert fam_db.exists()

        # 5. Normal routes redirect to /account-recovery and API routes return 403 while in quarantine
        dash_redirect = client.get("/")
        assert dash_redirect.status_code == 302
        assert "/account-recovery" in dash_redirect.headers["Location"]

        api_blocked = client.get("/api/settings/assumptions")
        assert api_blocked.status_code == 403
        assert api_blocked.get_json()["deletion_scheduled"] is True

        # 6. /account-recovery renders 200 with countdown and restore CTA
        rec_page = client.get("/account-recovery")
        assert rec_page.status_code == 200
        rec_html = rec_page.get_data(as_text=True)
        assert "Your Household Vault is Scheduled for Deletion" in rec_html
        assert "btn-restore-household" in rec_html
        assert "The Horizon Household" in rec_html

        # 7. Restore household cancels quarantine and restores access
        restore_resp = client.post("/api/family/restore")
        assert restore_resp.status_code == 200
        assert restore_resp.get_json()["success"] is True

        assump_ok = client.get("/api/settings/assumptions")
        assert assump_ok.status_code == 200
        assert security.get_family_deletion_status(fam_db, family_id=test_fid) is None

        # 8. Immediate deletion physically unlinks families/888.db and purges global.db rows
        imm_resp = client.post("/api/family/delete", json={
            "confirm_name": "The Horizon Household",
            "immediate": True,
        })
        assert imm_resp.status_code == 200
        imm_data = imm_resp.get_json()
        assert imm_data["success"] is True
        assert imm_data["mode"] == "immediate"
        assert imm_data["permanently_deleted"] is True
        assert not fam_db.exists()
        assert not cache_db.exists()

        if glob_db.exists():
            with get_db_connection(glob_db) as gconn:
                assert gconn.execute("SELECT 1 FROM families WHERE family_id = ?", (test_fid,)).fetchone() is None
                assert gconn.execute("SELECT 1 FROM users WHERE family_id = ?", (test_fid,)).fetchone() is None
    finally:
        try:
            security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
        except Exception:
            pass


def test_per_household_resource_limits_and_updates(monkeypatch):
    """
    Verifies all per-household resource caps return HTTP 400 with a descriptive
    'Maximum of ... reached' error on net-new insertions, while still allowing
    in-place updates to existing records when at the cap.
    """
    import io
    import config
    import db
    import security
    from hvl_common.db import get_db_connection

    test_fid = 889
    uni = "test"
    fam_db = config.get_family_db_path(test_fid, universe=uni)
    glob_db = config.get_global_db_path(universe=uni)

    try:
        security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
    except Exception:
        pass

    security.init_db(fam_db)
    security.init_db(glob_db)
    with get_db_connection(fam_db) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO families (family_id, name, settings, support_access_enabled) VALUES (?, ?, ?, 1)",
            (test_fid, "The Limit Test Household", '{"primary_state": "WA", "tax_filing_status": "MFJ"}'),
        )
        conn.commit()
    security.update_family(fam_db, family_id=test_fid, name="The Limit Test Household")
    security.get_family_key(fam_db, family_id=test_fid)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["is_demo"] = False
        sess["universe"] = uni
        sess["user"] = "limit_tester@example.com"
        sess["user_email"] = "limit_tester@example.com"
        sess["user_family_id"] = test_fid
        sess["family_id"] = test_fid
        sess["role"] = "admin"
        sess["user_role"] = "admin"
        sess["auth_method"] = "Google OAuth"

    try:
        # 1. Scenarios, Child Scenarios, Hierarchy Depth & Forecast Events
        import forecast_engine
        scen_state = forecast_engine.load_scenario_state(family_id=test_fid)
        base_scen_count = len(scen_state.get("scenarios", []))
        base_evt_count = len(scen_state.get("events", []))

        monkeypatch.setattr(config, "MAX_SCENARIOS", base_scen_count + 1)
        r_s1 = client.post("/api/scenarios", json={"id": "scen_custom_1", "name": "Custom 1"})
        assert r_s1.status_code == 200
        # At cap: creating a new scenario or cloning fails with 400
        r_s2 = client.post("/api/scenarios", json={"id": "scen_custom_2", "name": "Custom 2"})
        assert r_s2.status_code == 400
        assert "Maximum of" in r_s2.get_json()["error"]
        r_clone = client.post("/api/scenarios/scen_baseline/clone", json={"name": "Clone Blocked"})
        assert r_clone.status_code == 400
        assert "Maximum of" in r_clone.get_json()["error"]
        # Updating existing scenario at cap succeeds
        r_upd_scen = client.post("/api/scenarios", json={"id": "scen_custom_1", "name": "Custom 1 Updated"})
        assert r_upd_scen.status_code == 200

        # Child scenarios per parent & hierarchy depth
        monkeypatch.setattr(config, "MAX_SCENARIOS", base_scen_count + 10)
        monkeypatch.setattr(config, "MAX_CHILD_SCENARIOS_PER_PARENT", 1)
        monkeypatch.setattr(config, "MAX_SCENARIO_DEPTH", 2)
        r_child1 = client.post("/api/scenarios", json={"id": "scen_child_1", "name": "Child 1", "parent_id": "scen_custom_1"})
        assert r_child1.status_code == 200
        r_child2 = client.post("/api/scenarios", json={"id": "scen_child_2", "name": "Child 2", "parent_id": "scen_custom_1"})
        assert r_child2.status_code == 400
        assert "child scenarios per parent" in r_child2.get_json()["error"]

        monkeypatch.setattr(config, "MAX_CHILD_SCENARIOS_PER_PARENT", 5)
        r_grandchild = client.post("/api/scenarios", json={"id": "scen_grandchild_1", "name": "Grandchild 1", "parent_id": "scen_child_1"})
        assert r_grandchild.status_code == 400
        assert "hierarchy depth" in r_grandchild.get_json()["error"]

        # Forecast Events
        monkeypatch.setattr(config, "MAX_FORECAST_EVENTS", base_evt_count + 1)
        r_e1 = client.post("/api/events", json={"id": "evt_limit_1", "name": "Event 1", "amount": 10000, "start_year": 2027})
        assert r_e1.status_code == 200
        r_e2 = client.post("/api/events", json={"id": "evt_limit_2", "name": "Event 2", "amount": 20000, "start_year": 2028})
        assert r_e2.status_code == 400
        assert "Maximum of" in r_e2.get_json()["error"]
        # Updating existing event at cap succeeds
        r_e1_upd = client.post("/api/events", json={"id": "evt_limit_1", "name": "Event 1 Edited", "amount": 15000, "start_year": 2027})
        assert r_e1_upd.status_code == 200

        # 2. Gifting Recipients & Gift Records
        monkeypatch.setattr(config, "MAX_GIFT_RECIPIENTS", 1)
        monkeypatch.setattr(config, "MAX_GIFT_RECORDS", 1)
        r_g1 = client.post("/api/gifting/recipient", json={"recipient": "Group Alpha", "num_people": 2, "relationship": "Sibling", "amount": 18000, "year": "2026"})
        assert r_g1.status_code == 200
        r_g2 = client.post("/api/gifting/recipient", json={"recipient": "Group Beta", "num_people": 1, "relationship": "Friend", "amount": 5000, "year": "2026"})
        assert r_g2.status_code == 400
        assert "gift recipients" in r_g2.get_json()["error"]
        # Updating existing recipient's 2026 gift at cap succeeds
        r_g1_upd = client.post("/api/gifting/budget", json={"recipient": "Group Alpha", "num_people": 2, "relationship": "Sibling", "amount": 20000, "year": "2026"})
        assert r_g1_upd.status_code == 200
        # Copying to a new year fails when MAX_GIFT_RECORDS == 1
        r_g_copy = client.post("/api/gifting/copy_previous_year", json={"from_year": "2026", "to_year": "2027"})
        assert r_g_copy.status_code == 400
        assert "gift records" in r_g_copy.get_json()["error"]

        # 3. Philanthropy Years & Donations
        monkeypatch.setattr(config, "MAX_PHILANTHROPY_YEARS", 1)
        monkeypatch.setattr(config, "MAX_PHILANTHROPY_DONATIONS", 1)
        r_pb1 = client.post("/api/philanthropy/budget", json={"year": "2026", "budget": 50000})
        assert r_pb1.status_code == 200
        r_pb1_upd = client.post("/api/philanthropy/budget", json={"year": "2026", "budget": 60000})
        assert r_pb1_upd.status_code == 200
        r_pb2 = client.post("/api/philanthropy/budget", json={"year": "2027", "budget": 50000})
        assert r_pb2.status_code == 400
        assert "philanthropy budget years" in r_pb2.get_json()["error"]

        r_pd1 = client.post("/api/philanthropy/grant", json={"year": "2026", "organization": "Local Food Bank", "amount": 5000})
        assert r_pd1.status_code == 200
        r_pd2 = client.post("/api/philanthropy/grant", json={"year": "2026", "organization": "Animal Shelter", "amount": 2500})
        assert r_pd2.status_code == 400
        assert "charitable donations" in r_pd2.get_json()["error"]

        # 4. Equity Companies, Grants & FMV History
        monkeypatch.setattr(config, "MAX_EQUITY_COMPANIES", 1)
        monkeypatch.setattr(config, "MAX_EQUITY_GRANTS", 1)
        monkeypatch.setattr(config, "MAX_FMV_RECORDS_PER_COMPANY", 2)
        r_ec1 = client.post("/api/equity/company", json={"company_name": "Alpha Tech", "current_fmv": 25.0, "fmv_date": "2026-01"})
        assert r_ec1.status_code == 200
        cid = r_ec1.get_json()["company_id"]
        r_ec2 = client.post("/api/equity/company", json={"company_name": "Beta Bio", "current_fmv": 15.0, "fmv_date": "2026-01"})
        assert r_ec2.status_code == 400
        assert "equity companies" in r_ec2.get_json()["error"]

        r_eg1 = client.post("/api/equity/grant", json={"company_id": cid, "nickname": "Initial Grant", "grantDate": "2026-01-15", "quantityGranted": 1000, "strikePrice": 5.0, "grantType": "nso"})
        assert r_eg1.status_code == 200
        gid = r_eg1.get_json()["grant"]["id"]
        r_eg2 = client.post("/api/equity/grant", json={"company_id": cid, "nickname": "Refresh Grant", "grantDate": "2026-06-15", "quantityGranted": 500, "strikePrice": 10.0, "grantType": "rsu"})
        assert r_eg2.status_code == 400
        assert "equity grants" in r_eg2.get_json()["error"]
        # Updating existing grant at cap succeeds
        r_eg1_upd = client.put(f"/api/equity/grant/{gid}", json={"nickname": "Initial Grant Updated", "grantDate": "2026-01-15", "quantityGranted": 1200, "strikePrice": 5.0, "grantType": "nso"})
        assert r_eg1_upd.status_code == 200

        # FMV History (1 created with company, 2nd allowed, 3rd blocked, updating 2nd allowed)
        r_fmv2 = client.post("/api/equity/fmv", json={"company_id": cid, "effective_date": "2026-06", "price": 30.0})
        assert r_fmv2.status_code == 200
        r_fmv2_upd = client.post("/api/equity/fmv", json={"company_id": cid, "effective_date": "2026-06", "price": 32.0})
        assert r_fmv2_upd.status_code == 200
        r_fmv3 = client.post("/api/equity/fmv", json={"company_id": cid, "effective_date": "2026-09", "price": 35.0})
        assert r_fmv3.status_code == 400
        assert "FMV history records" in r_fmv3.get_json()["error"]

        # 5. Compensation & W-2 Upload
        monkeypatch.setattr(config, "MAX_COMPENSATION_RECORDS", 1)
        r_comp1 = client.post("/api/compensation/save", json={"year": 2025, "adult": "1", "company": "Alpha Tech", "base_salary": 200000})
        assert r_comp1.status_code == 200
        r_comp1_upd = client.post("/api/compensation/save", json={"year": 2025, "adult": "1", "company": "Alpha Tech", "base_salary": 210000})
        assert r_comp1_upd.status_code == 200
        r_comp2 = client.post("/api/compensation/save", json={"year": 2026, "adult": "1", "company": "Alpha Tech", "base_salary": 220000})
        assert r_comp2.status_code == 400
        assert "compensation records" in r_comp2.get_json()["error"]

        r_w2 = client.post("/api/compensation/upload_w2", data={"file": (io.BytesIO(b"%PDF-1.4 dummy"), "w2.pdf")}, content_type="multipart/form-data")
        assert r_w2.status_code == 400
        assert "compensation records" in r_w2.get_json()["error"]

        # 6. Education / Tuition
        monkeypatch.setattr(config, "MAX_TUITION_YEARS", 1)
        monkeypatch.setattr(config, "MAX_TUITION_RECORDS", 1)
        r_t1 = client.post("/api/education/tuition/save", json={"school_year": "2026-2027", "total_cost": 25000})
        assert r_t1.status_code == 200
        r_t1_upd = client.post("/api/education/tuition/save", json={"school_year": "2026-2027", "total_cost": 26000})
        assert r_t1_upd.status_code == 200
        r_t2 = client.post("/api/education/tuition/save", json={"school_year": "2027-2028", "total_cost": 27000})
        assert r_t2.status_code == 400
        assert "tuition school years" in r_t2.get_json()["error"]

        # 7. Tax Transcripts
        monkeypatch.setattr(config, "MAX_TAX_TRANSCRIPTS", 0)
        r_tx = client.post("/api/transcripts/upload", data={"file": (io.BytesIO(b"%PDF-1.4 dummy"), "transcript.pdf")}, content_type="multipart/form-data")
        assert r_tx.status_code == 400
        assert "tax transcript records" in r_tx.get_json()["error"]

        # 8. AI Advisor Conversations & Messages
        monkeypatch.setattr(config, "MAX_ADVISOR_CONVERSATIONS", 1)
        r_ac1 = client.post("/api/ai-advisor/conversations", json={"title": "First Thread"})
        assert r_ac1.status_code == 200
        conv_id = r_ac1.get_json()["conversation_id"]
        r_ac2 = client.post("/api/ai-advisor/conversations", json={"title": "Second Thread"})
        assert r_ac2.status_code == 400
        assert "AI Advisor conversations" in r_ac2.get_json()["error"]

        monkeypatch.setattr(config, "MAX_ADVISOR_MESSAGES_PER_CONV", 0)
        r_am = client.post("/api/ai-advisor/chat", json={"message": "Hello advisor", "conversation_id": conv_id})
        assert r_am.status_code == 400
        assert "messages per conversation" in r_am.get_json()["error"]

        # 9. Magic Invites
        monkeypatch.setattr(config, "MAX_ACTIVE_INVITES_PER_FAMILY", 1)
        r_inv1 = client.post("/api/family/invites", json={"invite_type": "join_household", "role": "editor", "label": "Invite 1"})
        assert r_inv1.status_code == 200
        r_inv2 = client.post("/api/family/invites", json={"invite_type": "join_household", "role": "editor", "label": "Invite 2"})
        assert r_inv2.status_code == 400
        assert "active invite links" in r_inv2.get_json()["error"]

        # 10. Holdings
        monkeypatch.setattr(config, "MAX_HOUSEHOLD_HOLDINGS", 1)
        import pytest
        with pytest.raises(ValueError, match="Maximum of 1 holdings per household reached"):
            db.accounts.save_holdings(
                family_id=test_fid,
                holdings=[
                    {"id": "h1", "account_id": "a1", "ticker": "VTI", "total_value": 1000},
                    {"id": "h2", "account_id": "a1", "ticker": "VXUS", "total_value": 2000},
                ],
                db_path=fam_db,
            )
    finally:
        try:
            security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
        except Exception:
            pass


def test_whats_new_page_and_scenarios_csv_export_and_granularity():
    """
    Verifies:
    1. `/whats-new` and `/changes` visual release review & public changelog routes return HTTP 200 with live UI previews and copy review table.
    2. `GET /api/scenarios/export_csv` exports a downloadable 30-year cash flow & tax projection CSV.
    3. `GET /api/networth/history` supports `monthly_net_worth`, `quarterly_net_worth`, and `recommended_granularity`.
    """
    client = get_authenticated_client()

    # 1. Verify /whats-new and /changes render HTTP 200 with expected review & preview sections
    wn_resp = client.get("/whats-new")
    assert wn_resp.status_code == 200
    wn_html = wn_resp.get_data(as_text=True)
    assert "Sync Accounts" in wn_html
    assert "SimpleFIN" in wn_html

    ch_resp = client.get("/changes")
    assert ch_resp.status_code == 200

    # 2. Verify Scenarios Multi-Year Forecast & Tax Projection CSV export
    sc_csv_resp = client.get("/api/scenarios/export_csv")
    assert sc_csv_resp.status_code == 200
    assert "text/csv" in sc_csv_resp.headers.get("Content-Type", "")
    sc_csv_text = sc_csv_resp.get_data(as_text=True)
    assert "Year,Age,Gross Income" in sc_csv_text
    assert "True Net Worth" in sc_csv_text
    assert len(sc_csv_text.strip().splitlines()) >= 10

    # 3. Verify Net Worth Over Time returns monthly, quarterly, and annual series + recommended_granularity
    nw_resp = client.get("/api/networth/history?granularity=monthly").get_json()
    assert nw_resp["success"] is True
    assert "monthly_net_worth" in nw_resp
    assert "quarterly_net_worth" in nw_resp
    assert nw_resp.get("recommended_granularity") in ("annual", "monthly", "quarterly")

    # 4. Verify Site-Admin-Only /admin/release-review returns 200 for Family 1 Admin and 403 for Demo / non-admin
    adm_resp = client.get("/admin/release-review")
    assert adm_resp.status_code == 200
    adm_html = adm_resp.get_data(as_text=True)
    assert "Old Copy" in adm_html and "New Copy" in adm_html

    demo_client = app.test_client()
    with demo_client.session_transaction() as dsess:
        dsess["authenticated"] = True
        dsess["is_demo"] = True
        dsess["universe"] = "demo"
        dsess["role"] = "viewer"
        dsess["family_id"] = 2
    assert demo_client.get("/admin/release-review").status_code == 403


def test_help_and_whats_new_subnav_common_controls():
    """
    Verifies that /help and /whats-new pages render the common scrollable ribbon control
    with container, inner list, prev/next arrow buttons, and /common/utils.js.
    """
    client = app.test_client()
    for endpoint in ("/help", "/whats-new"):
        res = client.get(endpoint)
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "features-subnav-strip" in html
        assert "features-subnav-container" in html
        assert "btn-subnav-prev" in html
        assert "btn-subnav-next" in html
        assert "subnav-arrow-btn prev" in html
        assert "subnav-arrow-btn next" in html
        assert "/common/utils.js" in html







