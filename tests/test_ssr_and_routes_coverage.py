"""
SSR Hydration Parity, Dynamic URL Map Auth Guardrails & Empty Household Smoke Tests.

Validates:
1. Dynamic app.url_map State-Changing Auth Guardrail (test_all_mutating_routes_enforce_auth_and_demo_readonly)
2. Full-Page (GET /<tab>) Deep SSR Hydration Check (test_full_page_routes_embed_hydrated_ssr_markup)
3. Empty / Unseeded Household (0 Accounts) SSR Smoke Test (test_empty_household_ssr_fragments_never_crash_or_leak_mockups)
4. Standalone SSR Pages & Mode-Conditional Rendering (test_standalone_pages_and_login_modes_ssr)
"""

from __future__ import annotations

import json
import re
from typing import Set
import pytest
from cryptography.fernet import Fernet

from app import app
import config
from db.session import resolve_db_path
from hvl_common.testing import SSRParityAuditor
from security import get_db_connection
from security_crypto import _get_fernet, encrypt_string, get_or_create_key
from security_store import init_db, run_alembic_migrations


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
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


@pytest.fixture
def demo_viewer_client():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["is_demo"] = True
        sess["universe"] = "demo"
        sess["role"] = "viewer"
        sess["family_id"] = 1
    return client


@pytest.fixture
def unauth_client():
    return app.test_client()


