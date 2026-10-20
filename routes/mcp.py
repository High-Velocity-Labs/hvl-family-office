"""
Model Context Protocol (MCP) Route Handlers (`routes.mcp`).
Mounts the streamable JSON-RPC 2.0 MCP Gateway blueprint at `/mcp` and provides
authenticated household/member settings endpoints for token lifecycle management.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request, session

from hvl_common.mcp.blueprint import create_mcp_blueprint
from routes.helpers import editor_required, get_current_family_id, get_current_universe, login_required
from services.mcp_service import (
    FAMILY_OFFICE_MCP_REGISTRY,
    _resolve_mcp_db_path,
    _resolve_mcp_server_secret,
    generate_member_mcp_token,
    get_household_mcp_status,
    record_fo_mcp_telemetry,
    revoke_member_mcp_token,
    toggle_household_mcp,
)

logger = logging.getLogger(__name__)

# Personal Assistant MCP JSON-RPC 2.0 Gateway Blueprint
mcp_gateway_bp = create_mcp_blueprint(
    FAMILY_OFFICE_MCP_REGISTRY,
    db_path_resolver=_resolve_mcp_db_path,
    service_name="family-office-mcp",
    url_prefix="/mcp",
    telemetry_callback=record_fo_mcp_telemetry,
    server_secret_resolver=_resolve_mcp_server_secret,
)

# Authenticated Member / Household Settings API Blueprint
mcp_settings_bp = Blueprint("mcp_settings", __name__)


@mcp_settings_bp.route("/api/settings/mcp/status", methods=["GET"])
@login_required
def get_mcp_settings_status() -> Any:
    """Returns household MCP gateway status, active member tokens, and endpoint info."""
    family_id = get_current_family_id()
    user_email = str(session.get("user_email") or session.get("user") or "").strip().lower()
    status = get_household_mcp_status(family_id, user_email=user_email)
    return jsonify({"success": True, "status": status})


@mcp_settings_bp.route("/api/settings/mcp/token", methods=["POST"])
@editor_required
def generate_mcp_token_route() -> Any:
    """Mints or rotates a Personal Assistant MCP API token for the current household member."""
    family_id = get_current_family_id()
    universe = get_current_universe()
    if session.get("is_demo") or universe in ("sandbox", "demo", "beta"):
        return jsonify({
            "success": False,
            "error": "MCP tokens cannot be minted for sandbox or demo workspaces.",
        }), 403

    user_email = str(session.get("user_email") or session.get("user") or "member").strip().lower()
    data = request.get_json(silent=True) or {}
    label = str(data.get("label") or f"{user_email}'s Assistant").strip()

    try:
        token_info = generate_member_mcp_token(
            family_id, user_email=user_email, label=label, universe=universe
        )
        status = get_household_mcp_status(family_id, user_email=user_email)
        return jsonify({
            "success": True,
            "raw_token": token_info["raw_token"],
            "token": token_info["raw_token"],
            "status": status,
        })
    except PermissionError as pe:
        return jsonify({"success": False, "error": str(pe)}), 403
    except Exception as e:
        logger.warning(f"Failed to mint MCP token for family {family_id}: {e}")
        return jsonify({"success": False, "error": "Failed to mint assistant token"}), 500


@mcp_settings_bp.route("/api/settings/mcp/toggle", methods=["POST"])
@editor_required
def toggle_household_mcp_route() -> Any:
    """Enables or pauses all Personal Assistant MCP tokens for the active household."""
    family_id = get_current_family_id()
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", True))
    toggle_household_mcp(family_id, enabled=enabled)
    user_email = str(session.get("user_email") or session.get("user") or "").strip().lower()
    status = get_household_mcp_status(family_id, user_email=user_email)
    return jsonify({"success": True, "enabled": enabled, "status": status})


@mcp_settings_bp.route("/api/settings/mcp/revoke", methods=["POST"])
@editor_required
def revoke_mcp_token_route() -> Any:
    """Revokes a specific member token or all household assistant tokens."""
    family_id = get_current_family_id()
    data = request.get_json(silent=True) or {}
    token_id_raw = data.get("token_id")
    token_id = int(token_id_raw) if token_id_raw is not None else None
    user_email = str(session.get("user_email") or session.get("user") or "").strip().lower()

    if token_id is None and not data.get("all"):
        revoke_member_mcp_token(family_id, user_email=user_email)
    elif data.get("all"):
        revoke_member_mcp_token(family_id)
    else:
        revoke_member_mcp_token(family_id, token_id=token_id)

    status = get_household_mcp_status(family_id, user_email=user_email)
    return jsonify({"success": True, "status": status})
