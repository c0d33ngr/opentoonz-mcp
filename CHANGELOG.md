# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.0] - 2026-10-16

### Added
- **Confirmation prompts for destructive tools.** `opentoonz_clean` and
  `opentoonz_delete_workspace` now ask the user through MCP elicitation when the
  client supports it, instead of only accepting a `confirm=true` flag the model
  fills in itself. `confirm=true` remains the explicit non-interactive path
  (automation and tests); with no way to ask — no client context, or an
  unsupported client — they fail closed.
- **`opentoonz_extract_frames(max_frames=5000)`** caps how many frames a single
  extract writes, so a long clip cannot fill the disk in one call. The reply says
  so when the cap is reached; raise it, or trim with `start`/`end`/`fps`.
- **Guardrails on drawing sizes.** A frame is capped at 8192 px per side and 40
  million pixels, a `blur`/`glow` radius at 200, and a tween at 2000 frames, so an
  absurd request fails with a clear message instead of exhausting memory or disk.
- `docs/tools.md` and the README now state what the CI unit suite proves (the
  scene-file edits, asserted against synthetic `.tnz` files) and what only the e2e
  suite proves (the integration), and the e2e workflow uploads its renders as
  artifacts.

### Changed
- **`opentoonz_render_frame` downscales the returned preview to 768px wide by
  default**, so looking at a 1080p scene no longer costs a full-size image on
  every call. Pass `max_width` to change it, or `max_width=0` for full size. Only
  the inline preview is affected; on-disk renders are untouched.
- The e2e workflow now **skips with a warning** when it cannot fetch a runtime,
  rather than failing the job, so a weekly red always means a real regression.

### Fixed
- **Drawing level names are validated.** `opentoonz_draw_frame`,
  `opentoonz_draw_frames` and `opentoonz_tween_frames` wrote
  `<workspace>/drawings/<level_name>...` without validating `level_name`, so a
  name like `../../esc` wrote outside the workspace. They now use the same
  `validate_level_name` as import and extract.
- **Render frames are matched by exact stem, not by prefix.** Frames were cleared
  and collected with the glob `<stem>*.png`, so rendering `a` deleted — and
  counted — the frames of `a_b`, and a batch naming scenes `intro`/`intro_v2` had
  them clobber each other. The match is now anchored to the stem.
- **MP4 output keeps both dimensions even without `scale`.** The even-dimension
  filter was applied only when `scale` was given, so an odd-sized scene failed at
  the encoder; it is now applied unconditionally.

## [0.7.0] - 2026-10-16

### Added
- **MCP resources** — `opentoonz://workspaces`, `opentoonz://workspace/{name}`
  and `opentoonz://workspace/{name}/scene/{scene}` expose the workspace data as
  JSON, so a client can poll state without calling a tool. They reuse the tool
  models, so the payloads match. The first two read only the filesystem.
- **Progress reporting during renders.** `opentoonz_render`, `opentoonz_render_video`,
  `opentoonz_render_gif` and `opentoonz_render_batch` now report progress to the
  client (start/finish, or once per scene for a batch) and run the blocking render
  off the event loop, so a long render no longer freezes the server's responsiveness.
- **`opentoonz_render_batch`** — renders several scenes in one call (frames, video
  or gif), naming each output after its scene and reporting every scene's result.
  One scene failing does not stop the rest, so a long batch is never lost to a
  single bad scene.
- **`opentoonz_clean(what="orphans")`** — removes drawings that no scene in the
  workspace references, which is what accumulates when a level is re-imported
  under a new name or a sequence is drawn but never used. Conservative by design:
  a name is kept if any scene mentions it, and with no scenes at all it refuses
  rather than treating every drawing as an orphan.
- **`opentoonz_doctor(smoke=true)`** — runs a trivial script through OpenToonz and
  reports whether it actually executed, so the diagnostic proves the runtime works
  end to end rather than only that the binaries exist.
