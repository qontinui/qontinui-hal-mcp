"""HTTP transport for qontinui-hal-mcp.

Phase 2 (eval-desktop container) needs a container-to-host transport;
stdio is in-process only. We expose the same tool surface as the stdio
server over two JSON POST endpoints:

    POST /mcp/list_tools      -> {"tools": [...]}
    POST /mcp/call_tool       -> {"name": str, "arguments": {...}}
                                  -> tool result dict

Every request must carry `Authorization: Bearer <token>`. We intentionally
do not speak the full MCP-over-HTTP streaming protocol here — the eval
desktop is a trusted network peer that only needs request/response
semantics, and speaking the JSON-RPC-over-HTTP framing would require
either the full streamable_http session machinery or a hand-rolled SSE
layer. This thin wrapper stays small and routes straight into the same
`HalMcpTools.dispatch` that stdio uses.
"""

from __future__ import annotations

import logging
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth import extract_bearer, verify_token
from .tools import TOOL_PERMISSIONS, TOOLS, HalMcpTools, PermissionLevel, ToolError

logger = logging.getLogger(__name__)


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.inputSchema,
    }


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {
            "success": False,
            "error_code": "unauthorized",
            "error": (
                "Missing or invalid bearer token. Send "
                "'Authorization: Bearer <token>' matching "
                "QONTINUI_HAL_MCP_TOKEN."
            ),
        },
        status_code=401,
    )


def _check_auth(request: Request) -> bool:
    token = extract_bearer(request.headers.get("authorization"))
    return verify_token(token)


def build_app(tools: HalMcpTools) -> Starlette:
    """Build a Starlette app bound to the given tool dispatcher."""

    async def list_tools(request: Request) -> JSONResponse:
        if not _check_auth(request):
            return _unauthorized()
        return JSONResponse({"tools": [_tool_to_dict(t) for t in TOOLS]})

    async def call_tool(request: Request) -> JSONResponse:
        if not _check_auth(request):
            return _unauthorized()
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(
                {
                    "success": False,
                    "error_code": "invalid_json",
                    "error": "Request body is not valid JSON.",
                },
                status_code=400,
            )
        name = body.get("name")
        arguments = body.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return JSONResponse(
                {
                    "success": False,
                    "error_code": "invalid_request",
                    "error": 'Body must be {"name": str, "arguments": object}.',
                },
                status_code=400,
            )

        level = TOOL_PERMISSIONS.get(name, PermissionLevel.DANGEROUS)
        logger.info("http_tool_call name=%s level=%s", name, level.value)

        try:
            result = await tools.dispatch(name, arguments)
        except ToolError as e:
            return JSONResponse(e.as_dict(), status_code=400)
        except Exception as e:
            logger.exception("http_tool_call_error name=%s", name)
            return JSONResponse(
                {
                    "success": False,
                    "error_code": "internal_error",
                    "error": f"{type(e).__name__}: {e}",
                },
                status_code=500,
            )
        return JSONResponse(result)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": "qontinui-hal-mcp"})

    return Starlette(
        routes=[
            Route("/mcp/list_tools", list_tools, methods=["POST"]),
            Route("/mcp/call_tool", call_tool, methods=["POST"]),
            Route("/health", health, methods=["GET"]),
        ]
    )


def serve_http(tools: HalMcpTools, host: str, port: int) -> None:
    """Run the HTTP transport (blocking)."""
    app = build_app(tools)
    logger.info("qontinui-hal-mcp HTTP server starting on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
