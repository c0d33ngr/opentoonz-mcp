#!/usr/bin/env python3
"""Build a multi-level scene, render it with OpenToonz, and make a GIF.

Unlike ``bouncing_ball.py`` (one level, one call), this shows the composition
model the tool is really for: three separately drawn levels — background, ball,
title — stacked on the xsheet and composited by OpenToonz's own renderer, with
exposure holds so the static levels only carry one drawing.

It also produces ``docs/demo.gif``, the animation embedded in the README.

Usage:
    OPENTOONZ_RUNTIME=/path/to/squashfs-root python examples/demo_reel.py
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

# Allow running straight from a checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opentoonz_mcp import draw, scenes  # noqa: E402
from opentoonz_mcp import render as render_mod  # noqa: E402
from opentoonz_mcp import workspace as workspace_mod  # noqa: E402
from opentoonz_mcp.context import get_context  # noqa: E402

WORKSPACE = "demo-reel"
SCENE = "reel"
WIDTH, HEIGHT = 1280, 720
FRAMES = 24
FPS = 12
GIF_WIDTH = 640


def blend(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> list[int]:
    """Linear colour interpolation, as an [r, g, b] the draw layer accepts."""
    return [round(a + (b - a) * t) for a, b in zip(start, end, strict=True)]


def sky_frame() -> list[dict]:
    """A static background: gradient sky, sun, and two hills."""
    ops: list[dict] = []
    bands = 48
    for band in range(bands):
        top = HEIGHT * band / bands
        bottom = HEIGHT * (band + 1) / bands
        ops.append(
            {
                "op": "rect",
                "xy": [0, top, WIDTH, bottom + 1],
                "fill": blend((0x0B, 0x16, 0x28), (0x35, 0x5E, 0x86), band / (bands - 1)),
            }
        )
    ops += [
        {"op": "ellipse", "box": [WIDTH - 300, 70, WIDTH - 170, 200], "fill": "#ffd479"},
        {"op": "ellipse", "box": [430, 120, 660, 176], "fill": "#2a4160"},
        {"op": "ellipse", "box": [560, 96, 700, 150], "fill": "#2a4160"},
        {"op": "ellipse", "box": [820, 168, 1060, 224], "fill": "#233752"},
        {"op": "ellipse", "box": [980, 144, 1100, 196], "fill": "#233752"},
        {"op": "polygon", "points": [[0, 520], [WIDTH * 0.35, 430], [WIDTH * 0.7, 520]], "fill": "#16283d"},
        {"op": "polygon", "points": [[WIDTH * 0.45, 520], [WIDTH * 0.8, 400], [WIDTH, 520]], "fill": "#122033"},
        {"op": "rect", "xy": [0, HEIGHT - 120, WIDTH, HEIGHT], "fill": "#0e1a2b"},
    ]
    return ops


def ball_frame(index: int) -> list[dict]:
    """One frame of a bouncing, squashing ball — this level animates on 1s."""
    phase = (index / FRAMES * 2) % 1.0
    lift = abs(math.sin(phase * math.pi)) ** 0.8
    ground = HEIGHT - 120
    radius = 52
    centre_x = WIDTH / 2 + math.sin(index / FRAMES * math.tau) * 130
    centre_y = ground - radius - lift * (HEIGHT * 0.42)
    squash = 1.0 + 0.30 * max(0.0, 1.0 - lift * 6)
    radius_x, radius_y = radius * squash, radius / squash

    shadow_width = 70 - 28 * lift
    return [
        {
            "op": "ellipse",
            "box": [centre_x - shadow_width, ground - 12, centre_x + shadow_width, ground + 12],
            "fill": "#0a1220",
        },
        {
            "op": "ellipse",
            "box": [centre_x - radius_x, centre_y - radius_y, centre_x + radius_x, centre_y + radius_y],
            "fill": "#ff6b6b",
        },
        {
            "op": "ellipse",
            "box": [
                centre_x - radius_x * 0.62,
                centre_y - radius_y * 0.72,
                centre_x - radius_x * 0.06,
                centre_y - radius_y * 0.16,
            ],
            "fill": "#ffc9c9",
        },
    ]


def title_frame() -> list[dict]:
    """A static title card, drawn with a translucent plate behind the text."""
    return [
        {"op": "rect", "xy": [56, 44, 470, 128], "fill": [0x0B, 0x16, 0x28, 0xA8]},
        {"op": "line", "xy": [56, 128, 470, 128], "fill": "#ff6b6b", "width": 4},
        {"op": "text", "xy": [76, 66], "text": "opentoonz-mcp", "fill": "#e8eef7", "size": 40},
        {"op": "text", "xy": [78, 138], "text": "drawn, timed and rendered headlessly", "fill": "#8fa6c4", "size": 22},
    ]


def make_gif(ffmpeg: str, frames_glob: Path, gif_path: Path) -> Path:
    """Turn rendered PNG frames into a palette-optimised, looping GIF."""
    filters = (
        f"fps={FPS},scale={GIF_WIDTH}:-1:flags=lanczos,format=rgb24,split[a][b];[a]palettegen=[p];[b][p]paletteuse"
    )
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        str(FPS),
        "-i",
        str(frames_glob),
        "-vf",
        filters,
        "-loop",
        "0",
        str(gif_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, errors="replace")
    if proc.returncode != 0 or not gif_path.is_file():
        raise RuntimeError(f"ffmpeg GIF failed (exit={proc.returncode}):\n{proc.stderr[-800:]}")
    return gif_path


def main() -> int:
    ctx = get_context()
    print("runtime:", ctx.runtime.version or "OpenToonz (unknown version)")

    ws, _ = workspace_mod.create(ctx, WORKSPACE)
    scenes.scene_new(ctx, WORKSPACE, SCENE, width=WIDTH, height=HEIGHT)
    print(f"scene {WIDTH}x{HEIGHT}")

    # Each level is drawn separately, at the scene's size.
    draw.draw_frame(ws.drawings / "sky.0001.png", sky_frame(), width=WIDTH, height=HEIGHT)
    draw.draw_frame(ws.drawings / "title.0001.png", title_frame(), width=WIDTH, height=HEIGHT, background=None)
    ball_paths = []
    for index in range(FRAMES):
        path = ws.drawings / f"ball.{index + 1:04d}.png"
        draw.draw_frame(path, ball_frame(index), width=WIDTH, height=HEIGHT, background=None)
        ball_paths.append(str(path))
    print(f"drew 1 sky + 1 title + {len(ball_paths)} ball frames")

    # Stack them on the xsheet, one column each.
    scenes.import_level(ctx, WORKSPACE, "sky", [str(ws.drawings / "sky.0001.png")], SCENE, column=0)
    scenes.import_level(ctx, WORKSPACE, "ball", ball_paths, SCENE, column=1)
    scenes.import_level(ctx, WORKSPACE, "title", [str(ws.drawings / "title.0001.png")], SCENE, column=2)

    # The static levels carry one drawing each — hold them for the whole shot.
    scenes.set_exposure(ctx, WORKSPACE, SCENE, "sky", [FRAMES], column=0)
    scenes.set_exposure(ctx, WORKSPACE, SCENE, "title", [FRAMES], column=2)

    info = scenes.scene_info(ctx, WORKSPACE, SCENE)
    names = ", ".join(level.name for level in info.levels)
    print(f"scene: {info.frame_count} frames, {len(info.levels)} levels ({names})")

    video, rendered = render_mod.render_video(ctx, WORKSPACE, SCENE, fps=FPS, out_name=SCENE)
    print(f"video: {video} ({len(rendered.frames)} frames)")

    gif = make_gif(ctx.settings.ffmpeg, ws.render / f"{SCENE}_%04d.png", Path("docs/demo.gif"))
    size_kb = gif.stat().st_size / 1024
    print(f"gif:   {gif.resolve()} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
