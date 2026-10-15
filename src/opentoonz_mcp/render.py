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

from . import bridge
from . import workspace as workspace_mod
from .context import Context
from .errors import RenderError

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


def _stem(out_name: str, default: str) -> str:
    return (out_name.strip().rstrip("_") or default) + "_"


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


def render_frame(
    context: Context,
    workspace: str,
    scene: str,
    frame: int = 1,
    out_name: str = "look",
) -> RenderResult:
    """Render a single frame — the agent's "look" at its work."""
    return render_frames(context, workspace, scene, out_name=out_name, frame=frame)


def render_video(
    context: Context,
    workspace: str,
    scene: str,
    fps: int = 24,
    out_name: str = "video",
) -> tuple[Path, RenderResult]:
    """Render frames and mux them into an MP4 with ffmpeg."""
    ws = workspace_mod.require(context, workspace)
    base = out_name.strip().rstrip("_") or "video"
    result = render_frames(context, workspace, scene, out_name=base)
    if not result.frames:
        raise RenderError(f"tcomposer produced no frames (exit={result.exit_code}).\n{result.log}")
    video = ws.render / f"{base}.mp4"
    pattern = str(ws.render / f"{_stem(base, 'video')}%04d.png")
    cmd = [
        context.settings.ffmpeg,
        "-y",
        "-framerate",
        str(int(fps)),
        "-i",
        pattern,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(video),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=context.settings.render_timeout, errors="replace"
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ffmpeg timed out after {context.settings.render_timeout}s") from exc
    if proc.returncode != 0 or not video.exists():
        raise RenderError(f"ffmpeg failed (exit={proc.returncode}).\n{proc.stderr[-1500:]}")
    return video, result
