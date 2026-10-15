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
├── scenes.py      Scene create/inspect, additive level import, cell placement
├── render.py      tcomposer rendering + ffmpeg muxing
└── server.py      FastMCP tool definitions (thin wrappers over the above)
```

`server.py` contains no logic beyond formatting and error handling — every
behaviour is testable directly through the library modules (see `tests/`).

## Data flow

```
opentoonz_draw_* / external tool   →  drawings/<level>.<NNNN>.png  (RGBA)
opentoonz_import_images_as_level   →  scripts/*.toonzscript → OpenToonz CLI → scene .tnz
opentoonz_set_cells                →  scripts/*.toonzscript → OpenToonz CLI → scene .tnz
opentoonz_render[_frame|_video]    →  tcomposer → render/*.png  (→ ffmpeg → *.mp4)
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
cannot leave orphans that inflate counts or leak into the MP4.

## Extension points

- **New platform:** `runtime.py` is the only place that knows where binaries live.
- **New tools:** add a function in the relevant module, then a thin wrapper in
  `server.py` (and a name to `tests/test_server.py`).
- **Persistent session (v2):** a daemon speaking to an in-process OpenToonz via
  the plugin SDK would replace `bridge.py` without changing the tool surface.
