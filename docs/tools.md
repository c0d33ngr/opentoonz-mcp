# Tool reference

Every tool returns a short human-readable string. Failures are returned as
`ERROR [ExceptionType]: message` rather than raising, so an agent can read and
react to them.

## Diagnostics

### `opentoonz_health() -> str`
Quick check that the runtime binaries and ffmpeg exist. Returns `READY ...` or
`DEGRADED — missing: ...`.

### `opentoonz_doctor() -> str`
Full diagnostics: resolved paths, version, prepared state, timeouts.

## Workspaces

### `opentoonz_create_workspace(name: str) -> str`
Creates `<workspaces>/<name>/` with `drawings/`, `render/`, `scripts/`.
Idempotent — calling it again reuses the workspace. Names may be nested
(`series/ep1`) but can never escape the workspaces root.

### `opentoonz_list_workspaces() -> str`
Lists each workspace with its scenes and rendered videos.

## Scenes

### `opentoonz_scene_new(workspace: str, scene: str = "main", width=None, height=None, fps=None) -> str`
Creates (or overwrites) an empty `.tnz` scene. Pass `width`/`height` to set the
camera resolution (default 1920×1080) — see `opentoonz_set_scene_settings`.

### `opentoonz_set_scene_settings(workspace, scene, width=None, height=None, fps=None) -> str`
Changes a scene's camera resolution and/or frame rate.

- **Why it patches XML:** OpenToonz's scripting API has no camera setter
  (`scene.setCameraSize` does not exist), so the scene file — which is plain
  XML — is edited in place. Later edits to the scene keep the setting.
- `width`/`height` may be given independently; the omitted one keeps its value.
- The camera's **physical size** is rescaled to match, so art drawn at the
  scene's size still fills the frame (leaving it at the 16×9 default while
  shrinking the resolution would render 640×360 art as a 213×120 box).
- Levels composite **1:1**, so draw art at the scene's resolution. Drawing at
  1920×1080 and then rendering at 480×270 shows the *centre* of the art, not a
  scaled-down version of it.

### `opentoonz_import_images_as_level(workspace, level_name, image_paths, scene="main", start_row=0, column=0) -> str`
Imports an **ordered** list of image paths as a raster level and places one frame
per row on the xsheet, starting at `start_row` in `column`.

- **Additive:** if the scene already exists it is loaded first, so you can call
  this repeatedly to build a multi-level / multi-column scene.
- **Re-runnable:** re-importing the same `level_name` reuses the existing level
  and overwrites its drawings. OpenToonz rejects a duplicate level name and has
  no `removeLevel`, so reuse is the only way to iterate on artwork. Shrinking a
  level (5 frames → 3) removes the orphaned `drawings/<level>.0004.png`/
  `.0005.png` files that would otherwise be loaded back in.
- Images are converted to **RGBA PNG** (OpenToonz rejects RGB-only images at
  render time) and stored as `drawings/<level_name>.%04d.png`. Art already
  sitting in `drawings/` is left in place.
- SVG input is **rejected** — vector levels load but rasterise to nothing (see
  [troubleshooting.md](troubleshooting.md)).
- Level names must be 1–64 characters of `A-Z a-z 0-9 _ -` (they become file
  prefixes).

### `opentoonz_scene_info(workspace, scene, max_rows=1000) -> str`
Reports `frames=`, `columns=`, then one line per level and per cell. The cell map
is scanned row by row, so it stops at `max_rows` (default 1000) and says
`note: cell list truncated` when a scene is taller.

### `opentoonz_set_cells(workspace, scene, placements) -> str`
`placements` is a list of `{"row": int, "col": int, "level": str, "fid": int|str}`.

### `opentoonz_exposure(workspace, scene, level, exposures, start_row=0, column=0) -> str`
Times a level by holding each drawing for N frames — the animation-native way to
say "on 2s":

| `exposures` | Meaning |
|---|---|
| `[3]` | hold *every* drawing for 3 frames |
| `[2, 4, 1]` | drawing 1 → 2 frames, drawing 2 → 4, drawing 3 → 1 |

Every row of a hold gets its own cell: an empty xsheet row renders nothing, so
"holding" means repeating the drawing's `fid` across the rows. Rows are
contiguous from `start_row`, and the scene's frame count follows what is placed.
The level must already be in the scene.

## Drawing

