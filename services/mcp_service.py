"""
MCP Gateway Service & Tool Registry for HVL Family Office (`services.mcp_service`).
Registers all 20 non-mutating AI Advisor tools into `FAMILY_OFFICE_MCP_REGISTRY`,
isolates execution per household, enforces scope-based rate limits, and provides
service helpers for household/member token administration in the Settings UI.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from hvl_common.mcp.server import MCPToolRegistry, get_active_mcp_token_context
from hvl_common.mcp.tokens import (
    list_mcp_tokens, mint_mcp_token, revoke_mcp_token, set_mcp_owner_enabled, verify_mcp_token,
)

__all__ = ["verify_mcp_token"]
from routes.helpers import get_current_universe, reset_background_context, set_background_context
from services.advisor.context import _get_family_advisor_context
from services.advisor.tools_core import (
    estimate_equity_exercise_tax, get_cash_flow_summary, get_equity_schedule,
    get_estate_tax_summary, get_monte_carlo_stress_test, get_portfolio_allocation,
    simulate_financial_scenario,
)
from services.advisor.tools_chief_of_staff import (
    get_annual_cash_flow_detail, get_chief_of_staff_radar, simulate_life_event_impact,
)
from services.advisor.tools_tabs import (
    audit_household_risks, get_accounts_and_balance_sheet, get_compensation_and_tax_withholding,
    get_education_529_plan, get_family_gifting_summary, get_philanthropy_and_daf_summary,
    get_private_markets_lp_book, get_scenarios_and_forecast_plan, get_state_tax_arbitrage,
)

logger = logging.getLogger(__name__)


def _resolve_mcp_db_path() -> Path:
    """Resolves primary SQLite database path for MCP tokens and telemetry events."""
    from routes.helpers import DB_PATH
    if hasattr(DB_PATH, "global_db"):
        try:
            return DB_PATH.global_db()
        except Exception:
            return Path(str(DB_PATH))
    return Path(str(DB_PATH))


def _resolve_mcp_server_secret() -> bytes:
    """Resolves the primary server root key used alongside raw_token to wrap/unwrap household FEK."""
    import security
    return security.get_primary_key()


def _with_background_context(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wraps an advisor tool to set background family and vault FEK contextvars during execution."""
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        fid = 0
        if "family_id" in kwargs:
            try:
                fid = int(kwargs["family_id"] or 0)
            except (ValueError, TypeError):
                fid = 0
        elif args:
            try:
                fid = int(args[0] or 0)
            except (ValueError, TypeError):
                fid = 0
        tok_ctx = get_active_mcp_token_context()
        vault_fek = tok_ctx.get("secret_payload") if isinstance(tok_ctx, dict) else None
        tokens = set_background_context(fid, get_current_universe(), vault_fek=vault_fek)
        try:
            return fn(*args, **kwargs)
        finally:
            reset_background_context(tokens)

    return wrapper


def get_family_advisor_context(family_id: int = 0) -> Dict[str, Any]:
    """Retrieves holistic household financial overview across net worth, accounts, cash flow, equity, and tax profile."""
    return _get_family_advisor_context(family_id=family_id)


# Configure and populate the singleton MCP Tool Registry
FAMILY_OFFICE_MCP_REGISTRY = MCPToolRegistry()

# 16 Read Tier Tools (scope="read", tier="read")
_READ_TOOLS: List[Tuple[str, Callable[..., Any], Optional[str]]] = [
    ("get_family_advisor_context", get_family_advisor_context, None),
    ("get_accounts_and_balance_sheet", get_accounts_and_balance_sheet, None),
    ("get_portfolio_allocation", get_portfolio_allocation, None),
    ("get_cash_flow_summary", get_cash_flow_summary, None),
    ("get_compensation_and_tax_withholding", get_compensation_and_tax_withholding, None),
    ("get_equity_schedule", get_equity_schedule, None),
    ("get_scenarios_and_forecast_plan", get_scenarios_and_forecast_plan, None),
    ("get_state_tax_arbitrage", get_state_tax_arbitrage, None),
    ("get_education_529_plan", get_education_529_plan, None),
    ("get_estate_tax_summary", get_estate_tax_summary, None),
    ("get_family_gifting_summary", get_family_gifting_summary, None),
    ("get_philanthropy_and_daf_summary", get_philanthropy_and_daf_summary, None),
    ("get_private_markets_lp_book", get_private_markets_lp_book, None),
    ("audit_household_risks", audit_household_risks, None),
    ("get_annual_cash_flow_detail", get_annual_cash_flow_detail, None),
    ("get_chief_of_staff_radar", get_chief_of_staff_radar, None),
]