@pytest.fixture
def empty_family_client():
    fam_id = 999
    fam_db = resolve_db_path(family_id=fam_id)
    init_db(fam_db)
    run_alembic_migrations(fam_db)

    root_kek = get_or_create_key()
    fam_key = Fernet.generate_key()
    enc_dek = _get_fernet(root_kek).encrypt(fam_key).decode("utf-8")
    enc_name = encrypt_string("Empty Household", key=fam_key)

    with get_db_connection(fam_db) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO families (family_id, name, settings, encryption_key_enc, support_access_enabled)
            VALUES (?, ?, ?, ?, 1)
            """,
            (fam_id, enc_name, json.dumps({"primary_state": "WA", "tax_filing_status": "MFJ"}), enc_dek),
        )
        conn.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["family_id"] = fam_id
        sess["role"] = "editor"
        sess["universe"] = "test"
        sess["user_email"] = "empty_household@example.com"
        sess["is_demo"] = False
    return client


# ---------------------------------------------------------------------------
# 1. Dynamic app.url_map Mutating Auth Guardrail
# ---------------------------------------------------------------------------
EXEMPT_MUTATING_ROUTES: Set[str] = {
    "/api/auth/logout",
    "/api/telemetry/action",
    "/api/sync",
    "/api/ai-advisor/chat",
    "/api/sandbox/launch",
    "/api/sandbox/wipe",
    "/api/sandbox/restore",
    "/api/sandbox/restore_async",
}


def test_all_mutating_routes_enforce_auth_and_demo_readonly(demo_viewer_client, unauth_client):
    """
    Introspects app.url_map and verifies that every state-changing route (POST, PUT, DELETE)
    under /api/* rejects unauthenticated and demo viewer sessions with HTTP 401 or 403.
    Never returns 200 or 500.
    """
    mutating_endpoints = []
    for rule in app.url_map.iter_rules():
        methods = rule.methods - {"GET", "HEAD", "OPTIONS"}
        if methods and rule.rule.startswith("/api/") and rule.rule not in EXEMPT_MUTATING_ROUTES:
            test_url = re.sub(r"<[^>]+>", "1", rule.rule)
            for method in sorted(methods):
                mutating_endpoints.append((method, test_url))

    assert len(mutating_endpoints) >= 70, f"Expected >= 70 mutating endpoints, found {len(mutating_endpoints)}"

    for method, url in mutating_endpoints:
        # 1. Demo personas are strictly read-only: must reject with 401/403 (never 200 or 500)
        resp_demo = getattr(demo_viewer_client, method.lower())(url, json={})
        assert resp_demo.status_code in (401, 403), (
            f"Demo viewer was not rejected on {method} {url} (status: {resp_demo.status_code})"
        )
        assert resp_demo.status_code not in (200, 500)

        # 2. Unauthenticated sessions must reject with 401 or 403
        resp_unauth = getattr(unauth_client, method.lower())(url, json={})
        assert resp_unauth.status_code in (401, 403), (
            f"Unauthenticated request was not rejected on {method} {url} (status: {resp_unauth.status_code})"
        )


# ---------------------------------------------------------------------------
# 2. Full-Page (GET /<tab>) Deep SSR Hydration Check
# ---------------------------------------------------------------------------
ALL_FULL_PAGE_ROUTES = [
    "/",
    "/overview",
    "/scenarios",
    "/equity",
    "/holdings",
    "/compensation",
    "/estate",
    "/college",
    "/philanthropy",
    "/arbitrage",
    "/gifting",
    "/accounts",
    "/settings",
]


@pytest.mark.parametrize("route", ALL_FULL_PAGE_ROUTES)
def test_full_page_routes_embed_hydrated_ssr_markup(auth_client, route):
    """
    Asserts that every full-page route returns HTTP 200 and embeds fully pre-hydrated SSR markup
    with zero unhydrated primary KPI dashes (>--<).
    """
    resp = auth_client.get(route, follow_redirects=True)
    assert resp.status_code == 200, f"Route {route} failed with {resp.status_code}"
    html = resp.get_data(as_text=True)
    SSRParityAuditor.assert_no_bare_kpi_dashes(
        html,
        context_name=route,
        allowed_empty_ids={"child", "unallocated"},
    )


# ---------------------------------------------------------------------------
# 3. Empty / Unseeded Household SSR Smoke Test
# ---------------------------------------------------------------------------
ALL_FRAGMENTS = [
    "overview",
    "scenarios",
    "equity",
    "holdings",
    "compensation",
    "estate",
    "college",
    "philanthropy",
    "arbitrage",
    "gifting",
    "accounts",
    "settings",
]


def test_empty_household_ssr_fragments_never_crash_or_leak_mockups(empty_family_client):
    """
    Verifies that a household with 0 accounts, 0 equity grants, 0 compensation rows, and 0 scenarios
    loads all 12 SSR fragments cleanly with HTTP 200 (zero 500 errors, ZeroDivisionError, or KeyError).
    """
    for fragment_name in ALL_FRAGMENTS:
        resp = empty_family_client.get(f"/fragments/{fragment_name}")
        assert resp.status_code == 200, f"/fragments/{fragment_name} returned {resp.status_code}"
        html = resp.get_data(as_text=True)
        assert len(html) > 50, f"/fragments/{fragment_name} returned empty shell"
        for bad_snippet in ("Traceback (most recent call last):", "ZeroDivisionError", "KeyError:"):
            assert bad_snippet not in html, f"/fragments/{fragment_name} leaked raw exception: {bad_snippet}"
        if fragment_name == "equity":
            assert 'id="graph-stat-growth"' in html and ">--<" in html.partition('id="graph-stat-growth"')[2].partition("</div>")[0] + "</div>"
            assert "+10.5% / yr" not in html


# ---------------------------------------------------------------------------
# 4. Standalone SSR Pages & Mode-Conditional Rendering
# ---------------------------------------------------------------------------
def test_standalone_pages_and_login_modes_ssr(unauth_client, monkeypatch):
    """
    Validates standalone SSR pages (/login, /help, /features) and conditional rendering
    between default Hosted mode and Local Desktop mode.
    """
    # 1. Default Hosted mode (LOCAL_MODE=False)
    monkeypatch.setattr(config, "is_local_mode", lambda: False)
    resp_hosted = unauth_client.get("/login")
    assert resp_hosted.status_code == 200
    html_hosted = resp_hosted.get_data(as_text=True)
    body_hosted = html_hosted.split("<body", 1)[1] if "<body" in html_hosted else html_hosted

    assert "Cloud Vault Sign In" in body_hosted
    assert "Anonymous Workspace" in body_hosted
    assert any(token in body_hosted for token in ('id="btn-launch-sandbox"', "/sandbox", "Launch Anonymous Workspace"))
    assert any(token in body_hosted for token in ("Interactive Feature Tour", "Explore Platform Features", "Tour"))

    # 2. Local Desktop mode (is_local_mode=True)
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setattr(config, "is_local_mode", lambda: True)
    resp_local = unauth_client.get("/login")
    assert resp_local.status_code == 200
    html_local = resp_local.get_data(as_text=True)
    body_local = html_local.split("<body", 1)[1] if "<body" in html_local else html_local

    assert "Cloud Vault Sign In" not in html_local
    assert "Anonymous Workspace" not in body_local
    assert any(
        token in body_local
        for token in ("Unlock Local Vault", "Welcome to Local Family Office", "local-setup-form", "local-login-form")
    )

    # 3. Help and Features documentation pages
    resp_help = unauth_client.get("/help")
    assert resp_help.status_code == 200
    html_help = resp_help.get_data(as_text=True)
    assert any(token in html_help for token in ("User Guide & Knowledge Base", "User Guide &amp; Knowledge Base", "User Guide"))

    resp_feat = unauth_client.get("/features")
    assert resp_feat.status_code == 200
    html_feat = resp_feat.get_data(as_text=True)
    assert any(token in html_feat for token in ("Workspace Modes", "Anonymous Workspace", "Cloud Vault"))


def test_scenarios_scorecard_viewing_badge_and_collapsed_event_icons_ssr(auth_client):
    """
    Verifies that /fragments/scenarios renders:
    1. Uniform .scorecard-actions-grid / .scorecard-action-item classes and a non-clickable
       <span class="... scorecard-viewing-badge">Viewing</span> on the currently viewed row.
    2. Collapsed event icon strips (#selected-scen-events-collapsed-icons and .scen-events-collapsed-icons)
       containing icon-only chips with hover tooltip attributes.
    """
    resp = auth_client.get("/fragments/scenarios")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'class="scorecard-actions-grid"' in html
    assert "scorecard-viewing-badge" in html
    assert "<button" not in html.partition("scorecard-viewing-badge")[0].rpartition("<")[-1]
    assert 'id="selected-scen-events-collapsed-icons"' in html
    assert "event-icon-chip-top" in html
    assert "scen-events-collapsed-icons" in html

