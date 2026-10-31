"""
MCP Tool Registry, Schema Introspection & JSON-RPC 2.0 Dispatcher (`hvl_common.mcp.server`).
Provides automatic type-hint introspection to JSON Schema, secure parameter filtering
with spoofing protection, and compliant JSON-RPC 2.0 dispatch.
"""

from __future__ import annotations

import contextvars
import inspect
import json
import types
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

_ACTIVE_MCP_TOKEN_CTX: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "_ACTIVE_MCP_TOKEN_CTX", default=None
)


def get_active_mcp_token_context() -> Optional[Dict[str, Any]]:
    """Returns the verified MCP token context dict for the currently executing tool call."""
    return _ACTIVE_MCP_TOKEN_CTX.get()


def _unwrap_optional_type(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is Union or (hasattr(types, "UnionType") and origin is types.UnionType):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _map_python_type_to_schema(annotation: Any) -> str:
    target = _unwrap_optional_type(annotation)
    origin = get_origin(target) or target

    if isinstance(origin, type):
        try:
            if issubclass(origin, bool):
                return "boolean"
            if issubclass(origin, int):
                return "integer"
            if issubclass(origin, float):
                return "number"
            if issubclass(origin, (list, tuple, set, Sequence)) and not issubclass(origin, (str, bytes)):
                return "array"
            if issubclass(origin, (dict, Mapping)):
                return "object"
            if issubclass(origin, (str, bytes)):
                return "string"
        except TypeError:
            pass

    str_repr = str(target).lower()
    if "bool" in str_repr:
        return "boolean"
    if "int" in str_repr:
        return "integer"
    if "float" in str_repr or "decimal" in str_repr:
        return "number"
    if "list" in str_repr or "seq" in str_repr or "tuple" in str_repr:
        return "array"
    if "dict" in str_repr or "map" in str_repr:
        return "object"
    return "string"


def introspect_callable_schema(
    fn: Callable[..., Any],
    *,
    exclude_args: Sequence[str] = ("family_id", "owner_id", "db_path"),
) -> Dict[str, Any]:
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = getattr(fn, "__annotations__", {})

    sig = inspect.signature(fn)
    properties: Dict[str, Any] = {}
    required: List[str] = []
    excluded = set(exclude_args)

    for param_name, param in sig.parameters.items():
        if param_name in excluded or param_name.startswith("_"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        raw_hint = hints.get(param_name, param.annotation)
        schema_type = _map_python_type_to_schema(raw_hint)
        prop_def: Dict[str, Any] = {"type": schema_type, "description": f"Parameter {param_name}"}
        if schema_type == "array":
            prop_def["items"] = {"type": "string"}
        properties[param_name] = prop_def

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {"type": "object", "properties": properties, "required": required}


def _jsonrpc_err(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


class MCPToolRegistry:
    """
    Registry for tools exposed over the Model Context Protocol (MCP).
    Enforces scope-based authorization and mandatory owner_id injection.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(
        self,
        fn: Callable[..., Any],
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        scope: str = "read",
        tier: str = "read",
        inject_arg: Optional[str] = "family_id",
        exclude_args: Sequence[str] = ("family_id", "owner_id", "db_path"),
    ) -> None:
        tool_name = name or fn.__name__
        tool_desc = description or inspect.getdoc(fn) or tool_name
        schema = introspect_callable_schema(fn, exclude_args=exclude_args)
        self._tools[tool_name] = {
            "fn": fn,
            "name": tool_name,
            "description": tool_desc,
            "scope": scope,
            "tier": tier,
            "inject_arg": inject_arg,
            "exclude_args": tuple(exclude_args),
            "inputSchema": schema,
        }

    def tool(
        self,
        name_or_fn: Optional[Union[str, Callable[..., Any]]] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        scope: str = "read",
        tier: str = "read",
        inject_arg: Optional[str] = "family_id",
        exclude_args: Sequence[str] = ("family_id", "owner_id", "db_path"),
    ) -> Any:
        if callable(name_or_fn):
            self.register_tool(
                name_or_fn,
                name=name,
                description=description,
                scope=scope,
                tier=tier,
                inject_arg=inject_arg,
                exclude_args=exclude_args,
            )
            return name_or_fn

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            eff_name = name or (name_or_fn if isinstance(name_or_fn, str) else None)
            self.register_tool(
                fn,
                name=eff_name,
                description=description,
                scope=scope,
                tier=tier,
                inject_arg=inject_arg,
                exclude_args=exclude_args,
            )
            return fn

        return decorator

    def list_tools(self, allowed_scopes: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        allowed = set(allowed_scopes) if allowed_scopes is not None else None
        tools: List[Dict[str, Any]] = []
        for meta in self._tools.values():
            if allowed is not None and meta["scope"] not in allowed:
                continue
            tools.append({
                "name": meta["name"],
                "description": meta["description"],
                "inputSchema": meta["inputSchema"],
            })
        return tools

    def get_tool_meta(self, name: str) -> Optional[Dict[str, Any]]:
        return self._tools.get(name)

    def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        owner_id: int,
        allowed_scopes: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        meta = self.get_tool_meta(name)
        if meta is None:
            raise KeyError(f"Tool {name!r} not found")

        if allowed_scopes is not None and meta["scope"] not in allowed_scopes:
            raise PermissionError(f"Scope {meta['scope']!r} not permitted for tool {name!r}")

        fn = meta["fn"]
        sig = inspect.signature(fn)
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

        kwargs: Dict[str, Any] = {}
        if arguments:
            if has_var_kw:
                kwargs.update(arguments)
            else:
                for k, v in arguments.items():
                    if k in sig.parameters:
                        kwargs[k] = v

        inject = meta.get("inject_arg")
        if inject and (inject in sig.parameters or has_var_kw):
            kwargs[inject] = owner_id

        result = fn(**kwargs)
        structured = result if isinstance(result, dict) else {"result": result}
        return {
            "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            "structuredContent": structured,
            "isError": False,
        }


def handle_jsonrpc_request(
    registry: MCPToolRegistry,
    payload: Any,
    *,
    token_ctx: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], int, Optional[Dict[str, Any]]]:
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        req_id = payload.get("id") if isinstance(payload, dict) else None
        return _jsonrpc_err(req_id, -32600, "Invalid JSON-RPC 2.0 request"), 400, None

    req_id = payload.get("id")
    method = payload.get("method")

    if method == "initialize":
        init_res = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "hvl-mcp-gateway", "version": "1.0.0"},
        }
        return ({"jsonrpc": "2.0", "id": req_id, "result": init_res}, 200, None)

    if method == "notifications/initialized":
        return (None, 202, None)

    if method == "ping":
        return ({"jsonrpc": "2.0", "id": req_id, "result": {}}, 200, None)

    if method == "tools/list":
        scopes = token_ctx.get("scopes")
        return (
            {"jsonrpc": "2.0", "id": req_id, "result": {"tools": registry.list_tools(scopes)}},
            200,
            None,
        )

    if method == "tools/call":
        params = payload.get("params") or {}
        tool_name = params.get("name")
        if not tool_name:
            return _jsonrpc_err(req_id, -32602, "Missing tool name"), 200, None

        tool_meta = registry.get_tool_meta(tool_name)
        if tool_meta is None:
            return _jsonrpc_err(req_id, -32601, f"Tool '{tool_name}' not found"), 200, None

        allowed_scopes = token_ctx.get("scopes")
        if allowed_scopes is not None and tool_meta["scope"] not in allowed_scopes:
            msg = f"Forbidden: scope '{tool_meta['scope']}' not permitted"
            return _jsonrpc_err(req_id, -32003, msg), 200, None

        try:
            ctx_token = _ACTIVE_MCP_TOKEN_CTX.set(token_ctx)
            try:
                res = registry.call_tool(
                    tool_name,
                    params.get("arguments"),
                    owner_id=token_ctx["owner_id"],
                    allowed_scopes=allowed_scopes,
                )
            finally:
                _ACTIVE_MCP_TOKEN_CTX.reset(ctx_token)
            call_meta = {
                "tool_name": tool_name,
                "tier": tool_meta["tier"],
                "scope": tool_meta["scope"],
            }
            return ({"jsonrpc": "2.0", "id": req_id, "result": res}, 200, call_meta)
        except (TypeError, ValueError) as err:
            return _jsonrpc_err(req_id, -32602, str(err)), 200, None
        except PermissionError as err:
            return _jsonrpc_err(req_id, -32003, str(err)), 200, None
        except KeyError as err:
            return _jsonrpc_err(req_id, -32601, str(err)), 200, None
        except Exception as err:
            return _jsonrpc_err(req_id, -32603, str(err)), 200, None

    return _jsonrpc_err(req_id, -32601, f"Method '{method}' not found"), 200, None