# 4 Simulation Tier Tools (scope="simulate", tier="simulate")
_SIMULATE_TOOLS: List[Tuple[str, Callable[..., Any], Optional[str]]] = [
    ("simulate_financial_scenario", simulate_financial_scenario, None),
    ("get_monte_carlo_stress_test", get_monte_carlo_stress_test, None),
    ("estimate_equity_exercise_tax", estimate_equity_exercise_tax, None),
    ("simulate_life_event_impact", simulate_life_event_impact, None),
]

for _scope_name, _tools_group in (("read", _READ_TOOLS), ("simulate", _SIMULATE_TOOLS)):
    for name, tool_fn, desc in _tools_group:
        FAMILY_OFFICE_MCP_REGISTRY.register_tool(
            _with_background_context(tool_fn),
            name=name,
            description=desc,
            scope=_scope_name,
            tier=_scope_name,
            inject_arg="family_id",
            exclude_args=("family_id", "owner_id", "db_path"),
        )


def record_fo_mcp_telemetry(event: Dict[str, Any]) -> None:
    """Telemetry hook invoked on successful tool executions and rate-limit hits."""
    try:
        from db.telemetry import record_portal_telemetry_event

        record_portal_telemetry_event(
            universe="public",
            event_type=event.get("event_type", "mcp_tool_call"),
            feature_key=str(event.get("tool_name") or event.get("scope") or "mcp"),
            session_hash=str(event.get("token_prefix") or ""),
            action=f"mcp:{event.get('tool_name') or event.get('scope') or 'call'}",
            db_path=_resolve_mcp_db_path(),
        )
    except Exception as e:
        logger.debug(f"Failed to record MCP telemetry event: {e}")


