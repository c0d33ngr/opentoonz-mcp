"""FastMCP server: headless OpenToonz automation tools for AI agents."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastmcp import FastMCP

from . import __version__, bridge, draw, scenes
from . import render as render_mod
from . import workspace as workspace_mod
from .context import get_context
from .errors import OpentoonzMCPError

mcp = FastMCP(
    "opentoonz-mcp",
    instructions=(
        "Headless OpenToonz automation. Typical flow: opentoonz_create_workspace → "
        "draw or import an image sequence as an animation level → opentoonz_set_cells "
        "to time it on the xsheet → opentoonz_render_frame to look at the result → "
        "opentoonz_render_video to produce an MP4. Everything runs through OpenToonz's "
        "scripting CLI and the official tcomposer renderer; no GUI is required. "
        "Use opentoonz_run_script as a generic escape hatch for the full JS API."
    ),
    version=__version__,
)


def _fail(exc: Exception) -> str:
    return f"ERROR [{type(exc).__name__}]: {exc}"


def _which_ffmpeg(ctx) -> str | None:
    """Resolve ffmpeg, honouring an absolute path in ``OPENTOONZ_FFMPEG``."""
    candidate = ctx.settings.ffmpeg
    if Path(candidate).is_file():
        return candidate
    return shutil.which(candidate)


# -- diagnostics --------------------------------------------------------------
@mcp.tool()
def opentoonz_health() -> str:
    """Quick availability check for the runtime, tcomposer, and ffmpeg."""
    try:
        ctx = get_context()
    except OpentoonzMCPError as exc:
        return _fail(exc)
    missing = []
    if not ctx.runtime.ot_bin.is_file():
        missing.append("OpenToonz binary")
    if not ctx.runtime.tcomposer_bin.is_file():
        missing.append("tcomposer binary")
    if not _which_ffmpeg(ctx):
        missing.append(f"ffmpeg ({ctx.settings.ffmpeg})")
    if missing:
        return f"DEGRADED — missing: {', '.join(missing)}"
    return (
        f"READY — {ctx.runtime.version or 'OpenToonz (unknown version)'}\n"
        f"runtime: {ctx.runtime.ot_bin}\n"
        f"workspaces: {ctx.settings.workspaces_root}"
    )


@mcp.tool()
def opentoonz_doctor() -> str:
    """Full diagnostic: resolved paths, versions, and prepared state."""
    try:
        ctx = get_context()
        ctx.prepare()
    except OpentoonzMCPError as exc:
        return _fail(exc)
    ffmpeg = _which_ffmpeg(ctx)
    lines = [
        f"opentoonz-mcp {__version__}",
        f"runtime root : {ctx.runtime.root}",
        f"OpenToonz    : {ctx.runtime.ot_bin}",
        f"tcomposer    : {ctx.runtime.tcomposer_bin}",
        f"version      : {ctx.runtime.version or 'unknown'}",
        f"stuff (TOONZROOT): {ctx.stuff_root}",
        f"isolated HOME: {ctx.settings.home}",
        f"workspaces   : {ctx.settings.workspaces_root}",
        f"ffmpeg       : {ffmpeg or 'NOT FOUND (' + ctx.settings.ffmpeg + ')'}",
        f"timeouts     : script={ctx.settings.script_timeout}s render={ctx.settings.render_timeout}s",
    ]
    return "\n".join(lines)


# -- workspaces ---------------------------------------------------------------
@mcp.tool()
def opentoonz_create_workspace(name: str) -> str:
    """Create a self-contained workspace folder (idempotent).

    A workspace holds drawings/, render/, and scripts/. The shared OpenToonz
    'stuff' tree is not copied per workspace (it lives once in the data home).
    """
    try:
        workspace, created = workspace_mod.create(get_context(), name)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    verb = "Created" if created else "Already exists (reused)"
    return f"{verb}: workspace '{name}' at {workspace.root}"


@mcp.tool()
def opentoonz_list_workspaces() -> str:
    """List workspaces with their scenes and rendered videos."""
    try:
        workspaces = workspace_mod.list_workspaces(get_context())
    except OpentoonzMCPError as exc:
        return _fail(exc)
    if not workspaces:
        return "No workspaces yet."
    lines = []
    for ws in workspaces:
        scene_names = [p.name for p in ws.scenes()]
        videos = [p.name for p in sorted(ws.render.glob("*.mp4"))]
        frames = len(list(ws.render.glob("*.png")))
        lines.append(f"{ws.name}: scenes={scene_names} videos={videos} frames={frames}")
    return "\n".join(lines)


# -- scenes -------------------------------------------------------------------
@mcp.tool()
def opentoonz_scene_new(workspace: str, scene: str = "main") -> str:
    """Create (or overwrite) an empty scene in a workspace."""
    try:
        result = scenes.scene_new(get_context(), workspace, scene)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return f"OK: created scene '{scene}' ({result.duration:.1f}s)"


@mcp.tool()
def opentoonz_import_images_as_level(
    workspace: str,
    level_name: str,
    image_paths: list[str],
    scene: str = "main",
    start_row: int = 0,
    column: int = 0,
) -> str:
    """Import an ordered image sequence as a raster level and place it on the xsheet.

    Additive: an existing scene is loaded first, so you can call this repeatedly
    with different level_name/column to build a multi-level scene. Images are
    converted to RGBA PNG named <level_name>.%04d.png. The default camera is
    1920x1080 — draw at that size for full-frame output.
    """
    try:
        result, copied = scenes.import_level(
            get_context(), workspace, level_name, image_paths, scene, start_row, column
        )
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return f"OK: imported {len(copied)} frames as level '{level_name}' into '{scene}'\n" + result.summary(
        out_tail=800, err_tail=600
    )


@mcp.tool()
def opentoonz_scene_info(workspace: str, scene: str) -> str:
    """Report a scene's frame/column counts, its levels, and its cell map."""
    try:
        info = scenes.scene_info(get_context(), workspace, scene)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    lines = [f"frames={info.frame_count} columns={info.column_count}"]
    for level in info.levels:
        lines.append(f"level: {level.name} type={level.type} frames={level.frame_count} path={level.path}")
    for cell in info.cells:
        lines.append(f"cell: row={cell.row} col={cell.column} level={cell.level} fid={cell.fid}")
    return "\n".join(lines)


