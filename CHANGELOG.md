# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-15

First public release. A headless, MCP-exposed automation layer for OpenToonz.

### Added
- MCP server (`opentoonz-mcp`) with 14 tools covering workspaces, scenes,
  levels, cells, drawing, rendering, and a generic script escape hatch.
- `draw.py`: a small PIL frame-authoring layer (rect/ellipse/line/polygon/
  polyline/text) producing RGBA PNG level frames.
- `opentoonz_render_frame` — a single-frame "look" so agents can review output.
- Additive multi-level / multi-column level import.
- Shared `TOONZROOT` + isolated `HOME`, so runs are self-contained and never
  touch the user's real OpenToonz configuration.
- Automatic RGBA conversion of imported images.
- Diagnostic tools (`opentoonz_health`, `opentoonz_doctor`).
- Runtime discovery (extracted AppImage, explicit binaries, or `PATH`).
- Test suite: unit tests plus runtime-gated end-to-end tests.
- Documentation: installation, tool reference, architecture, runtime notes,
  and troubleshooting.

### Fixed
- Level import is no longer destructive: an existing scene is loaded first
  instead of being replaced by a fresh `new Scene()`.
- Renders clear stale frames with the same output prefix, so frame counts and
  MP4s stay correct after a shorter re-render.
- Robust subprocess handling: deterministic script names, SIGKILL timeouts, and
  marker-based success detection (OpenToonz exits non-zero even on success).
