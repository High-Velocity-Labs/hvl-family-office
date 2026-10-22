"""
Tests for the Pane Bug Reporter, Deterministic PII/Numeric Anonymizer,
AI Calculation Triage, Rate Limiting, and Site-Admin Bug Queue.
"""

from __future__ import annotations

import pytest
from app import app
import db
from services.bug_reporter_service import (
    VALID_CATEGORIES,
    VALID_PANES,
    collect_and_anonymize_pane_state,
    format_antigravity_prompt,
    run_bug_triage_analysis,
    scrub_explanatory_text,
)


def test_scrub_explanatory_text_anonymizes_pii_and_scales_currency():
    """Verifies that free-form explanatory text scrubs names, emails, employers, and scales dollar figures."""
    token_map = {
        "Patagonia": "Employer_1",
        "Jordan": "Member_1",
        "Vanguard Brokerage": "Account_1",
    }
    raw_text = (
        "Jordan's RSU grant at Patagonia in Vanguard Brokerage shows $100,000 vs $150k "
        "(Delta: $+50,000 or -$20,000)! Contact jordan@example.com for details."
    )
    scrubbed = scrub_explanatory_text(raw_text, token_map=token_map, scale_factor=0.5, max_length=500)

    assert "Jordan" not in scrubbed
    assert "Patagonia" not in scrubbed
    assert "Vanguard Brokerage" not in scrubbed
    assert "jordan@example.com" not in scrubbed
    assert "$100,000" not in scrubbed
    assert "$150k" not in scrubbed
    assert "50,000" not in scrubbed.replace("$50,000 (scaled)", "")

    assert "Member_1" in scrubbed
    assert "Employer_1" in scrubbed
    assert "Account_1" in scrubbed
    assert "[redacted-email]" in scrubbed
    assert "$50,000 (scaled) vs $75,000 (scaled)" in scrubbed
    assert "+$25,000 (scaled)" in scrubbed
    assert "-$10,000 (scaled)" in scrubbed


def test_explanatory_text_length_bounded():
    """Verifies that overly long explanatory notes ('novels') are strictly truncated to max_length."""
    long_note = "A" * 1200
    scrubbed_desc = scrub_explanatory_text(long_note, token_map={}, scale_factor=0.6, max_length=500)
    scrubbed_followup = scrub_explanatory_text(long_note, token_map={}, scale_factor=0.6, max_length=400)
    assert len(scrubbed_desc) == 500
    assert len(scrubbed_followup) == 400


def test_pane_manifests_and_anonymization_modes(tmp_path):
    """Verifies all 12 panes have manifests and support isomorphic scaling vs statutory delta modes."""
    test_db = tmp_path / "fam_test.db"
    for pane in VALID_PANES:
        snapshot, token_map, k, mode = collect_and_anonymize_pane_state(
            family_id=0,
            pane=pane,
            db_path=test_db,
            scale_factor=0.64,
            client_context={"viewport": "1440x900", "recent_errors": [{"path": "/api/equity", "status": 500}]},
        )
        assert snapshot["pane"] == pane
        assert k == 0.64
        if pane in ("compensation", "arbitrage", "estate"):
            assert mode == "statutory_delta"
        else:
            assert mode == "isomorphic_scale"


