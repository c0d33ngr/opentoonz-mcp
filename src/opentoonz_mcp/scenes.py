"""Scene operations: create, resize, inspect, import levels, and time cells.

Scenes are ``.tnz`` files that live at the workspace root. Level import is
*additive*: if the scene already exists it is loaded first, so several levels
can be layered into one scene across multiple calls.

Two OpenToonz quirks shape this module:

* **Scene settings are not scriptable.** ``scene.setCameraSize``,
  ``setFrameCount`` and friends do not exist in the scripting API. Camera
  resolution and frame rate live in the ``.tnz`` file, which is plain XML, so
  :func:`set_scene_settings` patches it directly. A subsequent JS scene
  round-trip preserves those edits (verified), so ordering is not delicate.
* **Nothing can be deleted.** There is no ``removeLevel``/``clearCell``, so
  re-importing a level *reuses* it rather than replacing it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import bridge
from . import workspace as workspace_mod
from .bridge import OK_MARKER, ScriptResult
from .context import Context
from .errors import OpentoonzMCPError

#: Frames scanned by :func:`scene_info` unless the caller asks for more. The
#: xsheet is scanned cell by cell, so this guards against huge scenes.
DEFAULT_MAX_ROWS = 1000

#: A sane upper bound for a camera, to catch typos before they reach the renderer.
MAX_DIMENSION = 16384

#: Dots per inch OpenToonz assumes for a PNG with no resolution metadata. Art
#: pixels map to the camera's physical size at this rate, so the camera's
#: physical size must scale with the resolution for art drawn at the scene's
#: size to fill the frame. Established empirically: the default scene
#: (1920x1080 over a 16x9 inch camera) is exactly 120 dpi.
IMAGE_DPI = 120.0

#: Level names become file names (``<level>.0001.png``), so keep them boring.
_LEVEL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: The camera resolution/size live in the .tnz XML; capture the surrounding
#: whitespace so the file keeps its original layout.
_CAMERA_RES_RE = re.compile(r"<cameraRes>(\s*)\d+\s+\d+(\s*)</cameraRes>")
_CAMERA_SIZE_RE = re.compile(r"<cameraSize>(\s*)[\d.]+(?:\s+[\d.]+)?(\s*)</cameraSize>")
_FPS_RE = re.compile(r"<fps>(\s*)\d+(\s*)</fps>")
_CURRENT_RES_RE = re.compile(r"<cameraRes>\s*(\d+)\s+(\d+)\s*</cameraRes>")
_CURRENT_SIZE_RE = re.compile(r"<cameraSize>\s*([\d.]+)\s+([\d.]+)\s*</cameraSize>")
_CURRENT_FPS_RE = re.compile(r"<fps>\s*(\d+)\s*</fps>")


def _js(value: object) -> str:
    return json.dumps(str(value))


@dataclass
class LevelInfo:
    name: str
    type: str
    frame_count: str
    path: str


@dataclass
class CellInfo:
    row: int
    column: int
    level: str
    fid: str


@dataclass
class SceneInfo:
    frame_count: int
    column_count: int
    levels: list[LevelInfo] = field(default_factory=list)
    cells: list[CellInfo] = field(default_factory=list)
    cells_truncated: bool = False


@dataclass
class LevelImport:
    """Outcome of importing one level."""

    result: ScriptResult
    level_name: str
    copied: list[Path]
    reused: bool = False
    frame_count: int = 0


@dataclass
class SceneSettings:
    """The scene settings after a change."""

    width: int
    height: int
    camera_size: str
    fps: int | None = None
    changed: list[str] = field(default_factory=list)


def validate_level_name(level_name: str) -> str:
    """Reject level names that would make unsafe file names."""
    if not _LEVEL_NAME_RE.match(level_name or ""):
        raise OpentoonzMCPError(
            f"Invalid level name {level_name!r}: use 1-64 characters from A-Z a-z 0-9 _ - "
            "(the name becomes a file prefix in drawings/)."
        )
    return level_name


# -- scene settings (patched into the .tnz XML) -------------------------------
def _format_length(value: float) -> str:
    """Format a camera dimension without noise (``6.0`` -> ``6``, ``6.4`` -> ``6.4``)."""
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _camera_size_for(width: int, height: int) -> str:
    """The camera's physical size (inches) for a resolution.

    Art is composited at :data:`IMAGE_DPI`, so the camera's *physical* size has
    to grow with the resolution. Leaving it at the 16x9 default while shrinking
    the resolution renders the art proportionally smaller (640x360 art in a
    640x360 frame came out 213x120).
    """
    return f"{_format_length(width / IMAGE_DPI)} {_format_length(height / IMAGE_DPI)}"


def _current_camera_size(text: str) -> str:
    """The scene's current ``<cameraSize>`` text, as a fallback."""
    match = _CURRENT_SIZE_RE.search(text)
    return f"{match.group(1)} {match.group(2)}" if match else ""


