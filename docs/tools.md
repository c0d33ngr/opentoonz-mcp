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
Lists each workspace with its scenes, videos, GIFs, rendered frame count, and
total size on disk (the render folder is usually the bulk of it).

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

## Camera

### `opentoonz_camera_move(workspace, scene, keyframes) -> str`
Animates the scene's camera — pan, zoom, and rotate over time.

`keyframes` is a list of `{"frame": int, "x": px, "y": px, "zoom": factor,
"rotation": degrees, "ease": bool}`. Only `frame` is required; the rest default to
no movement (`x=0`, `y=0`, `zoom=1`, `rotation=0`, `ease=false`). Keyframes may be
given in any order.

- `frame` is a **1-based shot frame**, the same numbering as
  `opentoonz_render_frame`. Keyframes map to xsheet rows, so the first frame of
  the shot (`1`) is the row where you placed the first cell.
- `x`/`y` are the camera's position in **scene pixels**: `+x` pans the view right
  and `+y` pans it up, so the artwork moves the opposite way. One unit is
  `cameraRes.x / cameraSize.x` pixels — 120 px at the resolution
  `opentoonz_set_scene_settings` keeps.
- `zoom` is a **magnification**: `2` renders the artwork twice as large. Because
  this is a physical camera move, a pan's on-screen size is multiplied by the
  zoom.
- `rotation` is in **degrees, clockwise on screen**, about the frame centre.
- `ease` makes the camera **glide** out of that keyframe and into the next,
  instead of moving at a constant rate. It eases the segment that *starts* at the
  keyframe, symmetrically (half the segment at each end), across every channel at
  once. It is written as a real `EaseInOut` curve, so it stays editable in the
  Function Editor.
  - Easing is **per segment**: a run of eased keyframes settles at each pose, so
    ease only the segments you want softened. A single-segment move can be eased
    in one flag.
  - The flag on the **last** keyframe has no segment to ease, so it is ignored —
    stamping `ease` on every keyframe eases the whole move.
- **Replaces, not merges:** each call defines the whole camera, so channels left
  at neutral are cleared. Calling it again with only `zoom` drops an earlier pan
  rather than silently keeping both.

```json
[{"frame": 1, "zoom": 1.0, "ease": true}, {"frame": 48, "zoom": 1.4, "x": 60}]
```

**Why it patches XML:** the scripting API has no camera at all — the camera is a
*stage object* (`<pegbar id="Camera1">`) whose channels live in the `.tnz`. The
move is written there, so it renders like a real camera move and stays editable
in OpenToonz rather than being baked into the artwork.

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

### `opentoonz_render_frame(workspace, scene, frame=1, out_name="look", max_width=None) -> str`
Renders a single frame to a PNG — the agent's "look" at its work.

`max_width` downscales the returned PNG **in place** so looking at a large scene
costs fewer image tokens; the reply reports the size, e.g. `(960x540, downscaled
from 1920x1080)`. Only this preview is affected — `opentoonz_render` and
`opentoonz_render_video` frames are never downscaled.

### `opentoonz_render(workspace, scene, out_name="render") -> str`
Renders the scene to `render/<out_name>_NNNN.png` with `tcomposer`. Any stale
frames with the same name are removed first, so counts are always accurate.

### `opentoonz_render_video(workspace, scene, fps=24, out_name="video", audio=None) -> str`
Renders then muxes the frames into `render/<out_name>.mp4` with ffmpeg.

`audio` is an optional path to an external soundtrack (mp3, wav, ...). It is
encoded as AAC and cut to the video's length. OpenToonz's own audio columns
cannot be reached from the scripting API, so audio always comes from a file.

### `opentoonz_render_gif(workspace, scene, fps=12, out_name="reel", max_width=None, colors=256) -> str`
Renders then turns the frames into `render/<out_name>.gif` — a looping file, the
cheap way to share a finished move. `fps` sets playback speed (12–15 reads well
for hand-drawn work), `max_width` downscales, and `colors` caps the palette
(2–256). ffmpeg builds a per-clip palette, so gradients do not band. Use
`opentoonz_render_video` for anything with audio or that must stay full
resolution.

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
