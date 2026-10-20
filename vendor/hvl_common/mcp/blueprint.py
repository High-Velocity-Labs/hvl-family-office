"""
Flask Blueprint Factory for MCP Gateway (`hvl_common.mcp.blueprint`).
Exposes streamable JSON-RPC 2.0 endpoints with multi-worker rate limiting,
scope authorization, token usage recording, and operational telemetry.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable, Dict, Optional, Sequence, Tuple, Union

from flask import Blueprint, Response, jsonify, request, session

from hvl_common.mcp.server import MCPToolRegistry, handle_jsonrpc_request
from hvl_common.mcp.tokens import MCP_TOKEN_PREFIX, record_mcp_token_usage, verify_mcp_token
from hvl_common.web.rate_limit import RateLimiter, _record_rate_limit_telemetry


def _extract_mcp_token(req: Any) -> Optional[str]:
    """
    Extracts MCP raw token from Authorization: Bearer <token>, X-MCP-Token header, or ?token= query arg.
    """
    auth = req.headers.get("Authorization", "").strip()
    if auth:
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        if auth.startswith(MCP_TOKEN_PREFIX):
            return auth

    x_tok = req.headers.get("X-MCP-Token", "").strip()
    if x_tok:
        return x_tok

    q_tok = (req.args.get("token") or "").strip() if hasattr(req, "args") else ""
    if q_tok.startswith(MCP_TOKEN_PREFIX):
        return q_tok
    return None


def _authenticate_mcp_request(
    limiter: RateLimiter,
    req: Any,
    db_path: Union[str, Path],
    auth_fail_limits: Sequence[str],
    telemetry_cb: Optional[Callable[[Dict[str, Any]], None]],
    server_secret_resolver: Optional[Callable[[], Union[bytes, str]]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Response]]:
    """
    Verifies MCP bearer token. If invalid, applies auth_fail rate limiting and returns 401 or 429.
    """
    raw_token = _extract_mcp_token(req)
    server_sec = None
    if raw_token and server_secret_resolver is not None:
        try:
            server_sec = server_secret_resolver()
        except Exception:
            server_sec = None
    token_ctx = (
        verify_mcp_token(db_path, raw_token, server_secret=server_sec) if raw_token else None
    )
    if token_ctx is not None:
        return token_ctx, None

    allowed, retry_after, exceeded = limiter.evaluate(*auth_fail_limits, scope="mcp_auth_fail")
    if not allowed:
        if telemetry_cb:
            telemetry_cb({
                "event_type": "rate_limit_hit",
                "scope": "mcp_auth_fail",
                "owner_id": None,
                "token_id": None,
            })
        _record_rate_limit_telemetry(exceeded)
        resp = jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32029,
                "message": f"Rate limit exceeded: {exceeded}",
                "data": {"retry_after": retry_after},
            },
        })
        resp.status_code = 429
        resp.headers["Retry-After"] = str(retry_after)
        return None, resp

    if not raw_token and (
        session.get("is_demo")
        or session.get("role") == "viewer"
        or session.get("universe") == "demo"
    ):
        err_demo = jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32003, "message": "Forbidden: Demo or viewer sessions cannot invoke MCP gateway"},
        })
        err_demo.status_code = 403
        return None, err_demo

    err_resp = jsonify({
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32001, "message": "Unauthorized: Invalid or missing MCP token"},
    })
    err_resp.status_code = 401
    err_resp.headers["WWW-Authenticate"] = 'Bearer realm="MCP"'
    return None, err_resp


def _enforce_tool_rate_limit(
    limiter: RateLimiter,
    payload: Dict[str, Any],
    token_ctx: Dict[str, Any],
    registry: MCPToolRegistry,
    read_limits: Sequence[str],
    sim_limits: Sequence[str],
    telemetry_cb: Optional[Callable[[Dict[str, Any]], None]],
) -> Optional[Response]:
    """
    Checks per-token rate limits based on tool tier (simulate vs read) prior to execution.
    """
    if payload.get("method") != "tools/call":
        return None

    params = payload.get("params") or {}
    tool_name = params.get("name")
    tool_meta = registry.get_tool_meta(tool_name) if tool_name else None
    if not tool_meta:
        return None

    tier = tool_meta.get("tier", "read")
    limits = sim_limits if tier == "simulate" else read_limits
    scope = f"mcp_{tier}"
    client_key = f"mcp_tok:{token_ctx['token_id']}"

    allowed, retry_after, exceeded = limiter.evaluate(*limits, scope=scope, client_key=client_key)
    if allowed:
        return None

    if telemetry_cb:
        telemetry_cb({
            "event_type": "rate_limit_hit",
            "scope": scope,
            "owner_id": token_ctx["owner_id"],
            "token_id": token_ctx["token_id"],
        })
    _record_rate_limit_telemetry(exceeded)

    resp = jsonify({
        "jsonrpc": "2.0",
        "id": payload.get("id"),
        "error": {
            "code": -32029,
            "message": f"Rate limit exceeded: {exceeded}",
            "data": {"retry_after": retry_after},
        },
    })
    resp.status_code = 429
    resp.headers["Retry-After"] = str(retry_after)
    return resp


def create_mcp_blueprint(
    registry: MCPToolRegistry,
    *,
    db_path_resolver: Callable[[], Union[str, Path]],
    service_name: str = "hvl-mcp",
    url_prefix: str = "/mcp",
    read_rate_limits: Sequence[str] = ("30/min", "300/hr"),
    simulate_rate_limits: Sequence[str] = ("10/min", "60/hr"),
    auth_fail_rate_limits: Sequence[str] = ("10/min", "30/hr"),
    telemetry_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    server_secret_resolver: Optional[Callable[[], Union[bytes, str]]] = None,
) -> Blueprint:
    """
    Constructs and configures a Flask Blueprint for the MCP JSON-RPC 2.0 gateway.
    """
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", service_name).strip("_") or "hvl_mcp"
    bp = Blueprint(f"{safe_name}_gateway", __name__, url_prefix=url_prefix)
    limiter = RateLimiter()

    @bp.route("", methods=["GET", "POST"])
    @bp.route("/", methods=["GET", "POST"])
    def mcp_endpoint() -> Any:
        if request.method == "GET":
            return jsonify({
                "status": "ok",
                "protocol": "mcp-streamable-http",
                "service": service_name,
            })

        db_path = db_path_resolver()
        token_ctx, auth_err = _authenticate_mcp_request(
            limiter,
            request,
            db_path,
            auth_fail_rate_limits,
            telemetry_callback,
            server_secret_resolver=server_secret_resolver,
        )
        if auth_err is not None:
            return auth_err

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error: Invalid JSON"},
            }), 400

        limit_err = _enforce_tool_rate_limit(
            limiter, payload, token_ctx, registry, read_rate_limits, simulate_rate_limits, telemetry_callback
        )
        if limit_err is not None:
            return limit_err

        resp, status, call_meta = handle_jsonrpc_request(registry, payload, token_ctx=token_ctx)
        if resp is None:
            return ("", status)

        if call_meta and status == 200 and "error" not in resp:
            record_mcp_token_usage(db_path, token_ctx["token_id"])
            if telemetry_callback:
                telemetry_callback({
                    "event_type": "mcp_tool_call",
                    "tool_name": call_meta["tool_name"],
                    "tier": call_meta["tier"],
                    "scope": call_meta["scope"],
                    "owner_id": token_ctx["owner_id"],
                    "user_email": token_ctx.get("user_email", ""),
                    "token_id": token_ctx["token_id"],
                    "token_prefix": token_ctx.get("token_prefix", ""),
                })

        return jsonify(resp), status

    return bp