@mcp.tool()
def opentoonz_set_cells(workspace: str, scene: str, placements: list[dict]) -> str:
    """Place/replace cells on a scene's xsheet.

    placements: list of {"row": int, "col": int, "level": str, "fid": int|str}.
    Levels must already exist in the scene (see opentoonz_import_images_as_level).
    """
    try:
        result = scenes.set_cells(get_context(), workspace, scene, placements)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return f"OK: placed {len(placements)} cells into '{scene}'\n" + result.summary(out_tail=400, err_tail=300)


# -- drawing ------------------------------------------------------------------
@mcp.tool()
def opentoonz_draw_frame(
    workspace: str,
    level_name: str,
    ops: list[dict],
    frame: int = 1,
    width: int = draw.DEFAULT_WIDTH,
    height: int = draw.DEFAULT_HEIGHT,
    background: str = draw.DEFAULT_BACKGROUND,
) -> str:
    """Draw one RGBA frame with PIL primitives and save it as a level drawing.

    ops: list of {"op": "rect|ellipse|line|polygon|polyline|text", ...} — see
    docs/tools.md. Saved to <workspace>/drawings/<level_name>.<frame>.png, ready
    for opentoonz_import_images_as_level.
    """
    try:
        ws = workspace_mod.require(get_context(), workspace)
        path = ws.drawings / f"{level_name}.{int(frame):04d}.png"
        draw.draw_frame(path, ops, width=width, height=height, background=background)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return f"OK: drew {len(ops)} ops -> {path}"


@mcp.tool()
def opentoonz_draw_frames(
    workspace: str,
    level_name: str,
    frames: list[list[dict]],
    width: int = draw.DEFAULT_WIDTH,
    height: int = draw.DEFAULT_HEIGHT,
    background: str = draw.DEFAULT_BACKGROUND,
) -> str:
    """Draw a whole sequence of frames, one op-list per frame.

    frames: list where each item is a list of ops for that frame (frame 1 first).
    Saves <workspace>/drawings/<level_name>.%04d.png and returns the paths.
    """
    try:
        ws = workspace_mod.require(get_context(), workspace)
        paths = []
        for index, ops in enumerate(frames, start=1):
            path = ws.drawings / f"{level_name}.{index:04d}.png"
            draw.draw_frame(path, ops, width=width, height=height, background=background)
            paths.append(str(path))
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return f"OK: drew {len(paths)} frames for level '{level_name}'\n" + "\n".join(paths)


# -- rendering ----------------------------------------------------------------
@mcp.tool()
def opentoonz_render_frame(workspace: str, scene: str, frame: int = 1, out_name: str = "look") -> str:
    """Render a single frame to a PNG — the agent's 'look' at the result."""
    try:
        result = render_mod.render_frame(get_context(), workspace, scene, frame=frame, out_name=out_name)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    if not result.frames:
        return f"FAILED (exit={result.exit_code}, {result.duration:.1f}s)\n{result.log}"
    return f"OK: frame -> {result.frames[0]}"


@mcp.tool()
def opentoonz_render(workspace: str, scene: str, out_name: str = "render") -> str:
    """Render a scene to PNG frames under <workspace>/render/ with tcomposer."""
    try:
        result = render_mod.render_frames(get_context(), workspace, scene, out_name=out_name)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    if not result.frames:
        return f"FAILED (exit={result.exit_code}, {result.duration:.1f}s)\n{result.log}"
    return f"OK: {len(result.frames)} frames -> {result.frames[0].parent} ({result.duration:.1f}s)"


@mcp.tool()
def opentoonz_render_video(workspace: str, scene: str, fps: int = 24, out_name: str = "video") -> str:
    """Render a scene and mux the frames into an MP4 with ffmpeg."""
    try:
        video, result = render_mod.render_video(get_context(), workspace, scene, fps=fps, out_name=out_name)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return f"OK: {len(result.frames)} frames @ {fps}fps -> {video}"


# -- escape hatch -------------------------------------------------------------
@mcp.tool()
def opentoonz_run_script(workspace: str, code: str, timeout: int = 90) -> str:
    """Run arbitrary OpenToonz JavaScript headlessly (the full-power escape hatch).

    The script can use the OpenToonz API: new Scene(path?), scene.newLevel(type,
    name), scene.loadLevel(name, "path/<level>..png"), scene.setCell(row, col,
    level, fid), scene.getCell(row, col), scene.getLevels(), scene.save(path),
    new Image(path), image.save(path), level.setFrame(fid, image). Use print()
    for output; stdout is returned. Do NOT use new Renderer() — renderFrame
    deadlocks in CLI mode; use opentoonz_render instead. Use absolute paths.
    """
    try:
        ctx = get_context()
        ws = workspace_mod.require(ctx, workspace)
        result = bridge.run_script(ctx, ws.root, code, timeout=timeout)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return result.summary()


def main() -> None:
    """Console entry point."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
