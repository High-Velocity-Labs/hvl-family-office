"""
Modular AI Financial Advisor package.
Provides 14 household-isolated callable Gemini tools across all 11 dashboard tabs,
active-tab context pre-grounding, multi-turn history normalization, and deterministic fallback.
"""

from __future__ import annotations

from services.advisor.chat_service import (
    build_advisor_context_response,
    execute_advisor_generation,
    handle_demo_chat_turn,
    is_advisor_demo_session,
    prepare_and_dispatch_chat,
)
from services.advisor.context import (
    _build_active_tab_snapshot,
    _clean_history_text,
    _ensure_advisor_tables,
    _format_fiduciary_system_prompt,
    _format_off_topic_refusal,
    _generate_conversation_title,
    _generate_follow_up_suggestions,
    _get_conversation_history_for_gemini,
    _get_family_advisor_context,
    _is_off_topic_query,
    get_initial_tab_suggestions,
)
from services.advisor.fallback import _generate_rule_based_response
from services.advisor.tools_core import (
    _resolve_tool_family_id,
    estimate_equity_exercise_tax,
    get_cash_flow_summary,
    get_equity_schedule,
    get_estate_tax_summary,
    get_monte_carlo_stress_test,
    get_portfolio_allocation,
    simulate_financial_scenario,
)
from services.advisor.tools_tabs import (
    ALL_ADVISOR_TOOLS,
    audit_household_risks,
    get_accounts_and_balance_sheet,
    get_compensation_and_tax_withholding,
    get_education_529_plan,
    get_family_gifting_summary,
    get_philanthropy_and_daf_summary,
    get_private_markets_lp_book,
    get_scenarios_and_forecast_plan,
    get_state_tax_arbitrage,
    manage_lp_commitment,
    manage_scenario_life_event,
    update_tax_document_checklist_status,
)

ADVISOR_TOOLS = ALL_ADVISOR_TOOLS

__all__ = [
    "ADVISOR_TOOLS",
    "ALL_ADVISOR_TOOLS",
    "audit_household_risks",
    "_build_active_tab_snapshot",
    "_clean_history_text",
    "_ensure_advisor_tables",
    "_format_fiduciary_system_prompt",
    "_format_off_topic_refusal",
    "_generate_conversation_title",
    "_generate_follow_up_suggestions",
    "_generate_rule_based_response",
    "_get_conversation_history_for_gemini",
    "_get_family_advisor_context",
    "_is_off_topic_query",
    "_resolve_tool_family_id",
    "build_advisor_context_response",
    "estimate_equity_exercise_tax",
    "execute_advisor_generation",
    "get_accounts_and_balance_sheet",
    "get_cash_flow_summary",
    "get_compensation_and_tax_withholding",
    "get_education_529_plan",
    "get_equity_schedule",
    "get_estate_tax_summary",
    "get_family_gifting_summary",
    "get_initial_tab_suggestions",
    "get_monte_carlo_stress_test",
    "get_philanthropy_and_daf_summary",
    "get_portfolio_allocation",
    "get_private_markets_lp_book",
    "get_scenarios_and_forecast_plan",
    "get_state_tax_arbitrage",
    "handle_demo_chat_turn",
    "is_advisor_demo_session",
    "manage_lp_commitment",
    "manage_scenario_life_event",
    "prepare_and_dispatch_chat",
    "simulate_financial_scenario",
    "update_tax_document_checklist_status",
]
