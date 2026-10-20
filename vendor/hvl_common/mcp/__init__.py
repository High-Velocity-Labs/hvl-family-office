"""
Model Context Protocol (MCP) Server & Token Infrastructure for High Velocity Labs.
Standardizes secure JSON-RPC 2.0 tool exposure, individual member tokens within households,
schema introspection, scope enforcement, and multi-worker rate limiting.
"""

from hvl_common.mcp.blueprint import create_mcp_blueprint
from hvl_common.mcp.server import (
    MCPToolRegistry,
    get_active_mcp_token_context,
    handle_jsonrpc_request,
    introspect_callable_schema,
)
from hvl_common.mcp.tokens import (
    MCP_TOKEN_PREFIX,
    ensure_mcp_tokens_table,
    generate_raw_token,
    hash_mcp_token,
    list_mcp_tokens,
    mint_mcp_token,
    record_mcp_token_usage,
    revoke_mcp_token,
    set_mcp_owner_enabled,
    verify_mcp_token,
)

__all__ = [
    "MCP_TOKEN_PREFIX",
    "generate_raw_token",
    "hash_mcp_token",
    "ensure_mcp_tokens_table",
    "mint_mcp_token",
    "verify_mcp_token",
    "record_mcp_token_usage",
    "list_mcp_tokens",
    "set_mcp_owner_enabled",
    "revoke_mcp_token",
    "introspect_callable_schema",
    "MCPToolRegistry",
    "get_active_mcp_token_context",
    "handle_jsonrpc_request",
    "create_mcp_blueprint",
]
