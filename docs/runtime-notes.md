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
12. **Default camera is 1920×1080.** Art at other sizes is composited 1:1 and
    centred, so non-1080p art will not fill the frame.
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

16. Verified globals/classes: `Scene`, `Level`, `Image`, `Renderer`, `FilePath`,
    `ImageBuilder`, vectorizers, and a global `print()`.
17. `Scene`: `new Scene(path?)`, `load`/`save`, `newLevel(type, name)`,
    `loadLevel(name, "path/<level>..png")` (double-dot = frame-number pattern),
    `setCell(row, col, levelOrName, fid)`, `getCell(row, col)`, `getLevels()`,
    `frameCount`, `columnCount`.
18. `Level`: `.name` / `.type` / `.path` / `.frameCount` are **properties**, not
    methods. Also `getFrameIds()`, `getFrame(fid)`, `setFrame(fid, image)`.
19. `newLevel` + `setFrame` are **in-memory**; a saved `.tnz` referencing them will
    render black because the level files were never written. Import from real files
    with `loadLevel` instead.
20. **Not bound (GUI-only):** FX graphs, palette editing, camera splines,
    auto-inbetweening, audio tracks.

## Workarounds for the gaps

- **Drawing** → PIL raster PNGs (`draw.py`) or SVG import.
- **FX** → pre-bake in the image pipeline (PIL/ffmpeg).
- **Camera moves** → bake into the level frames.
- **Audio** → mux with ffmpeg at the end.