def _read_int(value: object, label: str) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise OpentoonzMCPError(f"{label} must be an integer, got {value!r}") from exc
    if not 1 <= number <= MAX_DIMENSION:
        raise OpentoonzMCPError(f"{label} must be between 1 and {MAX_DIMENSION}, got {number}")
    return number


def set_scene_settings(
    context: Context,
    workspace: str,
    scene: str,
    *,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
) -> SceneSettings:
    """Change a scene's camera resolution and/or frame rate.

    The scripting API exposes no setters for these, so the ``.tnz`` (plain XML)
    is patched in place. ``width``/``height`` may be given independently; the
    omitted one keeps its current value. The camera's physical size is rescaled
    to match, so artwork drawn at the scene's size still fills the frame.
    """
    ws = workspace_mod.require(context, workspace)
    scene_path = ws.scene_path(scene)
    if not scene_path.is_file():
        raise OpentoonzMCPError(f"Scene not found: {scene_path}")
    if width is None and height is None and fps is None:
        raise OpentoonzMCPError("Nothing to change: pass width, height, and/or fps.")

    text = scene_path.read_text(encoding="utf-8")
    current = _CURRENT_RES_RE.search(text)
    if current is None:
        raise OpentoonzMCPError(f"No <cameraRes> found in {scene_path}; is it a valid scene?")

    new_width = _read_int(width, "width") if width is not None else int(current.group(1))
    new_height = _read_int(height, "height") if height is not None else int(current.group(2))
    camera_size = _camera_size_for(new_width, new_height)

    changed: list[str] = []
    if (new_width, new_height) != (int(current.group(1)), int(current.group(2))):
        text = _CAMERA_RES_RE.sub(
            lambda m: f"<cameraRes>{m.group(1)}{new_width} {new_height}{m.group(2)}</cameraRes>",
            text,
            count=1,
        )
        text = _CAMERA_SIZE_RE.sub(
            lambda m: f"<cameraSize>{m.group(1)}{camera_size}{m.group(2)}</cameraSize>",
            text,
            count=1,
        )
        changed.append(f"cameraRes={new_width}x{new_height}")
        changed.append(f"cameraSize={camera_size}")

    current_fps_match = _CURRENT_FPS_RE.search(text)
    current_fps = int(current_fps_match.group(1)) if current_fps_match else None
    if fps is not None:
        new_fps = _read_int(fps, "fps")
        if new_fps != current_fps:
            text = _FPS_RE.sub(lambda m: f"<fps>{m.group(1)}{new_fps}{m.group(2)}</fps>", text)
            changed.append(f"fps={new_fps}")
        current_fps = new_fps

    scene_path.write_text(text, encoding="utf-8")
    return SceneSettings(width=new_width, height=new_height, camera_size=camera_size, fps=current_fps, changed=changed)


