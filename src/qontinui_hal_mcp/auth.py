"""Bearer-token auth for qontinui-hal-mcp.

This surface can drive the host machine. We refuse to start without a
token, and every tool call has to present it.
"""

from __future__ import annotations

import hmac
import os

_ENV_VAR = "QONTINUI_HAL_MCP_TOKEN"
_loaded_token: str | None = None


class AuthError(RuntimeError):
    """Raised when auth is missing or invalid."""


def load_token() -> str:
    """Read the bearer token from env once per process.

    Refuses to return a token that is unset/empty rather than silently
    allowing every request — the caller already decided to expose
    machine-level control, we don't double down by disabling auth.
    """
    global _loaded_token
    if _loaded_token is not None:
        return _loaded_token
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        raise AuthError(
            f"{_ENV_VAR} is not set. qontinui-hal-mcp refuses to run without "
            "an API bearer token because this surface controls the host "
            "machine."
        )
    _loaded_token = raw
    return _loaded_token


def verify_token(presented: str | None) -> bool:
    """Constant-time compare; returns False on any mismatch or missing token."""
    if not presented:
        return False
    try:
        expected = load_token()
    except AuthError:
        return False
    return hmac.compare_digest(expected, presented)


def extract_bearer(header_value: str | None) -> str | None:
    """Pull token out of an `Authorization: Bearer <token>` header."""
    if not header_value:
        return None
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
