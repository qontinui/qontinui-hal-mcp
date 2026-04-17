"""CLI entry point for qontinui-hal-mcp."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .auth import AuthError, load_token
from .tools import HalMcpTools


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qontinui-hal-mcp",
        description=(
            "GhostDesk-compatible MCP server exposing qontinui's HAL. "
            "Requires QONTINUI_HAL_MCP_TOKEN env var. Input tools "
            "(mouse_*, key_*) require --allow-input."
        ),
    )
    parser.add_argument(
        "--allow-input",
        action="store_true",
        help="Enable input tools (mouse_move/click/scroll, key_type/press). "
        "Off by default because the surface controls the host machine.",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use HTTP transport instead of stdio. Required for "
        "container-to-host wiring (Phase 2 eval desktop).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=7801, help="HTTP bind port.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        load_token()
    except AuthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    tools = HalMcpTools(allow_input=args.allow_input)

    if args.http:
        from .http_server import serve_http

        serve_http(tools, host=args.host, port=args.port)
        return 0

    from .server import serve_stdio

    asyncio.run(serve_stdio(tools))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