def scene_new(
    context: Context,
    workspace: str,
    scene: str = "main",
    *,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
) -> SceneSettings:
    """Create (or overwrite) an empty scene, optionally resizing it.

    The default camera is 1920x1080; pass ``width``/``height`` to change it. Art
    is composited 1:1 and centred, so draw at the scene's size for full-frame
    output.
    """
    ws = workspace_mod.require(context, workspace)
    scene_path = ws.scene_path(scene)
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    code = "var scene = new Scene();\nscene.save(" + _js(scene_path) + ");\n" + f'print("{OK_MARKER}");\n'
    bridge.run_script_or_raise(context, ws.root, code)
    if width is None and height is None and fps is None:
        text = scene_path.read_text(encoding="utf-8")
        current = _CURRENT_RES_RE.search(text)
        width_now = int(current.group(1)) if current else 0
        height_now = int(current.group(2)) if current else 0
        fps_match = _CURRENT_FPS_RE.search(text)
        return SceneSettings(
            width=width_now,
            height=height_now,
            camera_size=_current_camera_size(text) or _camera_size_for(width_now, height_now),
            fps=int(fps_match.group(1)) if fps_match else None,
        )
    return set_scene_settings(context, workspace, scene, width=width, height=height, fps=fps)


# -- level import -------------------------------------------------------------
def _numbered_drawings(level_name: str) -> re.Pattern[str]:
    """Matches exactly the frames belonging to ``level_name`` (not 'balloon')."""
    return re.compile(rf"^{re.escape(level_name)}\.\d{{4}}\.png$")


def import_level(
    context: Context,
    workspace: str,
    level_name: str,
    image_paths: list[str],
    scene: str = "main",
    start_row: int = 0,
    column: int = 0,
) -> LevelImport:
    """Import an ordered image sequence as a raster level and place it.

    Images are converted to RGBA PNG (OpenToonz refuses RGB-only images at
    render time) and named ``<level_name>.%04d.png`` so ``loadLevel``'s
    ``<level>..png`` sequence pattern finds them.

    Safe to call repeatedly for the same ``level_name``: OpenToonz cannot delete
    a level, and re-adding a name it already knows is an error, so an existing
    level is reused and its drawings are overwritten with the new art.
    """
    ws = workspace_mod.require(context, workspace)
    validate_level_name(level_name)
    if not image_paths:
        raise OpentoonzMCPError("image_paths must contain at least one file")
    ws.drawings.mkdir(parents=True, exist_ok=True)

    # Validate every source before touching anything, so one bad path cannot
    # leave the workspace half-imported.
    sources: list[Path] = []
    for src in image_paths:
        src_path = Path(src)
        if not src_path.is_file():
            raise OpentoonzMCPError(f"Image not found: {src}")
        if src_path.suffix.lower() == ".svg":
            raise OpentoonzMCPError(
                f"{src} is an SVG. Vector levels load but rasterise to nothing when rendered "
                "headlessly (see docs/troubleshooting.md) — convert it to PNG first."
            )
        sources.append(src_path.resolve())

    # Clear this level's previous frames first: a shorter sequence would
    # otherwise leave orphaned higher-numbered frames that loadLevel picks up.
    # Sources are spared, because drawing straight into drawings/ is the normal
    # workflow and would otherwise delete the very files being imported.
    keep = set(sources)
    stale = _numbered_drawings(level_name)
    for existing in ws.drawings.iterdir():
        if stale.match(existing.name) and existing.resolve() not in keep:
            existing.unlink(missing_ok=True)

    copied: list[Path] = []
    for index, src_path in enumerate(sources, start=1):
        dst = ws.drawings / f"{level_name}.{index:04d}.png"
        # Read fully into memory before saving: the source may be the
        # destination (re-importing a level's own drawings).
        with Image.open(src_path) as img:
            frame = img if img.mode == "RGBA" else img.convert("RGBA")
            frame = frame.copy()
        frame.save(dst, format="PNG")
        copied.append(dst)

    scene_path = ws.scene_path(scene)
    init = f"var scene = new Scene({_js(scene_path)});" if scene_path.exists() else "var scene = new Scene();"
    pattern = str(ws.drawings / f"{level_name}..png")
    code = "\n".join(
        [
            init,
            f"var NAME = {_js(level_name)};",
            "var level = null;",
            "var levels = scene.getLevels();",
            "for (var i = 0; i < levels.length; i++) { if (levels[i].name === NAME) { level = levels[i]; } }",
            "var reused = (level !== null);",
            f"if (!level) {{ level = scene.loadLevel(NAME, {_js(pattern)}); }}",
            'if (!level) throw new Error("loadLevel returned nothing for the image sequence");',
            'print("LEVEL-REUSED=" + (reused ? 1 : 0));',
            'print("LEVEL-FRAMES=" + level.frameCount);',
            "var n = level.frameCount;",
            f"for (var r = 0; r < n; r++) {{ scene.setCell({int(start_row)} + r, {int(column)}, level, r + 1); }}",
            f"scene.save({_js(scene_path)});",
            f'print("{OK_MARKER}");',
            "",
        ]
    )
    result = bridge.run_script_or_raise(context, ws.root, code)
    return LevelImport(
        result=result,
        level_name=level_name,
        copied=copied,
        reused="LEVEL-REUSED=1" in result.stdout,
        frame_count=_marker_int(result.stdout, "LEVEL-FRAMES="),
    )


