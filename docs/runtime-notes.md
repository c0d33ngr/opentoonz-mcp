# Runtime notes (hard-won OpenToonz facts)

These behaviours were established empirically against the **OpenToonz 1.8 Linux
AppImage** build. They are the reason the code is shaped the way it is; treat them
as the debugging map when something misbehaves.

## The CLI hook

1. **`OpenToonz <file>.toonzscript` runs JS headlessly.** It evaluates the script,
   prints to stdout, and exits — no window. This is the automation hook.
2. **Run the extracted binary, not the AppImage launcher.** The `AppRun` wrapper
   mangles CLI arguments and sends OpenToonz into GUI mode (a window opens and it
   never exits). Extract once (`--appimage-extract`) and run `usr/bin/OpenToonz`.
3. **`-TOONZROOT <dir>` makes it self-contained.** Point it at a writable `stuff`
   tree (copied once from the bundled `usr/share/opentoonz/stuff` template).
4. **Isolate `HOME`.** With `HOME` set to a scratch dir, OpenToonz still creates
   `$HOME/.config/OpenToonz`, but it stays contained and reproducible instead of
   touching the user's real config. Scripting and rendering both work this way.
5. **Success is not the exit code.** OpenToonz exits `1` on success because of
   icon-parsing warnings. Use a printed sentinel (`__OTMCP_OK__`) to detect
   success — never `returncode == 0`.
6. **Absolute paths everywhere.** `loadSceneProject` and friends reject or
   mis-handle relative paths.

## Rendering

7. **Never use `new Renderer()` in CLI scripts.** `renderFrame` / `renderScene`
   deadlock: the renderer waits on a Qt event loop that script mode never runs.
   Use `tcomposer`.
8. **`tcomposer <scene.tnz> -o out/prefix_.png`** renders frames to
   `out/prefix_0001.png`, `_0002.png`, ….
9. **`tcomposer` needs an ABSOLUTE scene path.** A relative path spins at 100% CPU
   with no error and no output.
10. **The output prefix must end in an image extension** (`.png`). Without it,
    `tcomposer` throws a "Toonz Exception" per frame.
11. **Level images must be RGBA PNG.** RGB-only images import fine but throw a
    "Toonz Exception" per frame at render time. The import tool converts them.
12. **The default camera is 1920×1080 over a 16×9 inch field — exactly 120 dpi.**
    A level image with no resolution metadata is composited at that 120 dpi, so
    art maps **1:1 to output pixels** when the camera's physical size matches the
    resolution (`cameraSize == cameraRes / 120`). Change `cameraRes` *alone* and
    the art scales with it: 640×360 art in a 640×360 frame, with `cameraSize`
    left at the 16×9 default, rendered as a **213×120** box in the middle.
    `set_scene_settings` therefore rewrites `cameraSize` as well.
13. **Runaway `tcomposer` ignores SIGTERM.** It must be killed with `SIGKILL`.
    (Python's `subprocess` timeout uses SIGKILL, so the runner is safe.)
14. **`tcomposer` accepts `-TOONZROOT`, `-TOONZCONFIG`, `-TOONZPROJECTS`,
    `-TOONZLIBRARY`, `-TOONZPROFILES`, `-TOONZSTUDIOPALETTE`, `-TOONZFXPRESETS`.**
    This is what allows fully isolated rendering.
15. **Farm log:** `$HOME/.config/OpenToonz/stuff/toonzfarm/tcomposer.log` (the
    isolated one, unless you overrode it) is useful for diagnosing render failures.

## Scripting API surface

Derived from the OpenToonz script bindings
([`toonz/sources/toonzlib`](https://github.com/opentoonz/opentoonz/tree/master/toonz/sources/toonzlib))
and the official [ToonzScript reference](https://opentoonz.readthedocs.io/en/latest/toonzscript.html).

16. **Verified global classes:** `Scene`, `Level`, `Image`, `Renderer`,
    `FilePath`, `ImageBuilder`, `OutlineVectorizer`, `CenterlineVectorizer`,
    `Rasterizer`, `ToonzRasterConverter`, `Transform`, and a global `print()`.
    There is **no** `Camera`, `Cell`, `Column`, `Xsheet`, `Project`, `Palette`,
    `Style`, or `Sound` binding.
17. `Scene`: `new Scene(path?)`, `load`/`save`,
    `loadLevel(name, "path/<level>..png")` (double-dot = frame-number pattern),
    `setCell(row, col, levelOrName, fid)`, `getCell(row, col)`, `getLevels()`,
    `frameCount`, `columnCount`. `setCell` accepts a level **name** as well as a
    level object, and raises `Level 'x' is not included in the scene` for an
    unknown one.
18. **`Scene` has no setters and no deletions.** `setCameraSize`, `getCameraSize`,
    `setCameraRect`, `setFrameRate`, `setFps`, `setFrameCount`, `setFieldSize`,
    `setOutputSize`, `removeLevel`, `deleteLevel`, `clearCell`, and `removeCell`
    are all **absent**. Resolution and fps live in the `.tnz` XML instead (see 25).
19. `Level`: `.name` / `.type` / `.path` / `.frameCount` are **properties**, not
    methods. Also `getFrame(fid)`, `setFrame(fid, image)`, `load`, `save`. There
    is no `saveAs`, `getPath`, `getFrameIds`, or `isReadOnly`.
20. **Re-adding a level name already in the scene is an error:**
    `Can't add the level: name(x) is already used`. Since nothing can be deleted,
    `import_level` reuses the existing level and overwrites its drawings.
21. **`level.setFrame()` on a loaded level never reaches the renderer.** Setting
    frame 2 to a red image and saving the scene left the render showing the
    original green. Only the files on disk matter, so paint levels *outside* the
    script.
22. `newLevel` + `setFrame` are **in-memory**; a saved `.tnz` referencing them
    renders black because the level files were never written. Import from real
    files with `loadLevel` instead.
23. **SVG imports as a `Vector` level but renders blank.** `loadLevel(name,
    "shape.svg")` succeeds and reports `type=Vector`, `frameCount=1` — but every
    variant tried (filled `<rect>`, filled `<path>`, stroked `<path>`) produced
    **0 opaque pixels**. Style/palette data is apparently not persisted anywhere
    the renderer reads. Raster PNG levels are the supported path.
24. **Success is still a marker** — the same rule as the CLI in general: a script
    that runs fine may exit `1`.
25. **Scene settings are plain XML, and patching them survives a save.**
    `.tnz` is ASCII XML: `<tnz framecount="N">`, `<cameraSize>`, `<cameraRes>`,
    `<fps>`, `<outputs>`. `new Scene(path)` → `save(path)` preserves edits made
    to those elements, so `set_scene_settings` can patch at any point rather than
    needing to run last.
26. **Not bound (GUI-only):** FX graphs, palette editing, camera splines,
    auto-inbetweening, audio tracks.

`scripts/probe_api.py` re-runs this whole survey against an installed runtime, so
a version bump can be checked rather than guessed at.

## Workarounds for the gaps

- **Drawing** → PIL raster PNGs (`draw.py`), or generate art elsewhere and import
  it. SVG/vector does **not** work headlessly (fact 23).
- **Scene size / fps** → patch the `.tnz` XML (`set_scene_settings`), since the
  API has no setter (fact 18).
- **Replacing a level** → impossible (no `removeLevel`); reuse the name and
  overwrite the drawings, or start a fresh scene (fact 20).
- **FX** → pre-bake in the image pipeline (PIL/ffmpeg).
- **Camera moves** → bake into the level frames.
- **Audio** → mux with ffmpeg at the end.
