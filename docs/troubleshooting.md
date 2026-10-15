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

## The rendered frame is black / the art is a small box

`newLevel`/`setFrame` are in-memory (black), or the art is not 1920×1080. The
default camera is 1920×1080 and composites levels 1:1 and centred, so generate art
at that size for full-frame output.

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