- **`opentoonz_delete_workspace(workspace, confirm=)`** — removes a whole
  workspace, scenes and all. Irreversible, so it refuses unless `confirm=true`;
  `opentoonz_clean` remains the keep-the-workspace alternative.

## [0.6.0] - 2026-10-16

### Added
- **`opentoonz_extract_frames`** — pulls a video's frames into `drawings/` as a
  level with ffmpeg, so outside footage can join a scene. Optional resample
  (`fps`), trim (`start`/`end`, seconds) and downscale (`max_width`).
- **Baked effect ops** — `blur`, `glow`, `adjust`, `vignette`, `outline` and
  `grain`. They post-process everything drawn before them, in order. OpenToonz FX
  nodes are GUI-only, so effects are baked into the frame instead.
- **`opentoonz_tween_frames`** — renders in-between frames moving one drawing from
  a start pose to an end pose (position, scale, rotation, opacity), with optional
  smoothstep easing, and saves them ready to import as a level. OpenToonz's
  auto-inbetweening is GUI-only, so the in-betweens are produced in the image
  pipeline.
- **Six more drawing ops** — `round_rect`, `star`, `arc`, `bezier`, `curve` and
  `gradient`. Frames can now carry rounded panels, stars, wedges, smooth splines
  (`curve` passes through every point; `bezier` is a cubic) and linear gradients
  without a separate image editor.

## [0.5.0] - 2026-10-16

### Added
- **`opentoonz_clean(workspace, what=, confirm=)`** — deletes a workspace's
  drawings, renders, or scripts to reclaim disk space, reporting how much was
  freed. Irreversible, so it refuses unless `confirm=true`; the workspace itself
  is always kept.
- **Structured tool results.** `opentoonz_list_workspaces`, `opentoonz_scene_info`
  and the `opentoonz_render*` tools now return a machine-readable payload beside
  the human summary (`models.py`: `SceneReport`, `WorkspaceReport`,
  `RenderReport`), so an agent reads fields instead of parsing prose. The summary
  is unchanged and still the first content block.
- **Inline frame previews.** `opentoonz_render_frame` returns the rendered PNG as
  an image block as well as writing it to disk, so looking at a frame costs no
  extra round-trip.
- **Frame ranges on `opentoonz_render`** — `start`/`end` render an inclusive
  range (e.g. frames 1–3) instead of the whole scene, so checking a section does
  not cost a full render.
- **`opentoonz_render_video(crf=, scale=)`** — control H.264 quality and output
  size directly.
- **`opentoonz_import_images_as_level` accepts a directory** in `image_paths`;
  the raster images inside it import in name order.

### Changed
- **Scene and output names are validated, not just sanitised.** `scene_path()`
  no longer accepts an absolute path or one that escapes the workspace via
  `..`, and render output stems must be a single plain name (they form file names
  *and* the ffmpeg glob used to clear frames). `Frame.save()` no longer creates
  missing parent directories.
- **Drawing ops validate their keys.** A typo'd key is reported by name with the
  allowed keys, instead of raising a raw `TypeError` from the op dispatch.

### Added (docs)
- `docs/api-surface.md` — the verified callable / absent scripting-API surface,
  with the evidence for the descoped cell-deletion (B6) and vector-level (B7)
  features.

## [0.4.0] - 2026-10-16

Camera moves — with easing — plus output polish, distribution, and hardening.

### Added
- **`opentoonz_camera_move`** — animate the camera: pan, zoom, and rotate over
  the shot, `[{"frame": 1, "zoom": 1}, {"frame": 48, "zoom": 1.4}]`. The
  scripting API has no camera at all (the camera is a *stage object* inside the
  `.tnz`), so keyframes are written into the camera's own channels. OpenToonz
  reads, renders *and re-saves* them, so the move behaves like a real camera move
  and stays editable in the GUI's Function Editor instead of being baked into the
  artwork. Position is in scene pixels, `zoom` is a magnification, and
  `rotation` is in degrees; channels left at neutral are cleared, so a later call
  fully redefines the camera rather than merging with an earlier one.
