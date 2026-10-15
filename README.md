# opentoonz-mcp

**Headless OpenToonz automation for AI agents — as a [Model Context Protocol](https://modelcontextprotocol.io) server.**

`opentoonz-mcp` lets an agent drive [OpenToonz](https://github.com/opentoonz/opentoonz) — levels, xsheets, cells, rendering, video — entirely from the command line. No GUI, no plugin build, no mouse.

It works by running OpenToonz's **built-in scripting engine** in CLI mode and the official **`tcomposer`** headless renderer, then exposing the useful primitives as MCP tools.

<!-- Replace with real badges after publishing -->
![CI](https://img.shields.io/badge/ci-github_actions-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

---

## Why

OpenToonz is a deep, industry-grade 2D animation suite, but its scripting API is headless-only and awkward to reach. This server turns the validated, hard-won runtime recipe into a small, safe, well-documented tool surface an agent can actually use:

- **Create a workspace** → **draw or import frames as a level** → **place cells on the xsheet** → **render a frame to look at it** → **render a video**.
- A generic `opentoonz_run_script` escape hatch exposes the rest of the JS API.
- Runs stay **self-contained**: an isolated `HOME` and a shared `TOONZROOT`, so nothing leaks into your real OpenToonz config.

## How it works

```
MCP client (agent)
      │  tool calls (stdio)
      ▼
opentoonz-mcp server
      │  writes <workspace>/scripts/*.toonzscript  +  PIL-drawn RGBA frames
      ▼
OpenToonz CLI  (script mode, no window)
      │
      ▼
tcomposer  (official headless renderer)  →  PNG frames  →  ffmpeg  →  MP4
```

> The extracted AppImage binary is run **directly** — its `AppRun` launcher mangles CLI arguments and drops into GUI mode.

## Requirements

| Requirement | Notes |
|---|---|
| Python | 3.10+ |
| OpenToonz | v1.x with `tcomposer`. On Linux, an extracted AppImage works best. |
| ffmpeg | Only for `opentoonz_render_video` |

See **[docs/installation.md](docs/installation.md)** for how to obtain and point at a runtime.

## Install

```bash
# from a checkout
pipx install .
# or
uv tool install .
# or for development
pip install -e ".[dev]"
```

The `opentoonz-mcp` console script starts the stdio server.

## Configure your MCP client

**OpenCode** (`~/.config/opencode/opencode.jsonc`):

```jsonc
{
  "mcp": {
    "opentoonz": {
      "type": "local",
      "command": ["opentoonz-mcp"],
      "enabled": true,
      "environment": {
        "OPENTOONZ_RUNTIME": "/path/to/opentoonz/squashfs-root"
      }
    }
  }
}
```

**Claude Desktop / Cursor** (`mcpServers`):

```json
{
  "mcpServers": {
    "opentoonz": {
      "command": "opentoonz-mcp",
      "env": { "OPENTOONZ_RUNTIME": "/path/to/opentoonz/squashfs-root" }
    }
  }
}
```

## Quickstart

Ask your agent to:

1. `opentoonz_create_workspace("my-short")`
2. `opentoonz_draw_frames(...)` — draw a few RGBA frames, **or** generate PNGs elsewhere
3. `opentoonz_import_images_as_level(...)` — bring them in as a level
4. `opentoonz_render_frame(...)` — look at the result
5. `opentoonz_render_video(...)` — get an MP4

Or run the example end-to-end:

```bash
OPENTOONZ_RUNTIME=/path/to/squashfs-root python examples/bouncing_ball.py
```

## Tools

| Tool | Purpose |
|---|---|
| `opentoonz_health` | Quick availability check |
| `opentoonz_doctor` | Full diagnostics (paths, versions, state) |
| `opentoonz_create_workspace` | Create a workspace (idempotent) |
| `opentoonz_list_workspaces` | Inventory workspaces/scenes/videos |
| `opentoonz_scene_new` | Create an empty scene |
| `opentoonz_import_images_as_level` | Image sequence → raster level (additive) |
| `opentoonz_scene_info` | Frames/columns/levels/cells |
| `opentoonz_set_cells` | Place cells on the xsheet |
| `opentoonz_draw_frame` | Draw one RGBA frame (PIL primitives) |
| `opentoonz_draw_frames` | Draw a whole sequence |
| `opentoonz_render_frame` | Render one frame (the "look") |
| `opentoonz_render` | Render PNG frames via `tcomposer` |
| `opentoonz_render_video` | Render + ffmpeg → MP4 |
| `opentoonz_run_script` | Arbitrary OpenToonz JS (escape hatch) |

Full reference, including the drawing-op schema: **[docs/tools.md](docs/tools.md)**.

## Limitations

OpenToonz's JS API is a **subset** of the GUI. Not reachable today:

- FX graphs, palette editing, camera splines, auto-inbetweening, audio tracks.
- Only **raster** levels are exercised end-to-end (vector/`ToonzRaster` are untested).
- Rendering needs a working `tcomposer`; `Renderer.renderFrame` **deadlocks** in CLI mode and is intentionally avoided.

Workarounds and the full picture: **[docs/runtime-notes.md](docs/runtime-notes.md)**.

## Troubleshooting

See **[docs/troubleshooting.md](docs/troubleshooting.md)** — it covers the common failure modes (GUI-mode hangs, black renders, `tcomposer` exceptions).

## Development

```bash
pip install -e ".[dev]"
pytest -m "not e2e"      # fast unit tests
pytest -m e2e            # requires a runtime (OPENTOONZ_RUNTIME=...)
ruff check .
```

Architecture notes live in **[docs/architecture.md](docs/architecture.md)**.

## License & attribution

MIT — see [LICENSE](LICENSE). This is an unofficial project and is **not** affiliated with OpenToonz. OpenToonz is BSD-3-Clause and is **not** bundled here. See [NOTICE](NOTICE).
