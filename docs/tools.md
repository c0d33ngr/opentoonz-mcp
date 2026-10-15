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

### `opentoonz_scene_new(workspace: str, scene: str = "main") -> str`
Creates (or overwrites) an empty `.tnz` scene.

### `opentoonz_import_images_as_level(workspace, level_name, image_paths, scene="main", start_row=0, column=0) -> str`
Imports an **ordered** list of image paths as a raster level and places one frame
per row on the xsheet, starting at `start_row` in `column`.

- **Additive:** if the scene already exists it is loaded first, so you can call
  this repeatedly to build a multi-level / multi-column scene.
- Images are converted to **RGBA PNG** (OpenToonz rejects RGB-only images at
  render time) and stored as `drawings/<level_name>.%04d.png`.
- The default camera is **1920×1080** — draw at that size for full-frame output.

### `opentoonz_scene_info(workspace, scene) -> str`
Reports `frames=`, `columns=`, then one line per level and per cell.

### `opentoonz_set_cells(workspace, scene, placements) -> str`
`placements` is a list of `{"row": int, "col": int, "level": str, "fid": int|str}`.

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

Colours accept `#rgb`, `#rrggbb`, `#rrggbbaa`, or `[r, g, b(, a)]`.

`background` may be a colour or `null` for transparency.

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
