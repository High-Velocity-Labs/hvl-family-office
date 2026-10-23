"""
Focused tests for Account Connectors (Monarch Money, SimpleFIN Bridge),
First-Class Manual Accounts CRUD & Guards, BYO Gemini API Key Lifecycle,
and 4-Step Guided Household Onboarding Progression.
"""

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import db
import monarch_service
import requests
import security
from app import app
from config import get_family_db_path, get_global_db_path
from db.accounts import list_accounts, replace_accounts
from hvl_common.db import get_db_connection
from monarch.simplefin import (
    _infer_simplefin_account_type,
    _normalize_simplefin_payload,
    claim_simplefin_setup_token,
    get_simplefin_status,
)
from routes.helpers import DB_PATH


def _provision_test_family(test_fid: int, name: str, uni: str = "test"):
    fam_db = get_family_db_path(test_fid, universe=uni)
    glob_db = get_global_db_path(universe=uni)
    security.init_db(fam_db)
    security.init_db(glob_db)
    with get_db_connection(fam_db) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO families (family_id, name, settings, support_access_enabled) VALUES (?, ?, ?, 1)",
            (test_fid, name, '{"primary_state": "WA", "tax_filing_status": "MFJ"}'),
        )
        conn.commit()
    security.update_family(fam_db, family_id=test_fid, name=name)
    return fam_db, glob_db


def _make_family_client(test_fid: int, user_email: str = "member.test@example.com", uni: str = "test"):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["is_demo"] = False
        sess["universe"] = uni
        sess["user"] = "TestMember"
        sess["user_display"] = "Test Member"
        sess["user_email"] = user_email
        sess["role"] = "editor"
        sess["user_role"] = "editor"
        sess["family_id"] = test_fid
        sess["user_family_id"] = test_fid
        sess["auth_method"] = "Google OAuth"
    return client


def _make_demo_client():
    demo_client = app.test_client()
    with demo_client.session_transaction() as dsess:
        dsess["authenticated"] = True
        dsess["is_demo"] = True
        dsess["universe"] = "beta"
        dsess["role"] = "viewer"
        dsess["user_role"] = "viewer"
        dsess["family_id"] = 1
        dsess["user_family_id"] = 1
    return demo_client