def _marker_int(stdout: str, prefix: str) -> int:
    for line in stdout.splitlines():
        if line.startswith(prefix):
            try:
                return int(line[len(prefix) :].strip())
            except ValueError:
                return 0
    return 0


# -- inspection ---------------------------------------------------------------
def scene_info(context: Context, workspace: str, scene: str, max_rows: int = DEFAULT_MAX_ROWS) -> SceneInfo:
    """Read frame/column counts, levels, and the cell map of a saved scene.

    The cell map is scanned row by row, so it stops at ``max_rows`` (default
    1000) and reports ``cells_truncated`` when the scene is taller than that.
    """
    ws = workspace_mod.require(context, workspace)
    scene_path = ws.scene_path(scene)
    if not scene_path.is_file():
        raise OpentoonzMCPError(f"Scene not found: {scene_path}")
    limit = max(1, int(max_rows))
    code = "\n".join(
        [
            f"var scene = new Scene({_js(scene_path)});",
            'print("FRAMECOUNT=" + scene.frameCount);',
            'print("COLUMNS=" + scene.columnCount);',
            "var levels = scene.getLevels();",
            "for (var i = 0; i < levels.length; i++) {",
            "  var L = levels[i];",
            '  print("LEVEL|" + L.name + "|" + L.type + "|" + L.frameCount + "|" + L.path);',
            "}",
            f"var maxRow = Math.min(scene.frameCount, {limit});",
            'print("TRUNCATED=" + (scene.frameCount > maxRow ? 1 : 0));',
            "for (var c = 0; c < scene.columnCount; c++) {",
            "  for (var r = 0; r < maxRow; r++) {",
            "    var cell = scene.getCell(r, c);",
            '    if (cell) print("CELL|" + r + "|" + c + "|" + cell.level.name + "|" + cell.fid);',
            "  }",
            "}",
            f'print("{OK_MARKER}");',
            "",
        ]
    )
    result = bridge.run_script_or_raise(context, ws.root, code)
    return parse_scene_info(result.stdout)


def parse_scene_info(stdout: str) -> SceneInfo:
    frame_count = 0
    column_count = 0
    levels: list[LevelInfo] = []
    cells: list[CellInfo] = []
    truncated = False
    for line in stdout.splitlines():
        if line.startswith("FRAMECOUNT="):
            frame_count = int(line.split("=", 1)[1] or 0)
        elif line.startswith("COLUMNS="):
            column_count = int(line.split("=", 1)[1] or 0)
        elif line.startswith("TRUNCATED="):
            truncated = line.split("=", 1)[1].strip() == "1"
        elif line.startswith("LEVEL|"):
            _, name, ltype, frames, path = line.split("|", 4)
            levels.append(LevelInfo(name=name, type=ltype, frame_count=frames, path=path))
        elif line.startswith("CELL|"):
            _, row, col, level, fid = line.split("|", 4)
            cells.append(CellInfo(row=int(row), column=int(col), level=level, fid=fid))
    return SceneInfo(
        frame_count=frame_count,
        column_count=column_count,
        levels=levels,
        cells=cells,
        cells_truncated=truncated,
    )


def set_cells(context: Context, workspace: str, scene: str, placements: list[dict]) -> ScriptResult:
    """Place/replace cells on a saved scene's xsheet."""
    ws = workspace_mod.require(context, workspace)
    scene_path = ws.scene_path(scene)
    if not scene_path.is_file():
        raise OpentoonzMCPError(f"Scene not found: {scene_path}")
    if not placements:
        raise OpentoonzMCPError("placements must contain at least one entry")
    for placement in placements:
        missing = [key for key in ("row", "col", "level", "fid") if key not in placement]
        if missing:
            raise OpentoonzMCPError(f"Each placement needs {missing}, got {placement!r}")
    code = "\n".join(
        [
            f"var scene = new Scene({_js(scene_path)});",
            f"var P = {json.dumps(placements)};",
            "for (var i = 0; i < P.length; i++) { scene.setCell(P[i].row, P[i].col, P[i].level, P[i].fid); }",
            f"scene.save({_js(scene_path)});",
            f'print("{OK_MARKER}");',
            "",
        ]
    )
    return bridge.run_script_or_raise(context, ws.root, code)


# -- exposure timing ----------------------------------------------------------
def expand_exposures(exposures: list[int], drawing_count: int) -> list[tuple[int, int]]:
    """Turn hold lengths into ``(row, fid)`` placements, starting at row 0.

    ``exposures`` is either a single hold applied to every drawing (``[3]`` =
    hold each on 3s) or one hold per drawing (``[3, 3, 1, 2]``). Extra values are
    ignored.

    Every row of a hold gets its own placement: an empty xsheet row renders
    nothing, so "holding" means repeating the drawing's fid across the rows, not
    leaving gaps. The result is therefore one entry per frame to be rendered.
    """
    if drawing_count <= 0:
        raise OpentoonzMCPError("Cannot time a level that has no drawings.")
    if not exposures:
        raise OpentoonzMCPError("exposures must contain at least one hold length.")
    holds = [int(value) for value in exposures]
    if any(hold < 1 for hold in holds):
        raise OpentoonzMCPError(f"Every hold must be at least 1 frame, got {exposures!r}")
    if len(holds) == 1:
        holds = holds * drawing_count
    if len(holds) < drawing_count:
        raise OpentoonzMCPError(
            f"exposures has {len(holds)} values but the level has {drawing_count} drawings: "
            "pass a single value (the same hold for every drawing) or one per drawing."
        )
    placements: list[tuple[int, int]] = []
    row = 0
    for index in range(drawing_count):
        for _ in range(holds[index]):
            placements.append((row, index + 1))
            row += 1
    return placements


def set_exposure(
    context: Context,
    workspace: str,
    scene: str,
    level: str,
    exposures: list[int],
    start_row: int = 0,
    column: int = 0,
) -> tuple[ScriptResult, list[tuple[int, int]]]:
    """Time a level's drawings on the xsheet, holding each for N frames.

    ``[3]`` holds every drawing on 3s; ``[2, 4, 1]`` gives drawing 1 two frames,
    drawing 2 four, and drawing 3 one. The scene's frame count follows the cells
    that are placed. The level must already be in the scene. Returns the
    ``(row, fid)`` pairs that were placed.
    """
    info = scene_info(context, workspace, scene)
    known = next((entry for entry in info.levels if entry.name == level), None)
    if known is None:
        raise OpentoonzMCPError(
            f"Level '{level}' is not in scene '{scene}'. Import it first with opentoonz_import_images_as_level."
        )
    pairs = expand_exposures(exposures, int(known.frame_count))
    placements = [{"row": int(start_row) + row, "col": int(column), "level": level, "fid": fid} for row, fid in pairs]
    return set_cells(context, workspace, scene, placements), pairs
