# qontinui-hal-mcp

GhostDesk-compatible MCP server exposing qontinui's HAL (screen capture,
mouse, keyboard) to external agents. Tool names mirror GhostDesk
(`screen_shot`, `mouse_move`, `mouse_click`, `mouse_scroll`, `key_type`,
`key_press`, `get_screen_size`) so clients written for GhostDesk run
against qontinui unmodified.

## Usage

```
# stdio (default)
QONTINUI_HAL_MCP_TOKEN=... poetry run qontinui-hal-mcp --allow-input

# HTTP (container-to-host, Phase 2)
QONTINUI_HAL_MCP_TOKEN=... poetry run qontinui-hal-mcp --http --host 0.0.0.0 --port 7801 --allow-input
```

Every call requires the bearer token in the `Authorization: Bearer <token>`
header (HTTP) or the `auth_token` argument (stdio). Input tools
(`mouse_*`, `key_*`) are disabled unless `--allow-input` is passed.
**Do not expose this surface to untrusted clients.**
