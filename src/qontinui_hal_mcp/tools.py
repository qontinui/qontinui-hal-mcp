"""Tool registry + HAL delegation for qontinui-hal-mcp.

Tool names mirror GhostDesk's MCP surface (`screen_shot`, `mouse_move`,
`mouse_click`, `mouse_scroll`, `key_type`, `key_press`, `get_screen_size`)
so GhostDesk-targeted client code drives qontinui unmodified. Each tool
delegates to qontinui's HAL — HAL methods are synchronous, so every call
is wrapped in `asyncio.to_thread` to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from enum import Enum
from typing import Any

from mcp import types
from PIL import Image

logger = logging.getLogger(__name__)


# Inlined rather than imported from qontinui_mcp because qontinui-hal-mcp is
# a standalone package; importing across package roots would require pinning
# qontinui-mcp as a hard dep for a 4-value enum.
class PermissionLevel(Enum):
    """Coarse auth gate for tool dispatch."""

    READ_ONLY = "read_only"
    DANGEROUS = "dangerous"


TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    "screen_shot": PermissionLevel.READ_ONLY,
    "get_screen_size": PermissionLevel.READ_ONLY,
    "mouse_move": PermissionLevel.DANGEROUS,
    "mouse_click": PermissionLevel.DANGEROUS,
    "mouse_scroll": PermissionLevel.DANGEROUS,
    "key_type": PermissionLevel.DANGEROUS,
    "key_press": PermissionLevel.DANGEROUS,
}


TOOLS: list[types.Tool] = [
    types.Tool(
        name="screen_shot",
        description=(
            "Capture a screenshot. If `region` is provided, captures that "
            "rect; otherwise captures the full virtual desktop. Returns "
            "PNG image as base64 plus pixel dimensions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "w": {"type": "integer"},
                        "h": {"type": "integer"},
                    },
                    "required": ["x", "y", "w", "h"],
                }
            },
        },
    ),
    types.Tool(
        name="mouse_move",
        description="Move mouse cursor to absolute screen coords.",
        inputSchema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
    ),
    types.Tool(
        name="mouse_click",
        description=(
            "Click mouse button at (x, y). `button` is one of 'left', "
            "'right', 'middle'. `double=true` performs a double-click."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                },
                "double": {"type": "boolean", "default": False},
            },
            "required": ["x", "y"],
        },
    ),
    types.Tool(
        name="mouse_scroll",
        description=(
            "Scroll at (x, y). `dy` is the wheel click count; positive "
            "scrolls up, negative scrolls down."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "dy": {"type": "integer"},
            },
            "required": ["x", "y", "dy"],
        },
    ),
    types.Tool(
        name="key_type",
        description="Type a text string via the keyboard.",
        inputSchema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    ),
    types.Tool(
        name="key_press",
        description=(
            "Press a key or key combo. A single-element list presses that "
            "key; a multi-element list fires a hotkey (e.g. "
            "['ctrl', 'shift', 't'])."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                }
            },
            "required": ["keys"],
        },
    ),
    types.Tool(
        name="get_screen_size",
        description="Return (w, h) of the primary monitor in pixels.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


class ToolError(Exception):
    """Structured error surfaced back to MCP callers."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, Any]:
        return {"success": False, "error_code": self.code, "error": self.message}


