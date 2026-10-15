# Troubleshooting

Start with **`opentoonz_doctor`** — it prints every resolved path and the version.

## "Could not locate the OpenToonz runtime"

The runtime binaries were not found. Do one of:

- Set `OPENTOONZ_RUNTIME` to an **extracted** AppImage directory (containing
  `usr/bin/OpenToonz`), or
- put `OpenToonz` and `tcomposer` on `PATH`, or
- set `OPENTOONZ_BIN` and `OPENTOONZ_TCOMPOSER_BIN`.

See [installation.md](installation.md).

## A script hangs / times out

Almost always the AppImage launcher, which puts OpenToonz into **GUI mode** (no
script output, process never exits). Make sure `OPENTOONZ_RUNTIME` points at the
extracted `squashfs-root` and that the binary used is `usr/bin/OpenToonz`, not the
`.AppImage`.

## Render produces no frames

Check, in order, the runtime-notes facts:

1. **Relative scene path** → `tcomposer` spins at 100% CPU. Scenes are always
   passed absolute; a custom script that doesn't may hang.
2. **Output prefix missing `.png`.**
3. **RGB (not RGBA) level images** → per-frame "Toonz Exception". Re-import them
   through `opentoonz_import_images_as_level` (it converts automatically).
4. **In-memory levels** (`newLevel` + `setFrame` without writing files) → black
   frames. Use `loadLevel` on real files.

The tcomposer farm log (`<isolated HOME>/.config/OpenToonz/stuff/toonzfarm/tcomposer.log`)
has the details; `opentoonz_render` also returns the captured log on failure.

## The rendered frame is black

`newLevel`/`setFrame` are in-memory: a saved `.tnz` that references them renders
black because the level files were never written. Import real files with
`opentoonz_import_images_as_level` instead.

## The art is a small box in the middle of the frame

The art is smaller than the camera. Levels composite **1:1 in output pixels**, so
draw at the scene's resolution — create the scene with
`opentoonz_scene_new(width=..., height=...)`, or check the current size with
`opentoonz_doctor`/the scene file.

If you resized the scene and the art *shrank*, you are on a pre-0.2.0 build: the
camera's **physical** size has to scale with the resolution (640×360 art in a
640×360 frame, with `cameraSize` left at the 16×9 default, rendered as a 213×120
box). `opentoonz_set_scene_settings` in 0.2.0+ rewrites `cameraSize` too.

## An SVG / vector level renders nothing

Expected, not a bug: vector levels load (`type=Vector`) but rasterise to nothing
headlessly. Convert the SVG to PNG first — `opentoonz_import_images_as_level`
rejects `.svg` input with that explanation. See runtime-notes fact 23.

## `level.setFrame()` seems to do nothing

Correct — edits made through `setFrame` on a loaded level never reach the
renderer, even after `scene.save()`. Only the files on disk matter, so repaint
the level's PNGs and re-import them with `opentoonz_import_images_as_level`
(re-importing the same level name is supported).

## A re-import shrank a level but the scene still has extra cells

OpenToonz has no way to delete a cell. Re-importing a *shorter* sequence removes
the orphaned drawing files and overwrites the cells it places, but any cells
beyond the new length stay in the xsheet. Use a fresh level name or a fresh scene
when a shot gets shorter.

## "ffmpeg not found"

Install ffmpeg, or set `OPENTOONZ_FFMPEG` to its full path. Only
`opentoonz_render_video` needs it.

## Multi-level import loses earlier levels

That was a bug in v0.1.0-alpha; `opentoonz_import_images_as_level` is now
additive (it loads an existing scene first). Upgrade, or use `opentoonz_set_cells`
with an already-populated scene.

## OpenToonz wrote to my real `~/.config/OpenToonz`

It should not — subprocesses get an isolated `HOME` under the data home. If you see
this, check that `OPENTOONZ_MCP_HOME` is writable and that no wrapper script is
resetting `HOME`.

## Stale frames from a previous render

`opentoonz_render` clears frames with the same `out_name` prefix before rendering.
If you render with a custom tool/prefix, clean `render/` yourself.

## Reporting a bug

Please include the output of `opentoonz_doctor`, the OpenToonz version, and the
failing tool's returned text.
