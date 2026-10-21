"""
Tests for AI Advisor What-If Scenarios & MCP Tool Registry (`tests.test_mcp_service`).
Verifies enhanced simulate_financial_scenario tool parameters (lifestyle expenses,
Form 709 annual gifting exclusion maximization, gifting overrides) and MCP registration.
"""

from __future__ import annotations

import pytest
from app import app
from services.advisor.tools_core import simulate_financial_scenario
from services.mcp_service import FAMILY_OFFICE_MCP_REGISTRY


def test_simulate_financial_scenario_unauthenticated():
    """Verify simulate_financial_scenario returns empty dict when family_id is 0."""
    assert simulate_financial_scenario(family_id=0) == {}


def test_simulate_financial_scenario_lifestyle_and_gifting():
    """Verify simulate_financial_scenario models lifestyle expense and max annual gifting."""
    res = simulate_financial_scenario(
        family_id=1,
        additional_annual_expense=45000.0,
        maximize_annual_gifting_exclusion=True,
        trials=50,
    )
    assert res.get("success") is True
    assert res.get("baseline_annual_spending") == 1130000.0
    assert res.get("additional_annual_expense_modeled") == 45000.0

    g_analysis = res.get("gifting_analysis")
    assert isinstance(g_analysis, dict)
    assert g_analysis["annual_gifting_limit"] == 722000.0
    assert g_analysis["current_annual_gifted"] == 140000.0
    assert g_analysis["additional_annual_gifting_modeled"] == 582000.0
    assert g_analysis["estimated_30yr_estate_transfer"] == 17460000.0
    assert g_analysis["estimated_estate_tax_saved_at_40pct"] == 6984000.0

    expected_spending = 1130000.0 + 45000.0 + 582000.0
    assert res.get("effective_annual_spending") == expected_spending
    assert res.get("simulated_spending") == expected_spending
    assert res.get("probability_of_success_pct") is not None


def test_simulate_financial_scenario_gifting_override():
    """Verify simulate_financial_scenario models custom gifting override amount."""
    res = simulate_financial_scenario(
        family_id=1,
        annual_gifting_override=200000.0,
        trials=50,
    )
    assert res.get("success") is True
    assert res.get("baseline_annual_spending") == 1130000.0

    g_analysis = res.get("gifting_analysis")
    assert isinstance(g_analysis, dict)
    assert g_analysis["current_annual_gifted"] == 140000.0
    assert g_analysis["additional_annual_gifting_modeled"] == 60000.0
    assert g_analysis["estimated_30yr_estate_transfer"] == 1800000.0
    assert g_analysis["estimated_estate_tax_saved_at_40pct"] == 720000.0

    expected_spending = 1130000.0 + 60000.0
    assert res.get("simulated_spending") == expected_spending


def test_simulate_financial_scenario_backward_compatibility():
    """Verify standard calls preserve exact legacy output format without extra keys."""
    res = simulate_financial_scenario(family_id=1, custom_spending=250000.0, trials=50)
    assert res.get("success") is True
    assert res.get("simulated_spending") == 250000.0
    assert "baseline_annual_spending" not in res
    assert "additional_annual_expense_modeled" not in res
    assert "gifting_analysis" not in res


def test_mcp_registry_simulate_financial_scenario_schema():
    """Verify FAMILY_OFFICE_MCP_REGISTRY automatically exposes updated tool signature."""
    meta = FAMILY_OFFICE_MCP_REGISTRY.get_tool_meta("simulate_financial_scenario")
    assert meta is not None
    props = meta.get("inputSchema", {}).get("properties", {})
    assert "additional_annual_expense" in props
    assert props["additional_annual_expense"]["type"] == "number"
    assert "maximize_annual_gifting_exclusion" in props
    assert props["maximize_annual_gifting_exclusion"]["type"] == "boolean"
    assert "annual_gifting_override" in props
    assert props["annual_gifting_override"]["type"] == "number"


def test_mcp_registry_simulate_financial_scenario_execution():
    """Verify MCP gateway registry can execute simulate_financial_scenario with new parameters."""
    import json
    res = FAMILY_OFFICE_MCP_REGISTRY.call_tool(
        "simulate_financial_scenario",
        {"additional_annual_expense": 30000.0, "trials": 20},
        owner_id=1,
        allowed_scopes=["simulate"],
    )
    assert res.get("isError") is False
    content = res.get("content", [])
    assert len(content) > 0
    data = json.loads(content[0]["text"])
    assert data.get("success") is True
    assert data.get("additional_annual_expense_modeled") == 30000.0
    assert data.get("baseline_annual_spending") == 1130000.0
    assert data.get("simulated_spending") == 1160000.0
