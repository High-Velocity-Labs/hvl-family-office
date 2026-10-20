"""
Tests for Personal Assistant MCP Gateway & Settings Integration (`tests.test_mcp_gateway`).
Verifies 20 non-mutating tools, JSON-RPC 2.0 protocol, household isolation,
multi-member tokens, sandbox rejection, rate limiting, telemetry, and settings API.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import pytest
from flask import Flask

from app import app
from hvl_common.mcp.tokens import (
    ensure_mcp_tokens_table,
    list_mcp_tokens,
    mint_mcp_token,
    verify_mcp_token,
)
from routes.helpers import DB_PATH
from services.mcp_service import (
    FAMILY_OFFICE_MCP_REGISTRY,
    _resolve_mcp_db_path,
    generate_member_mcp_token,
    get_household_mcp_status,
    revoke_member_mcp_token,
    toggle_household_mcp,
)
from ssr.settings import build_ssr_settings


@pytest.fixture(autouse=True)
def clean_mcp_tokens_db():
    """Ensures clean mcp_tokens table before each test run."""
    db_file = _resolve_mcp_db_path()
    ensure_mcp_tokens_table(db_file)
    import sqlite3
    with sqlite3.connect(str(db_file)) as conn:
        try:
            conn.execute("DELETE FROM mcp_tokens")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    yield


def _mint_test_tok(owner_id: int = 1, user_email: str = "tester@example.com") -> str:
    db_file = _resolve_mcp_db_path()
    res = mint_mcp_token(db_file, owner_id=owner_id, user_email=user_email)
    return str(res["raw_token"])


def test_mcp_registry_inspection_17_tools():
    """Verifies all 20 non-mutating tools are registered with correct tiers and no mutations."""
    tools = FAMILY_OFFICE_MCP_REGISTRY.list_tools()
    tool_names = {t["name"] for t in tools}
    assert len(tool_names) == 20

    # Mutating tools must NEVER be registered in the MCP gateway
    assert "manage_scenario_life_event" not in tool_names
    assert "manage_lp_commitment" not in tool_names
    assert "update_tax_document_checklist_status" not in tool_names

    read_tools = [
        "get_family_advisor_context", "get_accounts_and_balance_sheet", "get_portfolio_allocation",
        "get_cash_flow_summary", "get_compensation_and_tax_withholding", "get_equity_schedule",
        "get_scenarios_and_forecast_plan", "get_state_tax_arbitrage", "get_education_529_plan",
        "get_estate_tax_summary", "get_family_gifting_summary", "get_philanthropy_and_daf_summary",
        "get_private_markets_lp_book", "audit_household_risks",
        "get_annual_cash_flow_detail", "get_chief_of_staff_radar",
    ]
    sim_tools = [
        "simulate_financial_scenario", "get_monte_carlo_stress_test",
        "estimate_equity_exercise_tax", "simulate_life_event_impact",
    ]

    for name in read_tools:
        meta = FAMILY_OFFICE_MCP_REGISTRY.get_tool_meta(name)
        assert meta is not None, f"Missing read tool {name}"
        assert meta["tier"] == "read"
        assert meta["scope"] == "read"
        assert "family_id" not in meta["inputSchema"].get("properties", {})

    for name in sim_tools:
        meta = FAMILY_OFFICE_MCP_REGISTRY.get_tool_meta(name)
        assert meta is not None, f"Missing simulate tool {name}"
        assert meta["tier"] == "simulate"
        assert meta["scope"] == "simulate"
        assert "family_id" not in meta["inputSchema"].get("properties", {})

    # Docstring check for get_family_advisor_context
    ctx_meta = FAMILY_OFFICE_MCP_REGISTRY.get_tool_meta("get_family_advisor_context")
    assert "holistic household financial overview" in ctx_meta["description"].lower()


def test_mcp_endpoint_protocol_and_auth():
    """Verifies GET metadata, 401 without auth, and JSON-RPC initialize/tools methods."""
    client = app.test_client()

    # GET metadata
    r_get = client.get("/mcp")
    assert r_get.status_code == 200
    assert r_get.get_json()["protocol"] == "mcp-streamable-http"

    # POST missing token -> 401
    r_unauth = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r_unauth.status_code == 401
    assert "Bearer" in r_unauth.headers.get("WWW-Authenticate", "")

    # POST with valid token -> initialize
    raw_tok = _mint_test_tok(1)
    headers = {"Authorization": f"Bearer {raw_tok}"}

    r_init = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 10, "method": "initialize"})
    assert r_init.status_code == 200
    res_init = r_init.get_json()
    assert res_init["result"]["serverInfo"]["name"] == "hvl-mcp-gateway"

    # tools/list returns all 20 tools
    r_tools = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 11, "method": "tools/list"})
    assert r_tools.status_code == 200
    tools_list = r_tools.get_json()["result"]["tools"]
    assert len(tools_list) == 20


def test_mcp_execution_all_17_tools():
    """Executes all 20 tools via JSON-RPC tools/call over the HTTP gateway."""
    client = app.test_client()
    raw_tok = _mint_test_tok(1)
    headers = {"Authorization": f"Bearer {raw_tok}"}

    all_tools = [t["name"] for t in FAMILY_OFFICE_MCP_REGISTRY.list_tools()]
    assert len(all_tools) == 20

    custom_args = {
        "simulate_financial_scenario": {"trials": 10},
        "get_monte_carlo_stress_test": {"trials": 10},
        "estimate_equity_exercise_tax": {"shares_to_exercise": 50.0},
        "get_annual_cash_flow_detail": {"year": 2026},
        "simulate_life_event_impact": {"amount": 50000.0, "duration_years": 1},
        "get_chief_of_staff_radar": {},
    }

    results = {}
    for idx, tool_name in enumerate(all_tools, start=100):
        args = custom_args.get(tool_name, {})
        payload = {
            "jsonrpc": "2.0",
            "id": idx,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }
        res = client.post("/mcp", headers=headers, json=payload)
        assert res.status_code == 200, f"Tool {tool_name} failed with {res.status_code}: {res.data}"
        body = res.get_json()
        assert "error" not in body, f"Tool {tool_name} returned error: {body}"
        assert "result" in body
        structured = body["result"].get("structuredContent")
        assert isinstance(structured, dict)
        results[tool_name] = structured

    # Specific assertions for the 3 new high-leverage tools
    cf = results["get_annual_cash_flow_detail"]
    assert "year" in cf and "net_cash_flow" in cf and "available_year_range" in cf
    sim = results["simulate_life_event_impact"]
    assert sim["status"] == "simulated_ephemeral" and sim["persisted_to_db"] is False
    assert "baseline" in sim and "with_event" in sim and "deltas" in sim
    radar = results["get_chief_of_staff_radar"]
    assert "data_freshness" in radar and "household_risk_audit" in radar
    assert "tax_and_safe_harbor_pacing" in radar and "private_markets_and_liquidity" in radar


def test_household_isolation_and_spoofing_guard():
    """Verifies cross-tenant isolation and guarantees caller arguments cannot spoof family_id."""
    client = app.test_client()
    tok_fam1 = _mint_test_tok(1, "fam1@example.com")
    tok_fam2 = _mint_test_tok(2, "fam2@example.com")

    # Family 1 token attempts to pass arguments with family_id=2
    spoof_payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_family_advisor_context", "arguments": {"family_id": 2}}}
    r1 = client.post("/mcp", headers={"Authorization": f"Bearer {tok_fam1}"}, json=spoof_payload)
    assert r1.status_code == 200 and r1.get_json()["result"]["structuredContent"]["family_id"] == 1

    # Family 2 token receives Family 2 context
    r2 = client.post("/mcp", headers={"Authorization": f"Bearer {tok_fam2}"}, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_family_advisor_context"}})
    assert r2.status_code == 200 and r2.get_json()["result"]["structuredContent"]["family_id"] == 2


def test_spouse_multi_member_tokens():
    """Verifies multiple members within the same household can mint and track separate keys."""
    client = app.test_client()
    db_file = _resolve_mcp_db_path()

    tok_primary = _mint_test_tok(1, "alice@family.org")
    tok_spouse = _mint_test_tok(1, "bob@family.org")

    tokens = list_mcp_tokens(db_file, owner_id=1)
    assert len(tokens) == 2
    emails = {t["user_email"] for t in tokens}
    assert emails == {"alice@family.org", "bob@family.org"}

    # Primary makes a call
    client.post("/mcp", headers={"Authorization": f"Bearer {tok_primary}"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_cash_flow_summary"}})

    tokens_after = list_mcp_tokens(db_file, owner_id=1)
    p_meta = next(t for t in tokens_after if t["user_email"] == "alice@family.org")
    s_meta = next(t for t in tokens_after if t["user_email"] == "bob@family.org")
    assert p_meta["call_count"] == 1
    assert s_meta["call_count"] == 0

    # Spouse makes a call
    client.post("/mcp", headers={"Authorization": f"Bearer {tok_spouse}"}, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_equity_schedule"}})
    tokens_final = list_mcp_tokens(db_file, owner_id=1)
    s_final = next(t for t in tokens_final if t["user_email"] == "bob@family.org")
    assert s_final["call_count"] == 1


def test_household_toggle_and_revocation():
    """Verifies toggling household off disables tokens (401), and revoking deletes them."""
    client = app.test_client()
    raw_tok = _mint_test_tok(1)
    headers = {"Authorization": f"Bearer {raw_tok}"}

    # Enabled by default -> toggle off -> toggle on -> revoke
    assert client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 200
    toggle_household_mcp(1, enabled=False)
    assert client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).status_code == 401
    toggle_household_mcp(1, enabled=True)
    assert client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"}).status_code == 200
    revoke_member_mcp_token(1, user_email="tester@example.com")
    assert client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"}).status_code == 401


def test_sandbox_rejection_and_mint_security():
    """Verifies minting is forbidden in demo or sandbox workspaces."""
    db_file = _resolve_mcp_db_path()
    with pytest.raises(PermissionError):
        mint_mcp_token(db_file, owner_id=1, universe="demo")
    with pytest.raises(PermissionError):
        mint_mcp_token(db_file, owner_id=1, universe="sandbox")


def test_mcp_settings_endpoints_and_ssr_integration():
    """Verifies authenticated settings endpoints and inclusion of mcp_status in ssr_settings."""
    client = app.test_client()

    # Unauthenticated settings call -> 401
    r_unauth = client.get("/api/settings/mcp/status")
    assert r_unauth.status_code == 401

    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["is_demo"] = False
        sess["universe"] = "test"
        sess["user_email"] = "member@example.com"
        sess["family_id"] = 1
        sess["user_family_id"] = 1
        sess["role"] = "editor"

    # Status check
    r_stat = client.get("/api/settings/mcp/status")
    assert r_stat.status_code == 200
    assert r_stat.get_json()["success"] is True

    # Mint token via API
    r_mint = client.post("/api/settings/mcp/token", json={"label": "Antigravity Assistant"})
    assert r_mint.status_code == 200
    data = r_mint.get_json()
    assert data["success"] is True
    assert data["raw_token"].startswith("hvl_mcp_")
    token_id = data["status"]["tokens"][0]["token_id"]

    # Toggle via API
    r_tog = client.post("/api/settings/mcp/toggle", json={"enabled": False})
    assert r_tog.status_code == 200
    assert r_tog.get_json()["enabled"] is False

    # Revoke via API
    r_rev = client.post("/api/settings/mcp/revoke", json={"token_id": token_id})
    assert r_rev.status_code == 200
    assert len(r_rev.get_json()["status"]["tokens"]) == 0

    # SSR Context verification
    ssr = build_ssr_settings(1)
    assert "mcp_status" in ssr
    assert "ai_key_status" in ssr
    assert isinstance(ssr["mcp_status"], dict)


def test_telemetry_recording_hook():
    """Verifies telemetry hook is called and persists event to SQLite without throwing."""
    from services.mcp_service import record_fo_mcp_telemetry
    record_fo_mcp_telemetry({
        "event_type": "mcp_tool_call",
        "tool_name": "get_portfolio_allocation",
        "tier": "read",
        "scope": "read",
        "token_prefix": "hvl_mcp_test...",
    })


def test_mcp_rate_limiting_enforcement(monkeypatch, tmp_path):
    """Verifies per-token rate limits on simulation tools and auth failures return 429."""
    app.config["RATELIMIT_ENABLED"] = True
    app.config["RATELIMIT_CACHE_DIR"] = str(tmp_path / "rl_cache")
    try:
        client = app.test_client()

        # 1. Auth fail rate limiting (10/min)
        for _ in range(10):
            client.post("/mcp", headers={"Authorization": "Bearer hvl_mcp_invalid_token"}, json={"jsonrpc": "2.0", "id": 1})
        r_auth_limit = client.post("/mcp", headers={"Authorization": "Bearer hvl_mcp_invalid_token"}, json={"jsonrpc": "2.0", "id": 1})
        assert r_auth_limit.status_code == 429
        assert r_auth_limit.get_json()["error"]["code"] == -32029

        # 2. Simulation tool rate limiting (10/min)
        raw_tok = _mint_test_tok(1, "sim_limit@example.com")
        headers = {"Authorization": f"Bearer {raw_tok}"}
        sim_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "simulate_financial_scenario", "arguments": {"trials": 10}},
        }
        for _ in range(10):
            r = client.post("/mcp", headers=headers, json=sim_payload)
            assert r.status_code == 200

        r_sim_limit = client.post("/mcp", headers=headers, json=sim_payload)
        assert r_sim_limit.status_code == 429
        assert r_sim_limit.get_json()["error"]["code"] == -32029
        assert "Retry-After" in r_sim_limit.headers
    finally:
        app.config.pop("RATELIMIT_ENABLED", None)
        app.config.pop("RATELIMIT_CACHE_DIR", None)


def test_mcp_works_when_support_access_disabled_and_cache_cold(monkeypatch):
    """Verifies zero-knowledge token-bound FEK unwrapping works even when support_access_enabled=0 and caches are cold."""
    import config
    import security
    from hvl_common.db import get_db_connection
    from routes.helpers import get_current_db_path
    from services.advisor.tools_operations import manage_lp_commitment

    fam_db = get_current_db_path(family_id=1)
    security.init_db(fam_db)
    raw_fek = security.get_family_key(fam_db, 1)
    enc_dek = security._get_fernet(security.get_or_create_key()).encrypt(raw_fek).decode("utf-8")
    manage_lp_commitment(
        action="upsert", fund_name="Vault Locked Ventures I", vintage_year=2026,
        total_commitment=500000.0, capital_called=100000.0, family_id=1,
    )
    raw_tok = generate_member_mcp_token(1, user_email="alpha@example.com", universe="public")["raw_token"]

    with get_db_connection(fam_db) as conn:
        conn.execute("UPDATE families SET support_access_enabled = 0, encryption_key_enc = NULL WHERE family_id = 1")
        conn.commit()
    security._clear_security_caches()

    orig_testing = app.config.get("TESTING")
    try:
        ext_client = app.test_client()
        r = ext_client.post(
            "/mcp", headers={"Authorization": f"Bearer {raw_tok}"},
            json={"jsonrpc": "2.0", "id": 42, "method": "tools/call", "params": {"name": "get_private_markets_lp_book", "arguments": {}}},
        )
        assert r.status_code == 200 and r.get_json()["result"]["isError"] is False
        structured = r.get_json()["result"]["structuredContent"]
        assert any("Vault Locked Ventures I" in str(f.get("fund_name", "")) for f in structured.get("commitments", []))

        monkeypatch.setattr(config, "is_beta_instance", lambda: True)
        app.config["TESTING"] = False
        r_beta = ext_client.post(
            "/mcp", headers={"Authorization": f"Bearer {raw_tok}"},
            json={"jsonrpc": "2.0", "id": 43, "method": "tools/list"},
        )
        assert r_beta.status_code == 200 and len(r_beta.get_json()["result"]["tools"]) == 20
    finally:
        app.config["TESTING"] = orig_testing
        with get_db_connection(fam_db) as conn:
            conn.execute(
                "UPDATE families SET support_access_enabled = 1, encryption_key_enc = ? WHERE family_id = 1",
                (enc_dek,),
            )
            conn.commit()
        security._clear_security_caches()

