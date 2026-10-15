# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-15

Scene resolution control, exposure timing, and image compositing — plus three
correctness bugs in level import.

### Added
- **`opentoonz_set_scene_settings`** — change a scene's camera resolution
  and/or fps (e.g. 1080p → 720p). OpenToonz's scripting API has no setter
  (`scene.setCameraSize` does not exist), so the scene's XML is patched
  directly; the setting survives later edits to the scene. The camera's
  *physical* size is rescaled with it, so art drawn at the scene's size still
  fills the frame (leaving it at the 16×9 default while shrinking the
  resolution renders 640×360 art as a 213×120 box). `opentoonz_scene_new`
  accepts `width`/`height`/`fps` too.
- **`opentoonz_exposure`** — time a level by holding each drawing for N frames.
  `[3]` holds everything on 3s; `[2, 4, 1]` sets per-drawing holds. This is
  animation-native vocabulary and saves computing rows by hand.
- **Drawing op `{"op": "image", ...}`** — composite an existing PNG (optional
  `size` and `opacity`) into a drawn frame, so art made elsewhere can join one.
- `opentoonz_scene_info` takes `max_rows` and now reports `cells_truncated`
  instead of silently stopping at 1000 rows.
- `scripts/probe_api.py` — a re-runnable survey of the OpenToonz scripting API,
  so a future OpenToonz upgrade can be re-probed rather than guessed at.
- Unit tests for scene settings, exposure timing, and level import that need no
  OpenToonz runtime (90 unit + 12 e2e).

### Fixed
- **Re-importing a level name no longer fails.** OpenToonz rejects a duplicate
  level name (`Can't add the level: name(...) is already used`) and has no
  `removeLevel`, so an existing level is now *reused* and its drawings
  overwritten. The draw → import → render → redraw loop now works.
- **Shrinking a level no longer leaves orphaned drawings.** Importing 5 frames
  then 3 left `level.0004.png`/`.0005.png` on disk, and `loadLevel`'s `..`
  pattern loaded them back, producing a level with stale extra frames.
- Importing art that already lives in `drawings/` no longer deletes it — the
  stale-frame cleanup spares the files being imported.
- A failed import no longer removes existing drawings: sources are validated
  before anything is deleted.
- Level names are validated (letters, digits, `_`, `-`; up to 64 characters),
  since the name becomes a file prefix.
- `license` is now a PEP 639 SPDX expression; `LICENSE` and `NOTICE` ship in the
  wheel and the deprecated license classifier is gone.

### Changed
- `scenes.import_level()` returns a `LevelImport` (result, copied, reused,
  frame_count) rather than a `(result, copied)` tuple.
- `scenes.scene_new()` returns the resulting `SceneSettings`.
- Tool count is now 16.

### Documented
- SVG / **Vector levels import but rasterise to nothing** when rendered
  headlessly, and `level.setFrame()` on a loaded level **never reaches the
  renderer**. Both are recorded in `docs/runtime-notes.md` and
  `docs/troubleshooting.md`, and an SVG passed to the import tool is rejected
  with that explanation.

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
