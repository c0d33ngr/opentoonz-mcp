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

#: tcomposer writes ``<prefix>NNNN.png``.
_FRAME_RE = re.compile(r"\d+\.png$")


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
    for path in directory.glob(f"{stem}*.png"):
        if _FRAME_RE.search(path.name):
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
    frames = sorted(p for p in out_dir.glob(f"{stem}*.png") if _FRAME_RE.search(p.name))
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


def _run_ffmpeg(context: Context, cmd: list[str], output: Path, label: str) -> None:
    """Run ffmpeg and translate its failure modes into RenderError."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=context.settings.render_timeout, errors="replace"
        )
    except FileNotFoundError as exc:
        raise RenderError(f"ffmpeg not found: {context.settings.ffmpeg} — install ffmpeg to write {label}.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ffmpeg timed out after {context.settings.render_timeout}s") from exc
    if proc.returncode != 0 or not output.exists():
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
) -> tuple[Path, RenderResult]:
    """Render frames and mux them into an MP4 with ffmpeg.

    ``audio`` adds a soundtrack from an external file. OpenToonz's own audio
    columns are unreachable from the scripting API, so audio is always supplied
    from outside; it is encoded as AAC and trimmed to the video (``-shortest``).
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
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)]
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
