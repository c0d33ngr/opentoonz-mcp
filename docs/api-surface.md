# Scripting API surface (verified)

What is actually callable in the OpenToonz scripting API bundled with the
runtime, as opposed to what the documentation implies. This is the reference
that decided which features exist and which were **descoped**; the empirical
facts behind it live in **[runtime-notes.md](runtime-notes.md)** (facts 16–26).

Re-verify against a new runtime with:

```bash
OPENTOONZ_RUNTIME=/path/to/squashfs-root python scripts/probe_api.py
```

`scripts/probe_api.py` runs one `.toonzscript` per hypothesis through the bridge
and reports **callable** vs. **throws** vs. **absent**.

## Globals

| Callable | Absent |
| --- | --- |
| `Scene`, `Level`, `Image`, `Renderer`, `FilePath`, `ImageBuilder`, `OutlineVectorizer`, `CenterlineVectorizer`, `Rasterizer`, `ToonzRasterConverter`, `Transform`, `print()` | `Camera`, `Cell`, `Column`, `Xsheet`, `Project`, `Palette`, `Style`, `Sound` |

## `Scene`

| Callable | Absent |
| --- | --- |
| `new Scene(path?)`, `load`, `save`, `loadLevel(name, "…/<level>..png")`, `setCell(row, col, levelOrName, fid)`, `getCell(row, col)`, `getLevels()`, `frameCount`, `columnCount` | `setCameraSize`, `getCameraSize`, `setCameraRect`, `setFrameRate`, `setFps`, `setFrameCount`, `setFieldSize`, `setOutputSize`, `removeLevel`, `deleteLevel`, `clearCell`, `removeCell` |

Consequences: there are **no setters and no deletions**. Resolution and fps are
patched in the `.tnz` XML instead (`opentoonz_set_scene_settings`), and a level
is *replaced* by reusing its name and overwriting its drawings.

## `Level`

| Callable | Absent |
| --- | --- |
| `.name`, `.type`, `.path`, `.frameCount` (properties), `getFrame(fid)`, `setFrame(fid, image)`, `load`, `save` | `saveAs`, `getPath`, `getFrameIds`, `isReadOnly` |

## Behaviour worth knowing

- **`setFrame` never reaches the renderer.** Paint levels on disk, not in script
  (facts 21–22).
- **SVG/vector loads but renders blank** (fact 23) — see below.
- **Success is a marker, not an exit code** — a fine script may exit `1`
  (facts 5, 24).

## Descoped features (with the evidence)

| Feature | Why it is descoped |
| --- | --- |
| **Cell / column deletion** (roadmap B6) | `clearCell` / `removeCell` / `removeLevel` / `deleteLevel` are all **absent** from `Scene`. Nothing can be removed from an xsheet, so no delete tool is offered. Reuse the level name and overwrite instead. |
| **Vector / SVG levels** (roadmap B7) | `loadLevel(name, "shape.svg")` reports `type=Vector, frameCount=1` but every variant tried (filled `<rect>`, filled/stroked `<path>`) rendered **0 opaque pixels** (fact 23). Raster PNG levels are the supported path. |
| **Camera splines / FX graphs / palette editing / auto-inbetweening / audio tracks** | GUI-only; not bound (fact 26). Camera motion is done by patching the camera's stage-object channels (`opentoonz_camera_move`), FX by pre-baking in the image pipeline, and audio by muxing with ffmpeg at the end. |