class HalMcpTools:
    """HAL-backed tool dispatcher.

    Instantiates the HAL lazily: screen capture on first read-only call,
    keyboard/mouse on first input call. Lazy init keeps `--allow-input`
    off-by-default genuinely cheap — we don't construct pynput controllers
    just to serve a `screen_shot`.
    """

    def __init__(self, *, allow_input: bool) -> None:
        self._allow_input = allow_input
        self._screen: Any | None = None
        self._mouse: Any | None = None
        self._keyboard: Any | None = None

    def _get_screen(self) -> Any:
        if self._screen is None:
            from qontinui.hal.factory import HALFactory

            self._screen = HALFactory.get_screen_capture()
        return self._screen

    def _get_mouse(self) -> Any:
        if self._mouse is None:
            from qontinui.hal.factory import HALFactory

            self._mouse = HALFactory.get_mouse_controller()
        return self._mouse

    def _get_keyboard(self) -> Any:
        if self._keyboard is None:
            from qontinui.hal.factory import HALFactory

            self._keyboard = HALFactory.get_keyboard_controller()
        return self._keyboard

    def _require_input(self, tool_name: str) -> None:
        if not self._allow_input:
            raise ToolError(
                "input_disabled",
                f"Tool '{tool_name}' requires --allow-input at server "
                "startup. Input is disabled by default because "
                "qontinui-hal-mcp exposes host-level input control.",
            )

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "screen_shot":
            return await self._screen_shot(args)
        if name == "get_screen_size":
            return await self._get_screen_size()
        if name == "mouse_move":
            self._require_input(name)
            return await self._mouse_move(args)
        if name == "mouse_click":
            self._require_input(name)
            return await self._mouse_click(args)
        if name == "mouse_scroll":
            self._require_input(name)
            return await self._mouse_scroll(args)
        if name == "key_type":
            self._require_input(name)
            return await self._key_type(args)
        if name == "key_press":
            self._require_input(name)
            return await self._key_press(args)
        raise ToolError("unknown_tool", f"Unknown tool: {name}")

    async def _screen_shot(self, args: dict[str, Any]) -> dict[str, Any]:
        region = args.get("region")
        screen = self._get_screen()

        def _capture() -> Image.Image:
            if region:
                img = screen.capture_region(
                    int(region["x"]),
                    int(region["y"]),
                    int(region["w"]),
                    int(region["h"]),
                )
            else:
                img = screen.capture_screen()
            assert isinstance(img, Image.Image)
            return img

        image = await asyncio.to_thread(_capture)
        buf = io.BytesIO()
        await asyncio.to_thread(image.save, buf, "PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return {
            "success": True,
            "image_base64": encoded,
            "width": image.width,
            "height": image.height,
        }

    async def _get_screen_size(self) -> dict[str, Any]:
        screen = self._get_screen()
        w, h = await asyncio.to_thread(screen.get_screen_size)
        return {"success": True, "w": int(w), "h": int(h)}

    async def _mouse_move(self, args: dict[str, Any]) -> dict[str, Any]:
        x = int(args["x"])
        y = int(args["y"])
        mouse = self._get_mouse()
        ok = await asyncio.to_thread(mouse.mouse_move, x, y)
        return {"success": bool(ok), "x": x, "y": y}

    async def _mouse_click(self, args: dict[str, Any]) -> dict[str, Any]:
        from qontinui.hal.interfaces.mouse_controller import MouseButton

        x = int(args["x"])
        y = int(args["y"])
        button_str = str(args.get("button", "left")).lower()
        try:
            button = MouseButton(button_str)
        except ValueError as e:
            raise ToolError("invalid_button", str(e)) from None
        double = bool(args.get("double", False))
        clicks = 2 if double else 1
        mouse = self._get_mouse()
        ok = await asyncio.to_thread(
            mouse.mouse_click, x, y, button, clicks, 0.1 if double else 0.0
        )
        return {
            "success": bool(ok),
            "x": x,
            "y": y,
            "button": button_str,
            "double": double,
        }

    async def _mouse_scroll(self, args: dict[str, Any]) -> dict[str, Any]:
        x = int(args["x"])
        y = int(args["y"])
        dy = int(args["dy"])
        mouse = self._get_mouse()
        # HAL signature is (clicks, x=None, y=None) with positive=up;
        # GhostDesk's `dy` uses the same convention.
        ok = await asyncio.to_thread(mouse.mouse_scroll, dy, x, y)
        return {"success": bool(ok), "x": x, "y": y, "dy": dy}

    async def _key_type(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args["text"])
        keyboard = self._get_keyboard()
        ok = await asyncio.to_thread(keyboard.type_text, text)
        return {"success": bool(ok), "chars": len(text)}

    async def _key_press(self, args: dict[str, Any]) -> dict[str, Any]:
        raw_keys = args.get("keys") or []
        if not isinstance(raw_keys, list) or not raw_keys:
            raise ToolError("invalid_keys", "keys must be a non-empty string array")
        keys = [str(k) for k in raw_keys]
        keyboard = self._get_keyboard()
        if len(keys) == 1:
            ok = await asyncio.to_thread(keyboard.key_press, keys[0])
        else:
            ok = await asyncio.to_thread(keyboard.hotkey, *keys)
        return {"success": bool(ok), "keys": keys}
