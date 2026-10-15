"""FastMCP server: headless OpenToonz automation tools for AI agents."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastmcp import FastMCP
from PIL import Image

from . import __version__, bridge, draw, scenes
from . import render as render_mod
from . import workspace as workspace_mod
from .context import get_context
from .errors import OpentoonzMCPError

mcp = FastMCP(
    "opentoonz-mcp",
    instructions=(
        "Headless OpenToonz automation. Typical flow: opentoonz_create_workspace → "
        "draw or import an image sequence as an animation level → opentoonz_exposure "
        "(or opentoonz_set_cells) to time it on the xsheet → opentoonz_render_frame to "
        "look at the result → opentoonz_render_video to produce an MP4. Everything runs "
        "through OpenToonz's scripting CLI and the official tcomposer renderer; no GUI "
        "is required. opentoonz_scene_new and opentoonz_set_scene_settings change the "
        "camera resolution, and opentoonz_camera_move animates the camera over time "
        "(pan, zoom, rotate). Use opentoonz_run_script as a generic escape hatch for "
        "the full JS API."
    ),
    version=__version__,
)


def _fail(exc: Exception) -> str:
    return f"ERROR [{type(exc).__name__}]: {exc}"


def _format_exposure(pairs: list[tuple[int, int]]) -> str:
    """Compress ``(row, fid)`` placements into runs, e.g. ``fid 1: rows 0-1``."""
    runs: list[list[int]] = []
    for row, fid in pairs:
        if runs and runs[-1][2] == fid and runs[-1][1] + 1 == row:
            runs[-1][1] = row
        else:
            runs.append([row, row, fid])
    return ", ".join(
        f"fid {fid}: row {first}" if first == last else f"fid {fid}: rows {first}-{last}" for first, last, fid in runs
    )


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
        gifs = [p.name for p in sorted(ws.render.glob("*.gif"))]
        frames = len(list(ws.render.glob("*.png")))
        lines.append(
            f"{ws.name}: scenes={scene_names} videos={videos} gifs={gifs} frames={frames} "
            f"size={workspace_mod.human_size(workspace_mod.disk_usage(ws))}"
        )
    return "\n".join(lines)


# -- scenes -------------------------------------------------------------------
@mcp.tool()
def opentoonz_scene_new(
    workspace: str,
    scene: str = "main",
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
) -> str:
    """Create (or overwrite) an empty scene, optionally setting its resolution.

    The default camera is 1920x1080. Levels composite 1:1 and centred, so draw
    your art at the scene's size for full-frame output.
    """
    try:
        settings = scenes.scene_new(get_context(), workspace, scene, width=width, height=height, fps=fps)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    rate = f" @ {settings.fps}fps" if settings.fps else ""
    return f"OK: created scene '{scene}' at {settings.width}x{settings.height}{rate}"


@mcp.tool()
def opentoonz_set_scene_settings(
    workspace: str,
    scene: str,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
) -> str:
    """Change a scene's camera resolution and/or frame rate (e.g. 1080p -> 720p).

    OpenToonz's scripting API has no setters for these, so the scene file's XML
    is patched directly; later edits to the scene keep the new settings. `width`
    and `height` may be given independently — the omitted one keeps its value.
    Re-render after changing this, and draw new art at the new size.
    """
    try:
        settings = scenes.set_scene_settings(get_context(), workspace, scene, width=width, height=height, fps=fps)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    changed = ", ".join(settings.changed) if settings.changed else "nothing (already set)"
    return (
        f"OK: scene '{scene}' is now {settings.width}x{settings.height} "
        f"(camera {settings.camera_size}), fps={settings.fps}\nchanged: {changed}"
    )


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
    converted to RGBA PNG named <level_name>.%04d.png, and levels composite 1:1
    and centred — draw at the scene's size (1920x1080 by default) for full-frame
    output.

    Re-importing the same level_name reuses that level and overwrites its
    drawings, so you can iterate on art without the level being duplicated.
    """
    try:
        imported = scenes.import_level(get_context(), workspace, level_name, image_paths, scene, start_row, column)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    verb = "reused" if imported.reused else "imported"
    return (
        f"OK: {verb} {len(imported.copied)} frames as level '{level_name}' "
        f"({imported.frame_count} drawings) into '{scene}'\n" + imported.result.summary(out_tail=800, err_tail=600)
    )