def get_household_mcp_status(
    family_id: int,
    user_email: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Retrieves household MCP gateway enablement status, member tokens, and caller token info."""
    target_db = Path(db_path) if db_path is not None else _resolve_mcp_db_path()
    fid = int(family_id)
    tokens = [
        t for t in list_mcp_tokens(target_db, owner_id=fid)
        if not str(t.get("user_email") or "").strip().lower().startswith("siri:")
    ]
    clean_email = (user_email or "").strip().lower()
    my_token = next(
        (t for t in tokens if str(t.get("user_email") or "").strip().lower() == clean_email),
        None,
    ) if clean_email else None

    is_enabled = any(t.get("is_enabled", False) for t in tokens) if tokens else True
    total_calls = sum(int(t.get("call_count") or 0) for t in tokens)

    return {
        "enabled": is_enabled,
        "is_enabled": is_enabled,
        "family_id": fid,
        "tokens": tokens,
        "token_count": len(tokens),
        "user_token": my_token,
        "has_token": bool(my_token or tokens),
        "total_calls": total_calls,
        "endpoint_path": "/mcp",
    }


def generate_member_mcp_token(
    family_id: int,
    user_email: str = "",
    label: str = "Personal Assistant",
    universe: str = "public",
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Mints or rotates an MCP token for a specific household member, binding their vault FEK zero-knowledge."""
    import security
    from routes.helpers import get_current_db_path

    target_db = Path(db_path) if db_path is not None else _resolve_mcp_db_path()
    fid = int(family_id)
    vault_fek: Optional[bytes] = None
    if fid > 0:
        try:
            fam_db = Path(db_path) if db_path is not None else get_current_db_path(family_id=fid)
            vault_fek = security.get_family_key(fam_db, fid)
        except Exception:
            vault_fek = None

    return mint_mcp_token(
        target_db,
        owner_id=fid,
        user_email=user_email,
        label=label or "Personal Assistant",
        scopes=("read", "simulate"),
        universe=universe,
        secret_payload=vault_fek,
        server_secret=_resolve_mcp_server_secret(),
    )


def toggle_household_mcp(
    family_id: int,
    enabled: bool,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Enables or pauses all active MCP tokens for a household."""
    target_db = Path(db_path) if db_path is not None else _resolve_mcp_db_path()
    return set_mcp_owner_enabled(target_db, owner_id=int(family_id), enabled=bool(enabled))


def revoke_member_mcp_token(
    family_id: int,
    token_id: Optional[int] = None,
    user_email: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Revokes a specific token by ID or user email, or all household tokens."""
    target_db = Path(db_path) if db_path is not None else _resolve_mcp_db_path()
    return revoke_mcp_token(
        target_db,
        owner_id=int(family_id),
        token_id=token_id,
        user_email=user_email,
    )


def get_ai_key_status(family_id: int, db_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Extracts custom Gemini API key configuration and rate limits for SSR settings."""
    from config import get_household_ai_limits

    target_db = Path(db_path) if db_path is not None else _resolve_mcp_db_path()
    policy = dict(
        get_household_ai_limits(
            family_id=family_id, db_path=target_db if target_db.exists() else None
        )
    )
    policy.pop("api_key", None)
    return policy


def bind_request_fek(
    fek_or_family_id: Any, vault_fek: Optional[bytes] = None, *,
    family_id: int = 0, universe: str = "",
) -> Tuple[Any, ...]:
    """Binds an unwrapped household `vault_fek` to the active request and background context."""
    from routes.helpers import get_current_family_id
    if isinstance(fek_or_family_id, (bytes, str)):
        raw_fek = fek_or_family_id.encode("utf-8") if isinstance(fek_or_family_id, str) else fek_or_family_id
        fid = int(family_id or get_current_family_id() or 1)
    else:
        fid = int(fek_or_family_id or family_id or 0)
        raw_fek = vault_fek.encode("utf-8") if isinstance(vault_fek, str) else vault_fek
    if fid > 0 and raw_fek:
        import security
        security.stash_request_vault_fek(fid, raw_fek)
    return set_background_context(fid, universe or get_current_universe(), vault_fek=raw_fek)


def mint_siri_token(
    family_id: int, user_email: str = "", universe: str = "public",
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Mints a Siri Shortcut token (`hvl_siri_...`) wrapping `secret_payload=vault_fek` via `hvl_common.mcp.tokens`."""
    clean_email = (user_email or "member").strip().lower()
    info = generate_member_mcp_token(
        int(family_id), user_email=f"siri:{clean_email}",
        label="Siri Shortcut", universe=universe, db_path=db_path,
    )
    raw_mcp = str(info.get("raw_token") or "")
    siri_tok = "hvl_siri_" + raw_mcp[len("hvl_mcp_"):] if raw_mcp.startswith("hvl_mcp_") else raw_mcp
    info["raw_token"] = siri_tok
    info["token"] = siri_tok
    return info


def verify_siri_token(
    raw_token: str, db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Verifies a Siri (`hvl_siri_...`) or MCP (`hvl_mcp_...`) bearer token and unwraps `secret_payload` (`vault_fek`)."""
    clean = str(raw_token or "").strip()
    if not clean:
        return None
    mcp_equiv = "hvl_mcp_" + clean[len("hvl_siri_"):] if clean.startswith("hvl_siri_") else clean
    target_db = Path(db_path) if db_path is not None else _resolve_mcp_db_path()
    return verify_mcp_token(target_db, mcp_equiv, server_secret=_resolve_mcp_server_secret())


def revoke_siri_token(
    family_id: int, user_email: str = "", db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Revokes the Siri Shortcut token for the specified household member."""
    clean_email = (user_email or "member").strip().lower()
    return revoke_member_mcp_token(int(family_id), user_email=f"siri:{clean_email}", db_path=db_path)


def run_advisor_chat(
    family_id: int, prompt: str, *, user_email: str = "",
    vault_fek: Optional[bytes] = None, db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Binds `vault_fek` and routes a spoken Siri prompt into the Family Office AI Advisor."""
    from routes.helpers import get_current_db_path
    from services.advisor.chat_service import execute_advisor_generation

    fid = int(family_id)
    tokens = bind_request_fek(fid, vault_fek)
    try:
        target_db = Path(db_path) if db_path is not None else get_current_db_path(family_id=fid)
        return execute_advisor_generation(
            family_id=fid, target_db_path=target_db, conv_id="",
            conv_title="Siri Voice Query", is_new_conv=False,
            user_message=str(prompt or "").strip(), active_tab="section-overview", history=[],
        )
    finally:
        reset_background_context(tokens)