def test_bug_reporter_auth_and_demo_guardrails(tmp_path, monkeypatch):
    """
    Verifies that:
    - Unauthenticated visitors receive 401 on /api/bugs/* and 302 on /admin/bugs.
    - Read-only Demo Guests receive 403 Forbidden on /api/bugs/analyze and /api/bugs/submit.
    - Authenticated Household Viewers (e.g., spouse/child with viewer role) CAN analyze & submit bugs.
    - Ephemeral Sandbox sessions CAN analyze & submit bugs without uploading a .fovault.
    """
    bugs_db = tmp_path / "global_bugs.db"
    monkeypatch.setattr("db.bugs.resolve_bugs_db_path", lambda: bugs_db)
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. Unauthenticated -> 401 / 302
        r_unauth_analyze = client.post("/api/bugs/analyze", json={"pane": "equity", "description": "Math off"})
        assert r_unauth_analyze.status_code == 401
        r_unauth_submit = client.post("/api/bugs/submit", json={"pane": "equity", "description": "Math off"})
        assert r_unauth_submit.status_code == 401
        r_unauth_admin = client.get("/admin/bugs")
        assert r_unauth_admin.status_code in (302, 403)

        # 2. Demo Guest -> 403 Forbidden
        with client.session_transaction() as sess:
            sess.clear()
            sess["authenticated"] = True
            sess["is_demo"] = True
            sess["universe"] = "demo"
            sess["family_id"] = 1
            sess["role"] = "viewer"

        r_demo_analyze = client.post("/api/bugs/analyze", json={"pane": "overview", "description": "Test"})
        assert r_demo_analyze.status_code == 403
        r_demo_submit = client.post("/api/bugs/submit", json={"pane": "overview", "description": "Test"})
        assert r_demo_submit.status_code == 403

        # 3. Real Authenticated Household Member with 'viewer' role -> 200 OK
        with client.session_transaction() as sess:
            sess.clear()
            sess["authenticated"] = True
            sess["is_demo"] = False
            sess["universe"] = "public"
            sess["user_email"] = "viewer_member@example.com"
            sess["user_id"] = 7
            sess["family_id"] = 3
            sess["user_family_id"] = 3
            sess["role"] = "viewer"
            sess["user_role"] = "viewer"

        r_viewer_analyze = client.post(
            "/api/bugs/analyze",
            json={
                "pane": "equity",
                "category": "math",
                "description": "My RSU vest shows $200,000 instead of $240,000 for viewer_member@example.com",
                "scale_factor": 0.5,
                "client_context": {"client_version": "0000000-1700000000"},
            },
        )
        assert r_viewer_analyze.status_code == 200
        analyze_data = r_viewer_analyze.get_json()
        assert analyze_data["success"] is True
        assert analyze_data["scale_factor"] == 0.5
        assert "viewer_member@example.com" not in analyze_data["scrubbed_description"]
        assert "$100,000 (scaled)" in analyze_data["scrubbed_description"]
        assert "$120,000 (scaled)" in analyze_data["scrubbed_description"]
        assert analyze_data["session_envelope"]["family_id"] == 3
        assert analyze_data["session_envelope"]["user_role"] == "viewer"
        assert analyze_data["session_envelope"]["universe"] == "public"
        assert analyze_data["session_envelope"]["app_instance"] in ("finances", "finances-beta", "finances-local")
        assert "[client: 0000000]" in analyze_data["session_envelope"]["app_version"]
        assert "equity_engine.py" in analyze_data["suspected_module"]

        r_viewer_submit = client.post(
            "/api/bugs/submit",
            json={
                "pane": "equity",
                "category": "math",
                "description": "My RSU vest shows $200,000 instead of $240,000",
                "followup_notes": "Still off by $40,000 even after checking state tax.",
                "scale_factor": 0.5,
            },
        )
        assert r_viewer_submit.status_code == 200
        submit_data = r_viewer_submit.get_json()
        assert submit_data["success"] is True
        bug_id_1 = submit_data["bug_id"]
        assert bug_id_1 >= 1
        assert submit_data["report"]["universe"] == "public"
        assert submit_data["report"]["app_version"].startswith("finances")
        assert submit_data["report"]["scale_factor"] is None
        assert "0.5x" not in submit_data["diagnostic_bundle"]
        assert "Scale Factor" not in submit_data["diagnostic_bundle"]
        assert "**Anonymization**:" in submit_data["diagnostic_bundle"]
        assert "**App Version**:" in submit_data["diagnostic_bundle"]
        assert submit_data["report"]["sanitized_snapshot"]["anonymization_mode"] == "isomorphic_scale"
        assert submit_data["report"]["sanitized_snapshot"]["universe"] == "public"
        assert "uid#7 (viewer)" in submit_data["report"]["sanitized_snapshot"]["user_ref"]

        # 4. Interactive Ephemeral Sandbox User -> 200 OK (no .fovault upload required)
        with client.session_transaction() as sess:
            sess.clear()
            sess["authenticated"] = True
            sess["is_sandbox"] = True
            sess["is_demo"] = False
            sess["universe"] = "sandbox"
            sess["family_id"] = 42
            sess["user_family_id"] = 42
            sess["role"] = "editor"

        r_sb_submit = client.post(
            "/api/bugs/submit",
            json={
                "pane": "scenarios",
                "category": "math",
                "description": "Monte Carlo depletion age looks off with $1,000,000 portfolio",
                "scale_factor": 0.75,
            },
        )
        assert r_sb_submit.status_code == 200
        sb_data = r_sb_submit.get_json()
        assert sb_data["success"] is True
        assert sb_data["report"]["universe"] == "sandbox"
        assert "sandbox#42" in sb_data["report"]["user_ref"]
        assert "$750,000 (scaled)" in sb_data["report"]["scrubbed_description"]


