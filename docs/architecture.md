# Architecture

## Module map

```
src/opentoonz_mcp/
├── config.py      Settings: all OPENTOONZ_* env vars, portable defaults
├── runtime.py     Locate OpenToonz + tcomposer + the bundled stuff template
├── context.py     Context (settings + runtime), lazily prepares stuff/HOME
├── bridge.py      Run .toonzscript files headlessly; capture output
├── workspace.py   Workspace lifecycle (drawings/render/scripts)
├── draw.py        PIL frame authoring (RGBA PNG frames + op schema)
├── scenes.py      Scene create/resize, camera moves, inspect, level import/reuse, cell & exposure timing
├── render.py      tcomposer rendering + ffmpeg muxing (MP4, GIF)
├── models.py      Pydantic results for the data-returning tools (structured output)
├── bootstrap.py   `fetch-runtime`: extract an OpenToonz AppImage into a runtime
└── server.py      FastMCP tool definitions (thin wrappers over the above)
```

`server.py` contains no logic beyond formatting and error handling — every
behaviour is testable directly through the library modules (see `tests/`).

The data-returning tools (`list_workspaces`, `scene_info`, `render*`) return a
`ToolResult` built by `server._structured`: a human-readable summary as the first
text block, plus a `models.py` payload as structured content. `render_frame`
also attaches the PNG as an image block, so looking at a frame costs no extra
round-trip.

The same models back three read-only MCP **resources** (`opentoonz://workspaces`,
`opentoonz://workspace/{name}`, `opentoonz://workspace/{name}/scene/{scene}`), so a
client can poll workspace state as JSON without calling a tool. The long-running
render tools also report progress and run their blocking work off the event loop.

## Data flow

```
opentoonz_draw_* / external tool   →  drawings/<level>.<NNNN>.png  (RGBA)
opentoonz_import_images_as_level   →  scripts/*.toonzscript → OpenToonz CLI → scene .tnz
opentoonz_set_cells / _exposure    →  scripts/*.toonzscript → OpenToonz CLI → scene .tnz
opentoonz_scene_new / _set_scene_settings  →  .tnz XML patched in place (cameraRes/cameraSize/fps)
opentoonz_camera_move              →  .tnz XML patched in place (camera stage-object channels)
opentoonz_render[_frame|_video|_gif]  →  tcomposer → render/*.png  (→ ffmpeg → *.mp4 / *.gif)
```

## Key design decisions

### 1. Headless CLI, not a GUI plugin
OpenToonz can execute a `.toonzscript` from the command line
(`OpenToonz <file>.toonzscript`). That is the automation hook — equivalent to
Blender's `--background --python` — and it needs no plugin or C++ build.

### 2. Process-per-call, batch by design
Each tool call spawns OpenToonz once (~a few seconds of startup). Tools are
therefore **batch-oriented**: one call does many operations. This is a deliberate
trade for zero-setup. A future daemon (C++ plugin + HTTP) is the only way to get
a persistent session.

### 3. Run the extracted binary directly
The Linux AppImage's `AppRun` launcher mangles arguments and drops OpenToonz into
GUI mode (it opens a window and never exits). `runtime.py` therefore runs
`usr/bin/OpenToonz` inside the extracted tree.

### 4. A shared `TOONZROOT`, an isolated `HOME`
- The OpenToonz `stuff/` tree is copied **once** into the data home and referenced
  with `-TOONZROOT`, instead of duplicating ~30 MB per workspace.
- OpenToonz subprocesses get `HOME=<data_home>/home`, so they never write into the
  user's real `~/.config/OpenToonz`.

Both were validated empirically: scripting and rendering both succeed with no
global config present.

### 5. Success is a marker, not an exit code
OpenToonz exits non-zero even on success (harmless icon-parsing warnings), so
generated scripts print `__OTMCP_OK__` and `bridge.py` keys off that.

### 6. Rendering goes through `tcomposer`
`Renderer.renderFrame` / `renderScene` deadlock in CLI mode (they need the Qt
event loop that script mode never starts). `tcomposer` — the official headless
renderer — is used instead. It needs an **absolute** scene path, a `.png` output
prefix, and `-TOONZROOT`.

### 7. Additive level import
`opentoonz_import_images_as_level` loads an existing scene before adding a level,
so several calls compose a multi-level scene. (An earlier version always started
from `new Scene()` and silently discarded previous levels.)

### 8. Stale-frame clearing
Renders clear frames matching their output prefix first, so a shorter re-render
cannot leave orphans that inflate counts or leak into the MP4. Level import does
the same for drawings: a shorter sequence would otherwise leave higher-numbered
frames that `loadLevel`'s `..` pattern loads back in. Sources being imported are
spared, since drawing straight into `drawings/` is the normal workflow.

### 9. Scene settings are patched into the `.tnz`, not set by API
`Scene` exposes no `setCameraSize`/`setFrameCount` — resolution and fps are only
reachable through the scene file, which is plain XML. `set_scene_settings` edits
it in place. Crucially it also rewrites `cameraSize`: levels composite at 120 dpi,
so the camera's *physical* size must scale with the resolution, or resizing a
scene shrinks the art instead of re-framing it. A JS scene round-trip preserves
the edit, so ordering relative to other tools does not matter.

### 10. Levels are reused, never replaced
There is no `removeLevel`/`clearCell`, and `loadLevel` errors on a name the scene
already knows. So `import_level` looks the name up first and, if it exists, reuses
that level and overwrites its drawings. This is what makes the
draw → import → render → redraw loop work, and it pushes the tool surface toward
"additive only" by design rather than by preference.

### 11. Camera moves are stage-object channels, not a bake
There is no camera in the JS API — not a setter, not even a `Camera` object. In
the scene XML the camera is a *stage object*: `<pegbar id="Camera1">` in the
xsheet's `<pegbars>`, with the same kind of channels as any column's pegbar
(`x`, `y`, `sc`, `rot`, ...). `camera_move` writes keyframes into those channels:
linear by default, or an eased (`<E>`) segment when a keyframe asks for one.
OpenToonz renders them and preserves them on save, so the result is a genuine
camera move that stays editable in the Function Editor — a *bake* into the level
frames was the fallback plan and was not needed.
`scripts/probe_camera.py` re-establishes the facts it depends on.

### 12. One workspace, one writer
A scene is read, edited and written as a whole, and the edit spans an OpenToonz
subprocess — so two callers on one workspace would interleave and lose changes.
Every scene and render operation therefore runs under a re-entrant `flock` on
`<workspace>/.lock` (`workspace.locked`, applied at the library layer so direct
callers get it too). Re-entrancy matters because operations legitimately nest
(`set_exposure` → `set_cells`, `render_video` → `render_frames`). The lock is
advisory, released on process death, and a busy workspace times out with a clear
message instead of hanging. Where `fcntl` is unavailable (Windows) there is
nothing to lock with, so the lock degrades to a no-op — but it warns once, rather
than letting concurrent edits be lost in silence.

## Extension points

- **New platform:** `runtime.py` is the only place that knows where binaries live.
- **New tools:** add a function in the relevant module, then a thin wrapper in
  `server.py` (and a name to `tests/test_server.py`).
- **Persistent session (v2):** a daemon speaking to an in-process OpenToonz via
  the plugin SDK would replace `bridge.py` without changing the tool surface.