- **Camera easing.** `"ease": true` on a keyframe makes the camera glide out of
  that pose and into the next instead of moving at a constant rate. Easing is
  per *segment* — it belongs on the keyframe the segment starts from — so you can
  soften one part of a move and keep the rest linear, which a single global
  switch could not express. It is symmetric (half the segment at each end) and
  applies to pan, zoom and rotation at once. The flag on the last keyframe has no
  segment to ease, so it is ignored: stamping `ease` on every keyframe eases the
  whole move. It is written as a real `EaseInOut` (`<E>`) curve, so the handles
  stay editable in the GUI's Function Editor.
- **`opentoonz_render_gif`** — render a scene to a looping GIF with ffmpeg's
  `palettegen`/`paletteuse` (per-clip palette, so gradients do not band). `fps`,
  `max_width`, and `colors` are configurable.
- **`opentoonz_render_frame(max_width=...)`** — downscale the returned preview in
  place, so looking at a 1080p scene costs far fewer image tokens. The reply
  reports the size (`(960x540, downscaled from 1920x1080)`). Only the preview is
  affected; `opentoonz_render` and `opentoonz_render_video` frames are untouched.
- **`opentoonz_render_video(audio=...)`** — mux an external soundtrack
  (`-c:a aac -shortest`). OpenToonz's own audio columns are unreachable from the
  scripting API, so audio always comes from a file.
- **`opentoonz-mcp fetch-runtime --appimage …`** — extract an OpenToonz AppImage
  into a reusable runtime, in one command, without a clone. The AppImage launcher
  mangles CLI arguments, so the tools need the *extracted* tree; the command
  reports the exact `OPENTOONZ_RUNTIME` value to set, and refuses a partial
  extraction (a runtime missing `tcomposer` would otherwise fail much later).
  `scripts/bootstrap_runtime.py` remains as a thin wrapper for use from a clone.
- **Per-workspace locking.** Every scene and render operation now runs under a
  re-entrant `flock` on `<workspace>/.lock`, so two agents (or processes) sharing
  a workspace can no longer silently drop each other's changes. A busy workspace
  waits, then fails with a clear message rather than hanging.
- `opentoonz_list_workspaces` reports each workspace's size on disk (plus GIFs).
- `scripts/probe_camera.py` — a re-runnable probe that re-establishes how the
  camera is stored and what each channel does (including that easing renders and
  survives a save), for future OpenToonz upgrades.
- `examples/camera_move.py` — a static scene pushed in on by an eased camera,
  rendered to `docs/camera.gif`.
- Faked-subprocess unit tests for `bridge.py`, `render.py`, and the runtime
  bootstrap (160 unit + 20 e2e).

### Changed
- **The saved script succeeds or fails on its own terms.** A missing OpenToonz or
  `tcomposer` binary now raises a message naming `OPENTOONZ_RUNTIME` instead of
  surfacing a bare `FileNotFoundError`, and a missing audio file is reported
  before rendering rather than after.
- **Workspace locking degrades loudly where `fcntl` is unavailable** (Windows).
  There is nothing to serialise on, so the lock is still a no-op — but it now
  warns once, instead of losing concurrent edits in silence.
- CI checks formatting (`ruff format --check`) and builds a wheel, so packaging
  regressions fail the build rather than the release.
- `uv.lock` is ignored: CI installs from the `pyproject.toml` floors, so the
  lockfile pins nothing that ships.
- `docs/runtime-notes.md` records the camera, easing, and audio findings
  (facts 27–31).

### Fixed
- **Serialised camera calls no longer accumulate channels.** Writing only the
  channels of the latest call left an earlier move switched on — a pan followed by
  a zoom kept both — which was found by rendering and measuring the result.

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