@mcp.tool()
def opentoonz_scene_info(workspace: str, scene: str, max_rows: int = scenes.DEFAULT_MAX_ROWS) -> str:
    """Report a scene's frame/column counts, its levels, and its cell map.

    The cell map is scanned row by row and stops at max_rows (default 1000);
    the output says so explicitly when a scene is taller than that.
    """
    try:
        info = scenes.scene_info(get_context(), workspace, scene, max_rows=max_rows)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    lines = [f"frames={info.frame_count} columns={info.column_count}"]
    if info.cells_truncated:
        lines.append(f"note: cell list truncated at max_rows={max_rows} (raise max_rows to see the rest)")
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
    For the common animation task of holding each drawing for N frames, use
    opentoonz_exposure instead of computing rows yourself.
    """
    try:
        result = scenes.set_cells(get_context(), workspace, scene, placements)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return f"OK: placed {len(placements)} cells into '{scene}'\n" + result.summary(out_tail=400, err_tail=300)


@mcp.tool()
def opentoonz_exposure(
    workspace: str,
    scene: str,
    level: str,
    exposures: list[int],
    start_row: int = 0,
    column: int = 0,
) -> str:
    """Time a level's drawings on the xsheet by holding each one for N frames.

    exposures is either a single hold for every drawing ([3] = hold all on 3s)
    or one hold per drawing in order ([2, 4, 1]). Rows are contiguous, and the
    scene's frame count follows what is placed. The level must already be in the
    scene (see opentoonz_import_images_as_level).
    """
    try:
        result, placements = scenes.set_exposure(get_context(), workspace, scene, level, exposures, start_row, column)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return (
        f"OK: timed {len(placements)} frames of '{level}' into '{scene}'\n"
        f"{_format_exposure(placements)}\n" + result.summary(out_tail=300, err_tail=200)
    )


@mcp.tool()
def opentoonz_camera_move(workspace: str, scene: str, keyframes: list[dict]) -> str:
    """Move the scene's camera over the shot — pan, zoom, and rotate.

    keyframes: list of {"frame": int, "x": px, "y": px, "zoom": factor,
    "rotation": degrees}. Only "frame" is required; the rest default to no
    movement (x=0, y=0, zoom=1, rotation=0). "frame" is a 1-based shot frame —
    the same numbering as opentoonz_render_frame.

    x/y are the camera's position in scene pixels: +x pans the view right and +y
    pans it up, so the artwork moves the opposite way. zoom is a magnification
    (2 renders the art twice as large), and rotation is in degrees, clockwise on
    screen, about the frame centre. OpenToonz interpolates linearly between
    keyframes.

    The move is stored in the scene file as the camera's animation channels, so
    it survives later edits and stays editable in OpenToonz's Function Editor.
    Re-render to see it.
    """
    try:
        moved = scenes.camera_move(get_context(), workspace, scene, keyframes)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return (
        f"OK: camera move over {len(moved.keyframes)} keyframes, frames "
        f"{moved.first_frame}-{moved.last_frame} in '{scene}'\n"
        f"channels: {', '.join(moved.channels)} at {moved.px_per_inch:g} px/unit"
    )


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

    ops: list of {"op": "rect|ellipse|line|polygon|polyline|text|image", ...} —
    see docs/tools.md. The "image" op composites an existing PNG, so art made
    elsewhere can join a drawn frame. Saved to
    <workspace>/drawings/<level_name>.<frame>.png, ready for
    opentoonz_import_images_as_level.
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
def _png_size(path: Path) -> str:
    with Image.open(path) as img:
        return f"{img.width}x{img.height}"


@mcp.tool()
def opentoonz_render_frame(
    workspace: str, scene: str, frame: int = 1, out_name: str = "look", max_width: int | None = None
) -> str:
    """Render a single frame to a PNG — the agent's 'look' at the result.

    max_width (optional) downscales the returned PNG in place to that width, so
    a large scene costs fewer image tokens to inspect. The file itself becomes
    the smaller preview; the scene's resolution is unchanged, and
    opentoonz_render / opentoonz_render_video output is never downscaled.
    """
    try:
        result = render_mod.render_frame(
            get_context(), workspace, scene, frame=frame, out_name=out_name, max_width=max_width
        )
    except OpentoonzMCPError as exc:
        return _fail(exc)
    if not result.frames:
        return f"FAILED (exit={result.exit_code}, {result.duration:.1f}s)\n{result.log}"
    size = _png_size(result.frames[0])
    if result.downscaled_from:
        source = result.downscaled_from
        return f"OK: frame -> {result.frames[0]} ({size}, downscaled from {source[0]}x{source[1]})"
    return f"OK: frame -> {result.frames[0]} ({size})"


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
def opentoonz_render_video(
    workspace: str, scene: str, fps: int = 24, out_name: str = "video", audio: str | None = None
) -> str:
    """Render a scene and mux the frames into an MP4 with ffmpeg.

    audio (optional) is a path to an external soundtrack (mp3, wav, ...). It is
    encoded as AAC and cut to the video's length. OpenToonz's own audio columns
    cannot be reached from the scripting API, so audio always comes from a file.
    """
    try:
        video, result = render_mod.render_video(
            get_context(), workspace, scene, fps=fps, out_name=out_name, audio=audio
        )
    except OpentoonzMCPError as exc:
        return _fail(exc)
    track = f" + audio {Path(audio).name}" if audio else ""
    return f"OK: {len(result.frames)} frames @ {fps}fps{track} -> {video}"


@mcp.tool()
def opentoonz_render_gif(
    workspace: str,
    scene: str,
    fps: int = 12,
    out_name: str = "reel",
    max_width: int | None = None,
    colors: int = 256,
) -> str:
    """Render a scene to a looping GIF — the shareable form of a short move.

    fps sets playback speed (12–15 reads well for hand-drawn work), max_width
    downscales the GIF, and colors caps the palette (2–256). Frames come from the
    same tcomposer pass as opentoonz_render_video; use that for anything with
    audio or that must stay full resolution.
    """
    try:
        gif, result = render_mod.render_gif(
            get_context(), workspace, scene, fps=fps, out_name=out_name, max_width=max_width, colors=colors
        )
    except OpentoonzMCPError as exc:
        return _fail(exc)
    size = workspace_mod.human_size(gif.stat().st_size)
    return f"OK: {len(result.frames)} frames @ {fps}fps -> {gif} ({_png_size(gif)}, {size})"


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
        with workspace_mod.lock(ctx, workspace):
            result = bridge.run_script(ctx, ws.root, code, timeout=timeout)
    except OpentoonzMCPError as exc:
        return _fail(exc)
    return result.summary()


def main() -> None:
    """Console entry point."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