Draws RGBA frames with a small, intentional PIL subset — for agents that have no
external paint tool. Frames land in `drawings/` ready for
`opentoonz_import_images_as_level`.

### `opentoonz_draw_frame(workspace, level_name, ops, frame=1, width=1920, height=1080, background="#181a2e") -> str`
Draws one frame to `drawings/<level_name>.<frame:04d>.png`.

### `opentoonz_draw_frames(workspace, level_name, frames, width=1920, height=1080, background="#181a2e") -> str`
`frames` is a list where each item is that frame's list of ops (frame 1 first).
Returns the saved paths.

### Drawing ops

An op is a dict with an `op` key and keyword arguments:

| Op | Keys |
|---|---|
| `rect` | `xy=[x0,y0,x1,y1]`, `fill`, `outline`, `width` |
| `ellipse` | `box=[x0,y0,x1,y1]`, `fill`, `outline`, `width` |
| `line` | `xy=[x0,y0,x1,y1]`, `fill`, `width` |
| `polygon` | `points=[[x,y],...]`, `fill`, `outline`, `width` |
| `polyline` | `points=[[x,y],...]`, `fill`, `width` |
| `text` | `xy=[x,y]`, `text`, `fill`, `size`, `anchor` (PIL anchor, e.g. `"la"`) |
| `image` | `path`, `xy=[x,y]`, `size=[w,h]` (optional resize), `opacity` (0..1) |

Colours accept `#rgb`, `#rrggbb`, `#rrggbbaa`, or `[r, g, b(, a)]`.

`background` may be a colour or `null` for transparency.

The `image` op composites an existing PNG onto the frame — how art made elsewhere
joins a drawn frame:

```json
[
  {"op": "rect",  "xy": [0, 0, 1920, 1080], "fill": "#101828"},
  {"op": "image", "path": "/abs/character.png", "xy": [700, 300], "size": [520, 520]},
  {"op": "text",  "xy": [60, 90], "text": "Scene 1", "fill": "#e0b184", "size": 72}
]
```

Example:

```json
[
  {"op": "rect",    "xy": [0, 0, 1920, 1080], "fill": "#181a2e"},
  {"op": "ellipse", "box": [860, 400, 1060, 600], "fill": "#ff6b6b"},
  {"op": "text",    "xy": [60, 90], "text": "Frame 1", "fill": "#e0b184", "size": 72}
]
```

## Rendering

### `opentoonz_render_frame(workspace, scene, frame=1, out_name="look") -> str`
Renders a single frame to a PNG — the agent's "look" at its work.

### `opentoonz_render(workspace, scene, out_name="render") -> str`
Renders the scene to `render/<out_name>_NNNN.png` with `tcomposer`. Any stale
frames with the same name are removed first, so counts are always accurate.

### `opentoonz_render_video(workspace, scene, fps=24, out_name="video") -> str`
Renders then muxes the frames into `render/<out_name>.mp4` with ffmpeg.

## Escape hatch

### `opentoonz_run_script(workspace, code, timeout=90) -> str`
Runs arbitrary OpenToonz JavaScript headlessly and returns stdout. This is the
full-power tool — everything in the OpenToonz scripting API is reachable.

Upstream API reference:
[ToonzScript documentation](https://opentoonz.readthedocs.io/en/latest/toonzscript.html)
and the script bindings in
[`toonz/sources/toonzlib`](https://github.com/opentoonz/opentoonz/tree/master/toonz/sources/toonzlib).

Available in the script environment:

```js
var scene = new Scene();                      // or new Scene("/abs/path.tnz")
scene.loadLevel(name, "/abs/drawings/L..png") // ".." = frame-number pattern
scene.setCell(row, col, level, fid);
scene.getCell(row, col);
scene.getLevels();
scene.save("/abs/path.tnz");
var img = new Image("/abs/frame.png");
img.save("/abs/out.png");
level.frameCount; level.getFrameIds(); level.setFrame(fid, image);
print("...");   // goes to stdout
```

Notes:

- **Do not use `new Renderer()`** — `renderFrame`/`renderScene` deadlock in CLI
  mode. Render with `opentoonz_render` instead.
- Use **absolute paths**.
- Scripts print `__OTMCP_OK__` on success in the built-in tools; if you write
  your own via this tool, success is judged only by stdout, not the exit code.
