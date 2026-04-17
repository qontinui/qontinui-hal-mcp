"""Stdio MCP server for qontinui-hal-mcp.

Follows the same shape as `qontinui-mcp/src/qontinui_mcp/server.py`:
`mcp` SDK, stdio transport, manual `list_tools()` + `call_tool()` dispatch,
permission-gated calls. Auth is verified via an `auth_token` argument on
every call because stdio has no transport-level header; HTTP transport
uses the standard `Authorization: Bearer <token>` header instead.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .auth import verify_token
from .tools import TOOL_PERMISSIONS, TOOLS, HalMcpTools, PermissionLevel, ToolError

logger = logging.getLogger(__name__)


def build_server(tools: HalMcpTools) -> Server:
    """Build an MCP `Server` bound to the given tool dispatcher."""
    server: Server = Server("qontinui-hal-mcp")

    @server.list_tools()  # type: ignore[untyped-decorator,no-untyped-call]
    async def _list_tools() -> list[types.Tool]:
        return TOOLS

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        args = dict(arguments or {})
        presented = args.pop("auth_token", None)
        if not verify_token(presented):
            payload = {
                "success": False,
                "error_code": "unauthorized",
                "error": (
                    "Missing or invalid auth_token. Every qontinui-hal-mcp "
                    "call must include auth_token matching "
                    "QONTINUI_HAL_MCP_TOKEN."
                ),
            }
            return [types.TextContent(type="text", text=json.dumps(payload))]

        level = TOOL_PERMISSIONS.get(name, PermissionLevel.DANGEROUS)
        logger.info("tool_call name=%s level=%s", name, level.value)

        try:
            result = await tools.dispatch(name, args)
        except ToolError as e:
            return [types.TextContent(type="text", text=json.dumps(e.as_dict()))]
        except Exception as e:
            logger.exception("tool_call_error name=%s", name)
            payload = {
                "success": False,
                "error_code": "internal_error",
                "error": f"{type(e).__name__}: {e}",
            }
            return [types.TextContent(type="text", text=json.dumps(payload))]

        return [types.TextContent(type="text", text=json.dumps(result))]

    return server


async def serve_stdio(tools: HalMcpTools) -> None:
    """Run the stdio transport."""
    server = build_server(tools)
    logger.info("qontinui-hal-mcp stdio server starting")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )
