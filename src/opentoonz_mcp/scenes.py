"""Scene operations: create, inspect, import levels, and place cells.

Scenes are ``.tnz`` files that live at the workspace root. Level import is
*additive*: if the scene already exists it is loaded first, so several levels
can be layered into one scene across multiple calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import bridge
from . import workspace as workspace_mod
from .bridge import OK_MARKER, ScriptResult
from .context import Context
from .errors import OpentoonzMCPError


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


def scene_new(context: Context, workspace: str, scene: str = "main") -> ScriptResult:
    """Create (or overwrite) an empty scene."""
    ws = workspace_mod.require(context, workspace)
    scene_path = ws.scene_path(scene)
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    code = "var scene = new Scene();\nscene.save(" + _js(scene_path) + ");\n" + f'print("{OK_MARKER}");\n'
    return bridge.run_script_or_raise(context, ws.root, code)


def import_level(
    context: Context,
    workspace: str,
    level_name: str,
    image_paths: list[str],
    scene: str = "main",
    start_row: int = 0,
    column: int = 0,
) -> tuple[ScriptResult, list[Path]]:
    """Import an ordered image sequence as a raster level and place it.

    Images are converted to RGBA PNG (OpenToonz refuses RGB-only images at
    render time) and named ``<level_name>.%04d.png`` so ``loadLevel``'s
    ``<level>..png`` sequence pattern finds them.
    """
    ws = workspace_mod.require(context, workspace)
    if not image_paths:
        raise OpentoonzMCPError("image_paths must contain at least one file")
    ws.drawings.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for index, src in enumerate(image_paths, start=1):
        src_path = Path(src)
        if not src_path.is_file():
            raise OpentoonzMCPError(f"Image not found: {src}")
        dst = ws.drawings / f"{level_name}.{index:04d}.png"
        with Image.open(src_path) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            img.save(dst, format="PNG")
        copied.append(dst)

    scene_path = ws.scene_path(scene)
    init = f"var scene = new Scene({_js(scene_path)});" if scene_path.exists() else "var scene = new Scene();"
    pattern = str(ws.drawings / f"{level_name}..png")
    code = "\n".join(
        [
            init,
            f"var level = scene.loadLevel({_js(level_name)}, {_js(pattern)});",
            'if (!level) throw new Error("loadLevel returned nothing for the image sequence");',
            'print("LEVEL-FRAMES=" + level.frameCount);',
            "var n = level.frameCount;",
            f"for (var r = 0; r < n; r++) {{ scene.setCell({int(start_row)} + r, {int(column)}, level, r + 1); }}",
            f"scene.save({_js(scene_path)});",
            f'print("{OK_MARKER}");',
            "",
        ]
    )
    return bridge.run_script_or_raise(context, ws.root, code), copied


def scene_info(context: Context, workspace: str, scene: str) -> SceneInfo:
    """Read frame/column counts, levels, and the cell map of a saved scene."""
    ws = workspace_mod.require(context, workspace)
    scene_path = ws.scene_path(scene)
    if not scene_path.is_file():
        raise OpentoonzMCPError(f"Scene not found: {scene_path}")
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
            "var maxRow = Math.min(scene.frameCount, 1000);",
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
    for line in stdout.splitlines():
        if line.startswith("FRAMECOUNT="):
            frame_count = int(line.split("=", 1)[1] or 0)
        elif line.startswith("COLUMNS="):
            column_count = int(line.split("=", 1)[1] or 0)
        elif line.startswith("LEVEL|"):
            _, name, ltype, frames, path = line.split("|", 4)
            levels.append(LevelInfo(name=name, type=ltype, frame_count=frames, path=path))
        elif line.startswith("CELL|"):
            _, row, col, level, fid = line.split("|", 4)
            cells.append(CellInfo(row=int(row), column=int(col), level=level, fid=fid))
    return SceneInfo(frame_count=frame_count, column_count=column_count, levels=levels, cells=cells)


def set_cells(context: Context, workspace: str, scene: str, placements: list[dict]) -> ScriptResult:
    """Place/replace cells on a saved scene's xsheet."""
    ws = workspace_mod.require(context, workspace)
    scene_path = ws.scene_path(scene)
    if not scene_path.is_file():
        raise OpentoonzMCPError(f"Scene not found: {scene_path}")
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