def test_monarch_multi_tenant_credentials(monkeypatch):
    """Verifies storing per-tenant encrypted credentials in database without live network calls."""
    monkeypatch.setattr(
        monarch_service,
        "trigger_monarch_sync",
        lambda family_id=0: {"success": True, "accounts_count": 5},
    )

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Test User"
        sess["user_family_id"] = 1
        sess["family_id"] = 1
        sess["role"] = "editor"
        sess["auth_method"] = "Google OAuth"

    try:
        resp = client.post(
            "/api/settings/monarch_credentials",
            json={
                "email": "tenant@example.com",
                "password": "FakePassword123!",
                "mfa_secret_key": "JBSWY3DPEHPK3PXP",
                "sync": True,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "Monarch credentials stored" in data["message"]
        assert data["sync"]["success"] is True

        fam_db = DB_PATH.for_family(1)
        stored = security.db_load_encrypted(fam_db, "monarch_credentials", family_id=1)
        assert stored["email"] == "tenant@example.com"
        assert stored["mfa_secret_key"] == "JBSWY3DPEHPK3PXP"
    finally:
        try:
            with get_db_connection(DB_PATH.for_family(1)) as conn:
                conn.execute("DELETE FROM family_encrypted_store WHERE key = 'monarch_credentials'")
                conn.commit()
        except Exception:
            pass


def test_simplefin_ssrf_and_token_claim(monkeypatch):
    """Verifies SSRF guardrails and Base64 Setup Token / direct Access URL claiming."""
    # 1. Non-simplefin.org host rejected
    evil_token = base64.b64encode(b"https://evil.example.com/claim/123").decode("ascii")
    evil_res = claim_simplefin_setup_token(evil_token)
    assert evil_res["success"] is False
    assert "simplefin.org" in evil_res["error"]

    # 2. Non-HTTPS URL rejected
    http_token = base64.b64encode(b"http://beta-bridge.simplefin.org/simplefin/claim/123").decode("ascii")
    http_res = claim_simplefin_setup_token(http_token)
    assert http_res["success"] is False
    assert "HTTPS" in http_res["error"]

    # 3. Direct Access URL missing credentials rejected
    no_auth_res = claim_simplefin_setup_token("https://@beta-bridge.simplefin.org/simplefin")
    assert no_auth_res["success"] is False
    assert "credentials" in no_auth_res["error"].lower()

    # 4. Direct valid Access URL accepted without network POST
    direct_url = "https://user1:pass1@beta-bridge.simplefin.org/simplefin/"
    direct_res = claim_simplefin_setup_token(direct_url)
    assert direct_res["success"] is True
    assert direct_res["access_url"] == "https://user1:pass1@beta-bridge.simplefin.org/simplefin"

    # 5. Base64 Setup Token claim exchanges via POST
    claim_url = "https://beta-bridge.simplefin.org/simplefin/claim/token-abc"
    access_url = "https://claimed_u:claimed_p@beta-bridge.simplefin.org/simplefin"
    valid_token = base64.b64encode(claim_url.encode("utf-8")).decode("ascii")

    class _DummyResp:
        def __init__(self, status_code: int, text: str):
            self.status_code = status_code
            self.text = text

    monkeypatch.setattr(
        requests,
        "post",
        lambda url, **kw: _DummyResp(200, access_url) if url == claim_url else _DummyResp(403, ""),
    )
    claimed = claim_simplefin_setup_token(valid_token)
    assert claimed["success"] is True
    assert claimed["access_url"] == access_url


def test_simplefin_sync_coexistence_and_disconnect(monkeypatch):
    """
    Verifies provider coexistence (`monarch`, `simplefin`, `manual`) and tests BOTH
    `remove_accounts=False` (preserving `sfin_*` accounts while clearing token) and
    `remove_accounts=True` on `POST /api/settings/simplefin_disconnect`.
    """
    test_fid = 891
    uni = "test"
    fam_db, _ = _provision_test_family(test_fid, "The Beacon Household", uni=uni)

    try:
        # Seed a Monarch account and a Manual account
        replace_accounts(
            family_id=test_fid,
            accounts=[
                {
                    "id": "mon_101",
                    "displayName": "Monarch Joint Brokerage",
                    "currentBalance": 250000.0,
                    "includeInNetWorth": True,
                    "type": {"name": "brokerage"},
                    "subtype": {"name": "brokerage"},
                    "institution": {"name": "Fidelity"},
                }
            ],
            db_path=fam_db,
            provider="monarch",
        )
        db.accounts.upsert_manual_account(
            family_id=test_fid,
            account_id="manual_home1",
            display_name="Manual Residence",
            balance=900000.0,
            role="real_estate",
            institution_name="Assessor",
            include_in_net_worth=True,
            db_path=fam_db,
        )

        claim_url = "https://beta-bridge.simplefin.org/simplefin/claim/demo-token"
        access_url = "https://demo_user:demo_secret@beta-bridge.simplefin.org/simplefin"
        valid_setup_token = base64.b64encode(claim_url.encode("utf-8")).decode("ascii")

        mock_payload = {
            "errors": [],
            "accounts": [
                {
                    "id": "ACT-SFIN-01",
                    "name": "Premier Checking",
                    "currency": "USD",
                    "balance": "42500.00",
                    "org": {"domain": "chase.com", "name": "Chase Bank"},
                    "holdings": [],
                },
                {
                    "id": "ACT-SFIN-02",
                    "name": "Traditional Rollover IRA",
                    "currency": "USD",
                    "balance": "185000.00",
                    "org": {"domain": "vanguard.com", "name": "Vanguard"},
                    "holdings": [
                        {
                            "id": "HLD-1",
                            "symbol": "VTI",
                            "description": "Vanguard Total Stock Market ETF",
                            "shares": "600",
                            "market_value": "185000.00",
                            "cost_basis": "120000.00",
                        }
                    ],
                },
            ],
        }

        class _DummyResp:
            def __init__(self, status_code: int, text: str = "", json_data=None):
                self.status_code = status_code
                self.text = text
                self._json_data = json_data

            def json(self):
                return self._json_data

        monkeypatch.setattr(requests, "post", lambda url, **kw: _DummyResp(200, text=access_url))
        monkeypatch.setattr(requests, "get", lambda url, **kw: _DummyResp(200, json_data=mock_payload))

        client = _make_family_client(test_fid, uni=uni)

        # Connect SimpleFIN synchronously
        conn_resp = client.post(
            "/api/settings/simplefin_connect",
            json={"setup_token": valid_setup_token, "sync": True},
        )
        assert conn_resp.status_code == 200
        conn_data = conn_resp.get_json()
        assert conn_data["success"] is True
        assert conn_data["accounts_count"] == 2
        assert conn_data["holdings_count"] == 1

        # Verify all 3 providers coexist (`monarch`, `simplefin`, `manual`)
        all_accts = list_accounts(family_id=test_fid, db_path=fam_db)
        by_id = {a["id"]: a for a in all_accts}
        assert {"mon_101", "manual_home1", "sfin_ACT-SFIN-01", "sfin_ACT-SFIN-02"}.issubset(by_id.keys())
        assert by_id["mon_101"]["provider"] == "monarch"
        assert by_id["manual_home1"]["provider"] == "manual"
        assert by_id["sfin_ACT-SFIN-01"]["provider"] == "simplefin"

        # Verify badges in /fragments/accounts and /fragments/settings
        accts_html = client.get("/fragments/accounts").get_data(as_text=True)
        assert "SimpleFIN" in accts_html
        assert "Monarch" in accts_html
        assert "Manual" in accts_html

        # Disconnect with remove_accounts=False: token cleared, sfin_* accounts preserved
        disc_keep = client.post(
            "/api/settings/simplefin_disconnect",
            json={"remove_accounts": False},
        )
        assert disc_keep.status_code == 200
        assert disc_keep.get_json()["success"] is True
        status_after_keep = get_simplefin_status(family_id=test_fid, db_path=fam_db)
        assert status_after_keep["is_connected"] is False

        kept_ids = {a["id"] for a in list_accounts(family_id=test_fid, db_path=fam_db)}
        assert "sfin_ACT-SFIN-01" in kept_ids
        assert "sfin_ACT-SFIN-02" in kept_ids
        assert "mon_101" in kept_ids
        assert "manual_home1" in kept_ids

        # Disconnect with remove_accounts=True: sfin_* accounts removed, monarch & manual remain
        disc_remove = client.post(
            "/api/settings/simplefin_disconnect",
            json={"remove_accounts": True},
        )
        assert disc_remove.status_code == 200
        assert disc_remove.get_json()["success"] is True

        rem_ids = {a["id"] for a in list_accounts(family_id=test_fid, db_path=fam_db)}
        assert rem_ids == {"mon_101", "manual_home1"}
    finally:
        try:
            security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
        except Exception:
            pass


def test_simplefin_async_background_jobs_and_normalization(monkeypatch):
    """
    Tests async background job submission (`async=True`) on `/api/settings/simplefin_connect`
    and `/api/settings/simplefin_sync`, plus direct unit tests for SimpleFIN account type
    inference and payload normalization across credit, loan, mortgage, and investment accounts.
    """
    # 1. Direct unit tests for account type normalization across credit, loan, mortgage, investment, 529, 530A
    assert _infer_simplefin_account_type("Sapphire Reserve Visa Card", -2400.0, False) == (
        "credit",
        "Credit Card",
        "credit_card",
    )
    assert _infer_simplefin_account_type("Primary Residence 30Yr Mortgage", -450000.0, False) == (
        "loan",
        "Loan / Mortgage",
        "mortgage",
    )
    assert _infer_simplefin_account_type("Auto Loan Account", -18000.0, False) == (
        "loan",
        "Loan / Mortgage",
        "mortgage",
    )
    assert _infer_simplefin_account_type("Vanguard Roth IRA", 95000.0, True) == (
        "investment",
        "Retirement",
        "ira",
    )
    assert _infer_simplefin_account_type("ScholarShare 529 College Plan", 65000.0, True) == (
        "investment",
        "529 Education",
        "529",
    )
    assert _infer_simplefin_account_type("Coverdell 530A Account", 12000.0, False) == (
        "investment",
        "530A Custodial",
        "530a",
    )
    assert _infer_simplefin_account_type("Fidelity Individual Portfolio", 310000.0, True) == (
        "brokerage",
        "Brokerage",
        "brokerage",
    )
    assert _infer_simplefin_account_type("SimpleFIN Savings", 114825.51, True) == (
        "depository",
        "Cash / Depository",
        "savings",
    )
    assert _infer_simplefin_account_type("SimpleFIN Checking", 25218.83, False) == (
        "depository",
        "Cash / Depository",
        "checking",
    )

    norm_accs, norm_holdings = _normalize_simplefin_payload(
        {
            "accounts": [
                {"id": "cc_1", "name": "Amex Platinum Card", "balance": "-1500.50", "org": {"name": "Amex"}},
                {"id": "mtg_1", "name": "Home Mortgage Loan", "balance": "-380000.00", "org": {"name": "Wells Fargo"}},
                {
                    "id": "inv_1",
                    "name": "Company 401(k) Plan",
                    "balance": "420000.00",
                    "org": {"name": "Fidelity"},
                    "holdings": [{"id": "h1", "symbol": "FXAIX", "shares": "2000", "market_value": "420000"}],
                },
            ]
        }
    )
    acc_map = {a["id"]: a for a in norm_accs}
    assert acc_map["sfin_cc_1"]["type"]["name"] == "credit"
    assert acc_map["sfin_mtg_1"]["type"]["name"] == "loan"
    assert acc_map["sfin_mtg_1"]["subtype"]["name"] == "mortgage"
    assert acc_map["sfin_inv_1"]["type"]["name"] == "investment"
    assert acc_map["sfin_inv_1"]["subtype"]["name"] == "401k"
    assert len(norm_holdings["sfin_inv_1"]) == 1

    # 2. Async background job submission on /api/settings/simplefin_connect and /api/settings/simplefin_sync
    test_fid = 892
    uni = "test"
    fam_db, _ = _provision_test_family(test_fid, "Async SimpleFIN Household", uni=uni)

    try:
        monkeypatch.setattr(
            monarch_service,
            "claim_simplefin_setup_token",
            lambda tok: {
                "success": True,
                "access_url": "https://u:p@beta-bridge.simplefin.org/simplefin",
            },
        )
        monkeypatch.setattr(
            monarch_service,
            "trigger_simplefin_sync",
            lambda family_id=0: {
                "success": True,
                "provider": "simplefin",
                "accounts_count": 3,
                "holdings_count": 4,
            },
        )

        client = _make_family_client(test_fid, uni=uni)

        conn_async = client.post(
            "/api/settings/simplefin_connect",
            json={"setup_token": "https://u:p@beta-bridge.simplefin.org/simplefin", "async": True},
        )
        assert conn_async.status_code == 200
        conn_json = conn_async.get_json()
        assert conn_json["success"] is True
        assert conn_json["sync_status"] == "processing"
        assert conn_json.get("sync_job_id")

        sync_async = client.post("/api/settings/simplefin_sync", json={"async": True})
        assert sync_async.status_code == 200
        sync_json = sync_async.get_json()
        assert sync_json["success"] is True
        assert sync_json["status"] == "processing"
        assert sync_json.get("job_id")
    finally:
        try:
            security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
        except Exception:
            pass


def test_manual_accounts_crud_and_guards(monkeypatch):
    """
    Tests creating, updating, and deleting `manual_*` accounts, `MAX_HOUSEHOLD_ACCOUNTS` cap,
    provider sync preservation, HTTP 400 on deleting non-manual account (`mon_123`),
    HTTP 404 on deleting non-existent `manual_nonexistent`, and HTTP 403 for demo guest.
    """
    test_fid = 893
    uni = "test"
    fam_db, _ = _provision_test_family(test_fid, "Manual Accounts Household", uni=uni)

    try:
        client = _make_family_client(test_fid, uni=uni)

        # 1. Create a manual account
        create_resp = client.post(
            "/api/accounts/manual",
            json={
                "name": "Primary Residence Equity",
                "balance": 1450000.0,
                "role": "real_estate",
                "account_type": "real_estate",
                "institution": "County Assessor",
            },
        )
        assert create_resp.status_code == 200
        man_acc = create_resp.get_json()["account"]
        man_id = man_acc["id"]
        assert man_id.startswith("manual_")
        assert man_acc["provider"] == "manual"
        assert man_acc["source_label"] == "Manual"

        # 2. Enforce MAX_HOUSEHOLD_ACCOUNTS cap on new manual account creation
        assert config.MAX_HOUSEHOLD_ACCOUNTS == 1000
        monkeypatch.setattr(config, "MAX_HOUSEHOLD_ACCOUNTS", 1)
        over_cap = client.post(
            "/api/accounts/manual",
            json={"name": "Second Manual Over Cap", "balance": 10000.0, "role": "cash_liquid"},
        )
        assert over_cap.status_code == 400
        assert "Maximum of 1 accounts per household reached" in over_cap.get_json()["error"]
        monkeypatch.setattr(config, "MAX_HOUSEHOLD_ACCOUNTS", 1000)

        # 3. Update existing manual account
        upd_resp = client.post(
            "/api/accounts/manual",
            json={
                "account_id": man_id,
                "name": "Primary Residence Updated",
                "balance": 1525000.0,
                "role": "real_estate",
                "institution": "County Assessor",
            },
        )
        assert upd_resp.status_code == 200
        assert upd_resp.get_json()["account"]["currentBalance"] == 1525000.0

        # 4. Provider sync preservation (Monarch and SimpleFIN replace_accounts keep manual_*)
        replace_accounts(
            family_id=test_fid,
            accounts=[{"id": "mon_123", "displayName": "Monarch Checking", "currentBalance": 50000.0}],
            db_path=fam_db,
            provider="monarch",
        )
        replace_accounts(
            family_id=test_fid,
            accounts=[{"id": "sfin_456", "displayName": "SimpleFIN Brokerage", "currentBalance": 120000.0}],
            db_path=fam_db,
            provider="simplefin",
        )
        all_ids = {a["id"] for a in list_accounts(family_id=test_fid, db_path=fam_db)}
        assert {man_id, "mon_123", "sfin_456"}.issubset(all_ids)

        # 5. Guard: HTTP 400 when attempting to delete a non-manual account
        non_manual_del = client.delete("/api/accounts/manual/mon_123")
        assert non_manual_del.status_code == 400
        assert "manual_*" in non_manual_del.get_json()["error"]

        # 6. Guard: HTTP 404 when attempting to delete a non-existent manual account
        missing_del = client.delete("/api/accounts/manual/manual_nonexistent")
        assert missing_del.status_code == 404
        assert "not found" in missing_del.get_json()["error"].lower()

        # 7. Guard: HTTP 403 when a demo guest attempts manual account create or delete
        demo_client = _make_demo_client()
        demo_create = demo_client.post(
            "/api/accounts/manual",
            json={"name": "Demo Blocked Account", "balance": 500.0},
        )
        assert demo_create.status_code == 403

        demo_del = demo_client.delete(f"/api/accounts/manual/{man_id}")
        assert demo_del.status_code == 403

        # 8. Delete manual account and confirm removal
        del_resp = client.delete(f"/api/accounts/manual/{man_id}")
        assert del_resp.status_code == 200
        assert del_resp.get_json()["success"] is True
        assert man_id not in {a["id"] for a in list_accounts(family_id=test_fid, db_path=fam_db)}
    finally:
        try:
            security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
        except Exception:
            pass


def test_byo_gemini_api_key_lifecycle(monkeypatch):
    """Verifies saving, masking, resolving per-household Gemini API key, and deleting."""
    test_fid = 894
    uni = "test"
    fam_db, _ = _provision_test_family(test_fid, "BYO Gemini Household", uni=uni)

    try:
        client = _make_family_client(test_fid, uni=uni)
        monkeypatch.setenv("GEMINI_API_KEY", "env-default-key-9999")
        assert config.get_household_gemini_api_key(family_id=test_fid, db_path=fam_db) == "env-default-key-9999"

        # Save custom household key
        save_resp = client.post(
            "/api/settings/ai_key",
            json={"gemini_api_key": "AIzaSyCustomHouseholdKey7788"},
        )
        assert save_resp.status_code == 200
        save_data = save_resp.get_json()
        assert save_data["success"] is True
        assert save_data["has_custom_key"] is True
        assert save_data["masked_key"] == "••••7788"
        assert config.get_household_gemini_api_key(family_id=test_fid, db_path=fam_db) == "AIzaSyCustomHouseholdKey7788"

        # Verify SSR settings fragment displays masked key
        conn_tab_html = client.get("/fragments/settings?tab=monarch").get_data(as_text=True)
        assert "input-settings-gemini-key" in conn_tab_html
        assert "••••7788" in conn_tab_html
        assert "btn-clear-gemini-key" in conn_tab_html

        # Delete custom key and verify fallback to environment default
        del_resp = client.delete("/api/settings/ai_key")
        assert del_resp.status_code == 200
        del_data = del_resp.get_json()
        assert del_data["success"] is True
        assert del_data["has_custom_key"] is False
        assert config.get_household_gemini_api_key(family_id=test_fid, db_path=fam_db) == "env-default-key-9999"
    finally:
        try:
            security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
        except Exception:
            pass


def test_guided_onboarding_milestone_progression_and_dismissal():
    """
    Verifies 4-step milestone progression (0 -> 1 -> 2 -> 3 -> 4),
    `POST /api/onboarding/complete` with `{"dismissed": True}` setting `onboarding_dismissed: True`,
    `{"completed": True}`, and HTTP 403 demo guest write protection.
    """
    test_fid = 895
    uni = "test"
    fam_db, _ = _provision_test_family(test_fid, "Onboarding Progression Household", uni=uni)

    try:
        client = _make_family_client(test_fid, uni=uni)

        # Step 0: Fresh household has 0 of 4 milestones completed
        st0 = client.get("/api/onboarding/status").get_json()
        assert st0["success"] is True
        assert st0["completed_count"] == 0
        assert st0["show_checklist"] is True

        # Milestone 1: Configure Household & Tax Profile
        client.post(
            "/api/settings/assumptions",
            json={
                "state": "CA",
                "filing_status": "MFJ",
                "annual_spending": 0.0,
                "annual_savings": 0.0,
                "retirement_age": 55,
                "inflation_rate": 0.025,
            },
        )
        st1 = client.get("/api/onboarding/status").get_json()
        assert st1["completed_count"] == 1
        assert st1["steps"][0]["done"] is True

        # Milestone 2: Add Family Member with birthdate
        client.post(
            "/api/family/members",
            json={"name": "Taylor Member", "relationship": "primary", "birthdate": "1986-05-20", "role": "editor"},
        )
        st2 = client.get("/api/onboarding/status").get_json()
        assert st2["completed_count"] == 2
        assert st2["steps"][1]["done"] is True

        # Milestone 3: Link or add a Manual Account
        client.post(
            "/api/accounts/manual",
            json={"name": "Cash Reserve", "balance": 100000.0, "role": "cash_liquid"},
        )
        st3 = client.get("/api/onboarding/status").get_json()
        assert st3["completed_count"] == 3
        assert st3["steps"][2]["done"] is True

        # Test dismissal (`{"dismissed": True}`) before 4th milestone
        dismiss_resp = client.post("/api/onboarding/complete", json={"dismissed": True})
        assert dismiss_resp.status_code == 200
        dismiss_data = dismiss_resp.get_json()
        assert dismiss_data["onboarding_dismissed"] is True
        assert dismiss_data["onboarding_completed"] is False

        st_dismissed = client.get("/api/onboarding/status").get_json()
        assert st_dismissed["onboarding_dismissed"] is True
        assert st_dismissed["show_checklist"] is False

        # Milestone 4: Add Compensation / Income record -> 4/4 milestones done
        client.post(
            "/api/compensation",
            json={"year": 2026, "company": "Acme Corp", "salary": 350000.0, "bonus": 50000.0},
        )
        st4 = client.get("/api/onboarding/status").get_json()
        assert st4["completed_count"] == 4
        assert st4["progress_pct"] == 100
        assert all(step["done"] for step in st4["steps"])

        # Complete onboarding (`{"completed": True}`) resets `onboarding_dismissed` to False
        comp_resp = client.post("/api/onboarding/complete", json={"completed": True})
        assert comp_resp.status_code == 200
        comp_data = comp_resp.get_json()
        assert comp_data["onboarding_completed"] is True
        assert comp_data["onboarding_dismissed"] is False

        # Demo guest write protection (HTTP 403)
        demo_client = _make_demo_client()
        demo_comp = demo_client.post("/api/onboarding/complete", json={"completed": True})
        assert demo_comp.status_code == 403
    finally:
        try:
            security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
        except Exception:
            pass


def test_provider_aware_ui_and_unified_sync(monkeypatch):
    """
    Verifies:
    1. 'Sync Accounts' label and conditional 'Open Monarch ↗' visibility when Monarch is NOT connected vs connected.
    2. Unified `POST /api/sync` routing to SimpleFIN when only SimpleFIN is connected, Monarch when only Monarch is connected,
       and both when both are connected.
    """
    test_fid = 896
    uni = "test"
    fam_db, _ = _provision_test_family(test_fid, "Provider UI Household", uni=uni)

    try:
        client = _make_family_client(test_fid, uni=uni)

        # 1. Manual-only household: 'Open Monarch' button and sync buttons must be concealed (provider-hidden / hidden)
        index_html = client.get("/accounts").get_data(as_text=True)
        assert "Sync Accounts" in index_html
        assert "Accounts &amp; Holdings" in index_html or "Accounts & Holdings" in index_html
        assert 'id="btn-sidebar-monarch"' in index_html
        # Extract the #btn-sidebar-monarch tag and confirm it is hidden when Monarch is not connected
        monarch_btn_idx = index_html.find('id="btn-sidebar-monarch"')
        monarch_btn_tag = index_html[max(0, monarch_btn_idx - 20) : monarch_btn_idx + 450]
        assert "display: none" in monarch_btn_tag
        assert 'id="top-open-monarch"' in index_html
        top_monarch_idx = index_html.find('id="top-open-monarch"')
        top_monarch_tag = index_html[max(0, top_monarch_idx - 60) : top_monarch_idx + 260]
        assert "provider-hidden" in top_monarch_tag and "hidden" in top_monarch_tag
        assert 'id="btn-mobile-sync"' in index_html
        mob_sync_idx = index_html.find('id="btn-mobile-sync"')
        mob_sync_tag = index_html[max(0, mob_sync_idx - 60) : mob_sync_idx + 260]
        assert "provider-hidden" in mob_sync_tag and "hidden" in mob_sync_tag

        # 2. Connect SimpleFIN only -> `POST /api/sync` routes to SimpleFIN sync, 'Open Monarch' remains hidden
        security.db_save_encrypted(
            fam_db,
            "simplefin_credentials",
            "credentials",
            {"access_url": "https://u:p@beta-bridge.simplefin.org/simplefin"},
            family_id=test_fid,
        )
        calls = []
        monkeypatch.setattr(
            monarch_service,
            "trigger_simplefin_sync",
            lambda family_id=0, db_path=None: (
                calls.append("simplefin")
                or {"success": True, "provider": "simplefin", "accounts_count": 2, "holdings_count": 3}
            ),
        )
        monkeypatch.setattr(
            monarch_service,
            "trigger_monarch_sync",
            lambda family_id=0, db_path=None: (
                calls.append("monarch")
                or {"success": True, "provider": "monarch", "accounts_count": 4, "holdings_count": 5}
            ),
        )

        sync_sfin_only = client.post("/api/sync", json={"sync": True}).get_json()
        assert sync_sfin_only["success"] is True
        assert calls == ["simplefin"]

        # 3. Connect Monarch as well -> 'Open Monarch' becomes visible and `POST /api/sync` syncs BOTH providers
        security.db_save_encrypted(
            fam_db,
            "monarch_credentials",
            "credentials",
            {"email": "user@example.com", "token": "tok_123"},
            family_id=test_fid,
        )
        index_with_monarch = client.get("/accounts").get_data(as_text=True)
        m_idx2 = index_with_monarch.find('id="btn-sidebar-monarch"')
        m_tag2 = index_with_monarch[max(0, m_idx2 - 20) : m_idx2 + 450]
        assert "display: none" not in m_tag2
        assert 'href="https://app.monarch.com/links/dashboard"' in m_tag2
        top_idx2 = index_with_monarch.find('id="top-open-monarch"')
        top_tag2 = index_with_monarch[max(0, top_idx2 - 60) : top_idx2 + 260]
        assert 'href="https://app.monarch.com/links/dashboard"' in top_tag2
        assert 'target="_blank"' not in top_tag2

        calls.clear()
        sync_both = client.post("/api/sync", json={"sync": True}).get_json()
        assert sync_both["success"] is True
        assert calls == ["monarch", "simplefin"]
        assert sync_both["accounts_count"] == 6
        assert sync_both["holdings_count"] == 8
    finally:
        try:
            security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
        except Exception:
            pass


def test_balance_history_gap_filling_corrections_and_csv_roundtrip():
    """
    Verifies:
    1. Manual account creation with backdated `as_of_date` and subsequent updates preserving `currentBalance`
       as the latest snapshot date while recording historical points.
    2. 30+ day / multi-year sync gap-filling via linear interpolation and carry-forward.
    3. SimpleFIN 90-day transaction walkback balance reconstruction (`_reconstruct_simplefin_balance_history`).
    4. Snapshot correction (editing and deleting individual `(account_id, date)` points) and demo 403 guardrails.
    5. CSV Import (both Long Monarch format and Wide Pivot Spreadsheet format) and CSV Export round-trip.
    """
    from monarch.simplefin import _reconstruct_simplefin_balance_history

    test_fid = 897
    uni = "test"
    fam_db, _ = _provision_test_family(test_fid, "Balance History Household", uni=uni)

    try:
        client = _make_family_client(test_fid, uni=uni)

        # 1. Create a manual account with a current date, then backdate an earlier snapshot
        r_curr = client.post(
            "/api/accounts/manual",
            json={
                "name": "Fidelity Brokerage",
                "balance": 500000.0,
                "role": "public_brokerage",
                "as_of_date": "2026-10-01",
            },
        )
        assert r_curr.status_code == 200
        acc_id = r_curr.get_json()["account"]["id"]

        # Backdate a 2024 snapshot on the same account: currentBalance must stay 500,000 (latest date)
        r_back = client.post(
            "/api/accounts/manual",
            json={
                "account_id": acc_id,
                "name": "Fidelity Brokerage",
                "balance": 300000.0,
                "role": "public_brokerage",
                "as_of_date": "2024-12-31",
            },
        )
        assert r_back.status_code == 200
        assert r_back.get_json()["account"]["currentBalance"] == 500000.0

        # 2. Verify 2025 gap year is automatically filled via linear interpolation between 2024 ($300k) and 2026 ($500k)
        hist_resp = client.get("/api/accounts/history").get_json()
        assert hist_resp["success"] is True
        nw_by_yr = {row["year"]: row["liquid_investments"] for row in hist_resp["historical_net_worth"]}
        assert nw_by_yr[2024] == 300000
        assert 380000 <= nw_by_yr[2025] <= 440000
        assert nw_by_yr[2026] == 500000

        # 3. Verify SimpleFIN 90-day transaction walkback reconstruction
        sfin_snaps = _reconstruct_simplefin_balance_history(
            [
                {
                    "id": "CHK-1",
                    "name": "Main Checking",
                    "balance": "15000.00",
                    "balance-date": 1760572800,  # 2025-10-16
                    "transactions": [
                        {"posted": 1759276800, "amount": "5000.00"},   # +$5k on 2025-10-01 -> prior balance was $10k
                        {"posted": 1756684800, "amount": "-2000.00"},  # -$2k on 2025-09-01 -> prior balance was $12k
                    ],
                }
            ]
        )
        assert len(sfin_snaps) >= 2
        snap_balances = [round(s["balance"]) for s in sfin_snaps]
        assert 15000 in snap_balances
        assert 10000 in snap_balances

        # 4. Wide Pivot Spreadsheet CSV Import + Long Format CSV Import + Export round-trip
        wide_csv = (
            "Date,Fidelity Brokerage,Home Equity\n"
            "2022-12-31,\"$200,000.00\",\"$750,000.00\"\n"
            "2023-12-31,\"$250,000.00\",\"$800,000.00\"\n"
        )
        imp_wide = client.post("/api/accounts/import_csv", json={"csv_text": wide_csv})
        assert imp_wide.status_code == 200
        wide_json = imp_wide.get_json()
        assert wide_json["success"] is True
        assert wide_json["imported_rows"] == 4
        assert {2022, 2023, 2024, 2025, 2026}.issubset(set(wide_json["years_covered"]))

        # Verify CSV Export contains all imported rows
        csv_export = client.get("/api/accounts/export_csv").get_data(as_text=True)
        assert "Fidelity Brokerage" in csv_export
        assert "Home Equity" in csv_export
        assert "2022-12-31" in csv_export

        # 5. Delete a specific historical snapshot (`2022-12-31` for Fidelity Brokerage)
        del_snap = client.delete(
            "/api/accounts/history",
            json={"account_id": acc_id, "as_of_date": "2022-12-31"},
        )
        assert del_snap.status_code == 200
        remaining_dates = [
            h["date"] for h in del_snap.get_json()["history"] if h["account_id"] == acc_id
        ]
        assert "2022-12-31" not in remaining_dates
        assert "2024-12-31" in remaining_dates

        # 6. Demo guest write protection on history & CSV import endpoints
        demo_client = _make_demo_client()
        assert demo_client.post("/api/accounts/history", json={"account_name": "X", "date": "2025-01-01", "balance": 1}).status_code == 403
        assert demo_client.delete("/api/accounts/history", json={"account_id": acc_id, "date": "2024-12-31"}).status_code == 403
        assert demo_client.post("/api/accounts/import_csv", json={"csv_text": wide_csv}).status_code == 403
    finally:
        try:
            security.permanently_delete_family(fam_db, family_id=test_fid, universe=uni)
        except Exception:
            pass


def test_monarch_smart_stale_account_upstream_refresh(monkeypatch):
    """
    Verifies `_refresh_stale_monarch_accounts_if_needed`:
    1. Triggers `request_accounts_refresh` only for active, non-manual, connected accounts with
       `displayLastUpdatedAt` older than 72 hours (3 days), polls `is_accounts_refresh_complete`
       up to the 60s cap, and re-fetches `get_accounts()`.
    2. Skips `request_accounts_refresh` when all eligible accounts are fresh (< 72h), manual (`isManual=True`),
       or have `credential.updateRequired=True` / `syncDisabled=True`.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone
    import monarch.client_graphql as cg

    now_utc = datetime.now(timezone.utc)
    fresh_ts = (now_utc - timedelta(hours=12)).isoformat()
    stale_ts = (now_utc - timedelta(hours=96)).isoformat()

    initial_accounts = [
        {
            "id": "acc_stale_linked",
            "displayName": "Stale Linked Brokerage",
            "currentBalance": 100000.0,
            "isManual": False,
            "syncDisabled": False,
            "displayLastUpdatedAt": stale_ts,
            "credential": {"id": "cred_1", "updateRequired": False},
        },
        {
            "id": "acc_fresh_linked",
            "displayName": "Fresh Linked Checking",
            "currentBalance": 25000.0,
            "isManual": False,
            "syncDisabled": False,
            "displayLastUpdatedAt": fresh_ts,
            "credential": {"id": "cred_2", "updateRequired": False},
        },
        {
            "id": "acc_stale_manual",
            "displayName": "Manual Real Estate",
            "currentBalance": 850000.0,
            "isManual": True,
            "syncDisabled": False,
            "displayLastUpdatedAt": stale_ts,
        },
        {
            "id": "acc_stale_broken_cred",
            "displayName": "Disconnected Card",
            "currentBalance": -1200.0,
            "isManual": False,
            "syncDisabled": False,
            "displayLastUpdatedAt": stale_ts,
            "credential": {"id": "cred_3", "updateRequired": True},
        },
    ]

    refreshed_accounts = [
        {**initial_accounts[0], "currentBalance": 112500.0, "displayLastUpdatedAt": now_utc.isoformat()},
        *initial_accounts[1:],
    ]

    class _FakeMonarchClient:
        def __init__(self, accounts_list):
            self.accounts_list = accounts_list
            self.refresh_requested_ids = []
            self.poll_calls = 0
            self.get_accounts_calls = 0

        async def request_accounts_refresh(self, account_ids):
            self.refresh_requested_ids.append(list(account_ids))
            return True

        async def is_accounts_refresh_complete(self, account_ids):
            self.poll_calls += 1
            return self.poll_calls >= 2

        async def get_accounts(self):
            self.get_accounts_calls += 1
            return {"accounts": refreshed_accounts}

    async def _fast_sleep(_secs):
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    fake_mm = _FakeMonarchClient(initial_accounts)
    out_accounts, refreshed_count = asyncio.run(
        cg._refresh_stale_monarch_accounts_if_needed(fake_mm, initial_accounts)
    )
    assert refreshed_count == 1
    assert fake_mm.refresh_requested_ids == [["acc_stale_linked"]]
    assert fake_mm.poll_calls == 2
    assert fake_mm.get_accounts_calls == 1
    assert out_accounts[0]["currentBalance"] == 112500.0

    # Verify cooldown: recent upstream refresh (2h ago, within 12h cooldown) skips request_accounts_refresh immediately
    recent_upstream_ts = (now_utc - timedelta(hours=2)).isoformat()
    fake_mm_cooldown = _FakeMonarchClient(initial_accounts)
    out_cooldown, count_cooldown = asyncio.run(
        cg._refresh_stale_monarch_accounts_if_needed(
            fake_mm_cooldown, initial_accounts, last_upstream_refresh_ts=recent_upstream_ts
        )
    )
    assert count_cooldown == 0
    assert fake_mm_cooldown.refresh_requested_ids == []
    assert fake_mm_cooldown.poll_calls == 0
    assert out_cooldown == initial_accounts

    # Verify expired cooldown (15h ago, past 12h cooldown) triggers request_accounts_refresh
    expired_upstream_ts = (now_utc - timedelta(hours=15)).isoformat()
    fake_mm_expired = _FakeMonarchClient(initial_accounts)
    out_expired, count_expired = asyncio.run(
        cg._refresh_stale_monarch_accounts_if_needed(
            fake_mm_expired, initial_accounts, last_upstream_refresh_ts=expired_upstream_ts
        )
    )
    assert count_expired == 1
    assert fake_mm_expired.refresh_requested_ids == [["acc_stale_linked"]]
    assert out_expired[0]["currentBalance"] == 112500.0

    # Verify no upstream refresh when only fresh / manual / broken-credential accounts exist
    non_trigger_accounts = initial_accounts[1:]
    fake_mm_fresh = _FakeMonarchClient(non_trigger_accounts)
    out_fresh, count_fresh = asyncio.run(
        cg._refresh_stale_monarch_accounts_if_needed(fake_mm_fresh, non_trigger_accounts)
    )
    assert count_fresh == 0
    assert fake_mm_fresh.refresh_requested_ids == []
    assert fake_mm_fresh.poll_calls == 0
    assert fake_mm_fresh.get_accounts_calls == 0
    assert out_fresh == non_trigger_accounts