def test_site_admin_bug_queue_and_status_lifecycle(tmp_path, monkeypatch):
    """Verifies Site-Admin access to /admin/bugs, /api/admin/bugs, and status updates."""
    bugs_db = tmp_path / "global_admin_bugs.db"
    monkeypatch.setattr("db.bugs.resolve_bugs_db_path", lambda: bugs_db)
    app.config["TESTING"] = True

    bug_id = db.bugs.insert_bug_report(
        db_path=bugs_db,
        universe="public",
        family_id=2,
        user_role="editor",
        user_ref="uid#5 (editor)",
        support_access_enabled=1,
        pane="compensation",
        category="math",
        scrubbed_description="W-2 Box 1 mismatch of $10,000 (scaled)",
        scrubbed_followup="Confirmed YTD toggle is off.",
        ai_explanation="Checked W-2 aggregation rules.",
        suspected_module="tax_engine.py :: calculate_tax_projection",
        invariant_summary="Expected Box 1 sum to match taxable wages.",
        scale_factor=0.65,
        anonymization_mode="statutory_delta",
        sanitized_snapshot_json='{"pane": "compensation"}',
    )

    with app.test_client() as client:
        # Non-admin user (Family 2 editor) is rejected with 403
        with client.session_transaction() as sess:
            sess.clear()
            sess["authenticated"] = True
            sess["is_demo"] = False
            sess["universe"] = "public"
            sess["user_email"] = "regular_user@example.com"
            sess["family_id"] = 2
            sess["user_family_id"] = 2
            sess["role"] = "editor"

        assert client.get("/admin/bugs").status_code == 403
        assert client.get("/api/admin/bugs").status_code == 403
        assert client.post(f"/api/admin/bugs/{bug_id}/status", json={"status": "resolved"}).status_code == 403

        # Site Admin (Family 1 admin in public universe) succeeds
        with client.session_transaction() as sess:
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["role"] = "admin"
            sess["user_role"] = "admin"

        r_html = client.get("/admin/bugs")
        assert r_html.status_code == 200
        html_text = r_html.get_data(as_text=True)
        assert f"BUG #{bug_id}" in html_text
        assert "W-2 Box 1 mismatch" in html_text
        assert "Copy AI Triage Prompt" in html_text
        assert "HVL Family Office" in html_text
        assert "HVL Family Office (Beta)" in html_text
        assert "All Apps" in html_text

        # Filter by project=finances returns 1, project=finances-beta returns 0, project=ff returns 0
        r_proj_fin = client.get("/api/admin/bugs?project=finances").get_json()
        assert len(r_proj_fin["reports"]) == 1
        assert r_proj_fin["counts"]["active"] == 1
        assert r_proj_fin["counts"]["by_project"]["all"] == 1
        assert r_proj_fin["counts"]["by_project"]["finances"] == 1
        assert r_proj_fin["counts"]["by_project"]["finances-beta"] == 0
        r_proj_ff = client.get("/api/admin/bugs?project=ff").get_json()
        assert len(r_proj_ff["reports"]) == 0

        r_json = client.get("/api/admin/bugs")
        assert r_json.status_code == 200
        j = r_json.get_json()
        assert j["counts"]["total"] == 1
        assert j["counts"]["active"] == 1
        assert j["counts"]["open"] == 1
        assert "### Bug Report #" in j["reports"][0]["antigravity_prompt"]

        # Update status to investigating -> still counts as active in project pills
        r_inv = client.post(
            f"/api/admin/bugs/{bug_id}/status",
            json={"status": "investigating", "admin_notes": "Checking W-2 rules"},
        )
        assert r_inv.status_code == 200
        j_inv = client.get("/api/admin/bugs").get_json()
        assert j_inv["counts"]["active"] == 1
        assert j_inv["counts"]["by_project"]["all"] == 1
        assert j_inv["counts"]["by_project"]["finances"] == 1

        # Update status to resolved -> no longer contributes to active or by_project counts
        r_upd = client.post(
            f"/api/admin/bugs/{bug_id}/status",
            json={"status": "resolved", "admin_notes": "Fixed in tax_engine.py"},
        )
        assert r_upd.status_code == 200
        updated = db.bugs.get_bug_report(bug_id, db_path=bugs_db)
        assert updated is not None
        assert updated["status"] == "resolved"
        assert updated["admin_notes"] == "Fixed in tax_engine.py"

        j_res = client.get("/api/admin/bugs").get_json()
        assert j_res["counts"]["total"] == 1
        assert j_res["counts"]["active"] == 0
        assert j_res["counts"]["by_project"]["all"] == 0
        assert j_res["counts"]["by_project"]["finances"] == 0

        r_html_after = client.get("/admin/bugs").get_data(as_text=True)
        assert "All Apps (0)" in r_html_after
        assert "HVL Family Office (0)" in r_html_after


def test_bug_reporter_rate_limiting(tmp_path, monkeypatch):
    """Verifies that rapid bug analysis/submission triggers 429 Too Many Requests."""
    bugs_db = tmp_path / "global_rl_bugs.db"
    monkeypatch.setattr("db.bugs.resolve_bugs_db_path", lambda: bugs_db)
    app.config["TESTING"] = True
    app.config["TEST_BUG_RATE_LIMIT"] = True

    from hvl_common.web.rate_limit import _default_limiter
    _default_limiter.reset()

    try:
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["is_demo"] = False
                sess["universe"] = "public"
                sess["family_id"] = 2
                sess["user_family_id"] = 2
                sess["role"] = "editor"

            statuses = []
            for i in range(12):
                resp = client.post(
                    "/api/bugs/analyze",
                    json={"pane": "overview", "category": "math", "description": f"Check #{i}"},
                )
                statuses.append(resp.status_code)

            assert 200 in statuses
            assert 429 in statuses
    finally:
        app.config["TEST_BUG_RATE_LIMIT"] = False
        _default_limiter.reset()
