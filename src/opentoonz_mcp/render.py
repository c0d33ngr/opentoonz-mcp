"""Render scenes with the official headless ``tcomposer``, then mux with ffmpeg.

``Renderer.renderFrame`` deadlocks in OpenToonz CLI mode, so rendering always
goes through ``tcomposer`` — which needs an absolute scene path, a ``.png``
output prefix, and ``-TOONZROOT`` to stay self-contained.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import bridge
from . import workspace as workspace_mod
from .context import Context
from .errors import RenderError, WorkspaceError
from .scenes import validate_level_name

#: A single extract writes one RGBA PNG per frame, so a long clip could fill a
#: disk in one call. ffmpeg is told to stop after this many frames; the tool
#: says so when the cap is hit.
MAX_EXTRACT_FRAMES = 5000


def _frames_for(directory: Path, stem: str) -> list[Path]:
    """The frames belonging to exactly this stem, sorted.

    ``tcomposer`` writes ``<stem><n>.png``, so the digits follow the stem
    immediately. A prefix match is not enough: ``a_`` would also match
    ``a_b_0001.png``, so a render named ``a`` would count — and delete — a render
    named ``a_b``. Batch renders naming scenes ``intro``/``intro_v2`` hit this.
    """
    pattern = re.compile(rf"^{re.escape(stem)}\d+\.png$")
    return sorted(p for p in directory.glob(f"{stem}*.png") if pattern.match(p.name))


@dataclass
class RenderResult:
    ok: bool
    frames: list[Path]
    log: str
    exit_code: int | None
    timed_out: bool
    duration: float
    #: Original pixel size, set only when a preview was downscaled in place.
    downscaled_from: tuple[int, int] | None = None


def _stem(out_name: str, default: str) -> str:
    """Validate an output stem and append the frame-number separator.

    ``'render'`` becomes ``'render_'``, so ``tcomposer`` writes
    ``render_0001.png``. The name is validated here because it also forms the
    ffmpeg glob used to clear and collect frames — an unvalidated stem could
    reach outside the render directory.
    """
    name = (out_name or "").strip().rstrip("_") or default
    try:
        return workspace_mod.safe_out_name(name) + "_"
    except WorkspaceError as exc:
        raise RenderError(str(exc)) from exc


def _clear_stale(directory: Path, stem: str) -> None:
    """Delete frames from a previous render so counts and videos stay honest."""
    if not directory.is_dir():
        return
    for path in _frames_for(directory, stem):
        path.unlink(missing_ok=True)


def _run_tcomposer(
    context: Context,
    scene_path: Path,
    out_prefix: Path,
    *,
    frame: int | None = None,
    frame_range: tuple[int, int] | None = None,
) -> RenderResult:
    context.prepare()
    out_dir = out_prefix.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(context.runtime.tcomposer_bin),
        "-TOONZROOT",
        str(context.stuff_root),
        str(scene_path),
        "-o",
        str(out_prefix),
    ]
    if frame is not None:
        cmd += ["-frame", str(int(frame))]
    elif frame_range is not None:
        cmd += ["-range", str(int(frame_range[0])), str(int(frame_range[1]))]

    started = time.monotonic()
    timed_out = False
    out = err = ""
    code: int | None = None
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(scene_path.parent),
            env=bridge.build_env(context),
            capture_output=True,
            text=True,
            timeout=context.settings.render_timeout,
            errors="replace",
        )
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except FileNotFoundError as exc:
        raise RenderError(
            f"tcomposer not found: {context.runtime.tcomposer_bin} — set OPENTOONZ_RUNTIME to an "
            "extracted OpenToonz AppImage directory."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out = bridge.as_text(exc.stdout)
        err = bridge.as_text(exc.stderr)

    duration = time.monotonic() - started
    stem = out_prefix.name[: -len(".png")] if out_prefix.name.endswith(".png") else out_prefix.name
    frames = _frames_for(out_dir, stem)
    return RenderResult(
        ok=bool(frames) and not timed_out,
        frames=frames,
        log=(out + err)[-4000:],
        exit_code=code,
        timed_out=timed_out,
        duration=duration,
    )


@workspace_mod.locked
def render_frames(
    context: Context,
    workspace: str,
    scene: str,
    out_name: str = "render",
    *,
    frame: int | None = None,
    frame_range: tuple[int, int] | None = None,
) -> RenderResult:
    """Render a saved scene to PNG frames under ``<workspace>/render``."""
    ws = workspace_mod.require(context, workspace)
    scene_path = ws.scene_path(scene)
    if not scene_path.is_file():
        raise RenderError(f"Scene not found: {scene_path}")
    stem = _stem(out_name, "render")
    _clear_stale(ws.render, stem)
    return _run_tcomposer(context, scene_path, ws.render / (stem + ".png"), frame=frame, frame_range=frame_range)


def _downscale(path: Path, max_width: int) -> tuple[int, int] | None:
    """Shrink a rendered PNG in place; return its original size if it changed.

    Only previews are shrunk: a full-resolution frame or a video frame is
    never touched, so the delivered render keeps the scene's resolution.
    """
    with Image.open(path) as img:
        if img.width <= max_width:
            return None
        original = img.size
        height = max(1, round(img.height * max_width / img.width))
        resized = img.convert("RGBA").resize((max_width, height), Image.LANCZOS)
    resized.save(path, format="PNG")
    return original


def render_frame(
    context: Context,
    workspace: str,
    scene: str,
    frame: int = 1,
    out_name: str = "look",
    *,
    max_width: int | None = None,
) -> RenderResult:
    """Render a single frame — the agent's "look" at its work.

    ``max_width`` downscales the returned PNG in place, so looking at a large
    scene costs fewer image tokens. The file *is* the preview; the scene's own
    resolution is untouched, and render/render_video frames are never shrunk.
    """
    result = render_frames(context, workspace, scene, out_name=out_name, frame=frame)
    if max_width is None or not result.frames:
        return result
    width = int(max_width)
    if width < 1:
        raise RenderError(f"max_width must be at least 1, got {max_width!r}")
    result.downscaled_from = _downscale(result.frames[0], width)
    return result


def _run_ffmpeg(context: Context, cmd: list[str], output: Path | None, label: str) -> None:
    """Run ffmpeg and translate its failure modes into RenderError.

    ``output`` is the single file to expect; pass ``None`` for a command that
    writes a numbered sequence instead, and check the frames yourself.
    """
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=context.settings.render_timeout, errors="replace"
        )
    except FileNotFoundError as exc:
        raise RenderError(f"ffmpeg not found: {context.settings.ffmpeg} — install ffmpeg to write {label}.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ffmpeg timed out after {context.settings.render_timeout}s") from exc
    if proc.returncode != 0 or (output is not None and not output.exists()):
        raise RenderError(f"ffmpeg failed (exit={proc.returncode}).\n{proc.stderr[-1500:]}")


@workspace_mod.locked
def render_video(
    context: Context,
    workspace: str,
    scene: str,
    fps: int = 24,
    out_name: str = "video",
    *,
    audio: str | None = None,
    crf: int | None = None,
    scale: float | None = None,
) -> tuple[Path, RenderResult]:
    """Render frames and mux them into an MP4 with ffmpeg.

    ``audio`` adds a soundtrack from an external file. OpenToonz's own audio
    columns are unreachable from the scripting API, so audio is always supplied
    from outside; it is encoded as AAC and trimmed to the video (``-shortest``).

    ``crf`` (0-51, lower is better) trades quality for size, and ``scale`` (a
    positive factor, e.g. ``0.5``) resizes the video.
    """
    ws = workspace_mod.require(context, workspace)
    stem = _stem(out_name, "video")
    base = stem.rstrip("_")
    track: Path | None = None
    if audio is not None:
        # Validate before rendering: a missing track should not cost a render.
        track = Path(audio).expanduser()
        if not track.is_file():
            raise RenderError(f"Audio file not found: {track}")
    if crf is not None and not 0 <= int(crf) <= 51:
        raise RenderError(f"crf must be between 0 and 51, got {crf!r}")
    if scale is not None and float(scale) <= 0:
        raise RenderError(f"scale must be greater than 0, got {scale!r}")
    result = render_frames(context, workspace, scene, out_name=base)
    if not result.frames:
        raise RenderError(f"tcomposer produced no frames (exit={result.exit_code}).\n{result.log}")
    video = ws.render / f"{base}.mp4"
    pattern = str(ws.render / f"{stem}%04d.png")
    cmd = [
        context.settings.ffmpeg,
        "-y",
        "-framerate",
        str(int(fps)),
        "-i",
        pattern,
    ]
    if track is not None:
        cmd += ["-i", str(track), "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if crf is not None:
        cmd += ["-crf", str(int(crf))]
    # Always keep both dimensions even: libx264 + yuv420p rejects odd ones, and a
    # scene's camera can be odd-sized. When a scale factor is given it is applied
    # first, so the even rounding lands on the scaled size.
    if scale is None:
        cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    else:
        factor = float(scale)
        cmd += ["-vf", f"scale=trunc(iw*{factor}/2)*2:trunc(ih*{factor}/2)*2"]
    cmd += [str(video)]
    _run_ffmpeg(context, cmd, video, "video")
    return video, result


@workspace_mod.locked
def render_gif(
    context: Context,
    workspace: str,
    scene: str,
    fps: int = 12,
    out_name: str = "reel",
    *,
    max_width: int | None = None,
    colors: int = 256,
) -> tuple[Path, RenderResult]:
    """Render frames and turn them into a looping GIF with ffmpeg.

    A GIF is the cheap way to share a finished move: one file, no player, and it
    loops. Frames come from the same ``tcomposer`` pass as :func:`render_video`;
    ffmpeg builds a per-clip palette (``palettegen``/``paletteuse``) so gradients
    do not band the way a fixed web palette would.
    """
    ws = workspace_mod.require(context, workspace)
    stem = _stem(out_name, "reel")
    base = stem.rstrip("_")
    if not 2 <= int(colors) <= 256:
        raise RenderError(f"colors must be between 2 and 256, got {colors!r}")
    if int(fps) < 1:
        raise RenderError(f"fps must be at least 1, got {fps!r}")
    if max_width is not None and int(max_width) < 1:
        raise RenderError(f"max_width must be at least 1, got {max_width!r}")
    result = render_frames(context, workspace, scene, out_name=base)
    if not result.frames:
        raise RenderError(f"tcomposer produced no frames (exit={result.exit_code}).\n{result.log}")
    gif = ws.render / f"{base}.gif"
    pattern = str(ws.render / f"{stem}%04d.png")
    scale = "" if max_width is None else f"scale={int(max_width)}:-1:flags=lanczos,"
    chain = f"{scale}split[s0][s1];[s0]palettegen=max_colors={int(colors)}[p];[s1][p]paletteuse=dither=sierra2_4a"
    cmd = [
        context.settings.ffmpeg,
        "-y",
        "-framerate",
        str(int(fps)),
        "-i",
        pattern,
        "-filter_complex",
        chain,
        "-loop",
        "0",
        str(gif),
    ]
    _run_ffmpeg(context, cmd, gif, "GIF")
    return gif, result


@workspace_mod.locked
def extract_frames(
    context: Context,
    workspace: str,
    level_name: str,
    video: str,
    *,
    fps: float | None = None,
    start: float | None = None,
    end: float | None = None,
    max_width: int | None = None,
    max_frames: int = MAX_EXTRACT_FRAMES,
) -> list[Path]:
    """Extract a video's frames into ``drawings/`` as a level's drawings.

    The frames are named ``<level_name>.%04d.png``, exactly what
    ``opentoonz_import_images_as_level`` expects, so outside footage can join a
    scene as a level. ``fps`` resamples (default keeps the source rate),
    ``start``/``end`` are seconds, and ``max_width`` downscales so a large source
    does not fill the workspace. ``max_frames`` caps how many frames are written,
    so a long clip cannot fill the disk in one call.
    """
    ws = workspace_mod.require(context, workspace)
    validate_level_name(level_name)
    source = Path(video).expanduser()
    if not source.is_file():
        raise RenderError(f"Video not found: {source}")
    if fps is not None and float(fps) <= 0:
        raise RenderError(f"fps must be greater than 0, got {fps!r}")
    if max_width is not None and int(max_width) <= 0:
        raise RenderError(f"max_width must be greater than 0, got {max_width!r}")
    if int(max_frames) <= 0:
        raise RenderError(f"max_frames must be greater than 0, got {max_frames!r}")
    if start is not None and float(start) < 0:
        raise RenderError(f"start must not be negative, got {start!r}")
    if end is not None and float(end) < 0:
        raise RenderError(f"end must not be negative, got {end!r}")
    if start is not None and end is not None and float(end) <= float(start):
        raise RenderError(f"end must be after start, got start={start!r} end={end!r}")

    ws.drawings.mkdir(parents=True, exist_ok=True)
    # A shorter extract must not leave the previous run's drawings behind, or the
    # level would silently grow frames that no longer exist in the video.
    numbered = re.compile(rf"{re.escape(level_name)}\.\d+\.png$")
    for stale in ws.drawings.glob(f"{level_name}.*.png"):
        if numbered.match(stale.name):
            stale.unlink()

    filters = []
    if fps is not None:
        filters.append(f"fps={float(fps):g}")
    if max_width is not None:
        filters.append(f"scale={int(max_width)}:-2")
    pattern = str(ws.drawings / f"{level_name}.%04d.png")
    cmd = [context.settings.ffmpeg, "-y"]
    if start is not None:
        cmd += ["-ss", f"{float(start):g}"]
    if end is not None:
        cmd += ["-to", f"{float(end):g}"]
    cmd += ["-i", str(source)]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-frames:v", str(int(max_frames))]
    cmd += ["-pix_fmt", "rgba", pattern]
    _run_ffmpeg(context, cmd, None, "frames")

    frames = [path for path in sorted(ws.drawings.glob(f"{level_name}.*.png")) if numbered.match(path.name)]
    if not frames:
        raise RenderError(f"ffmpeg produced no frames from {source} — is it a readable video?")
    return frames
