#!/usr/bin/env python3
"""Animate the camera with easing, and render it to a GIF.

This is the camera half of the story. ``demo_reel.py`` moves *levels*; this moves
the *camera* over a static scene, which is the one thing OpenToonz's scripting API
cannot reach at all — it is written into the scene file as the camera stage
object's channels (see ``scripts/probe_camera.py``).

The push-in is eased: ``"ease": True`` on the first keyframe makes the camera
glide out of the wide shot and settle into the close-up, instead of moving at a
constant rate. Ease is per segment, so it belongs on the keyframe the segment
*starts* from.

It also produces ``docs/camera.gif``, the animation embedded in the README.

Usage:
    OPENTOONZ_RUNTIME=/path/to/squashfs-root python examples/camera_move.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Allow running straight from a checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opentoonz_mcp import draw, scenes  # noqa: E402
from opentoonz_mcp import render as render_mod  # noqa: E402
from opentoonz_mcp import workspace as workspace_mod  # noqa: E402
from opentoonz_mcp.context import get_context  # noqa: E402

WORKSPACE = "camera-move"
SCENE = "push-in"
WIDTH, HEIGHT = 960, 540
FRAMES = 24
FPS = 12
GIF_WIDTH = 640

#: The camera starts wide and eases into a close-up centred near x=680.
START = {"frame": 1, "x": 0, "y": 0, "zoom": 1.0, "ease": True}
END = {"frame": FRAMES, "x": 200, "y": 0, "zoom": 1.6}


def blend(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> list[int]:
    """Linear colour interpolation, as an [r, g, b] the draw layer accepts."""
    return [round(a + (b - a) * t) for a, b in zip(start, end, strict=True)]


def world_frame() -> list[dict]:
    """One static frame of 'world' for the camera to move over.

    A wide backdrop with evenly spaced markers, so the push-in is easy to read:
    the markers rush past during the fast middle of the move and crawl at its
    ends, which is exactly what easing looks like.
    """
    ops: list[dict] = []
    bands = 40
    for band in range(bands):
        top = HEIGHT * band / bands
        bottom = HEIGHT * (band + 1) / bands
        ops.append(
            {
                "op": "rect",
                "xy": [0, top, WIDTH, bottom + 1],
                "fill": blend((0x0B, 0x16, 0x28), (0x2F, 0x56, 0x7E), band / (bands - 1)),
            }
        )
    ops += [
        {"op": "ellipse", "box": [720, 60, 850, 190], "fill": "#ffd479"},
        {"op": "polygon", "points": [[0, 400], [260, 300], [520, 400]], "fill": "#16283d"},
        {"op": "polygon", "points": [[380, 400], [660, 280], [960, 400]], "fill": "#122033"},
        {"op": "rect", "xy": [0, HEIGHT - 110, WIDTH, HEIGHT], "fill": "#0e1a2b"},
    ]
    for index, x in enumerate(range(120, WIDTH, 200)):
        pole_top = HEIGHT - 240
        ops += [
            {"op": "rect", "xy": [x - 5, pole_top, x + 5, HEIGHT - 110], "fill": "#24344c"},
            {"op": "ellipse", "box": [x - 34, pole_top - 68, x + 34, pole_top], "fill": "#ff6b6b"},
            {"op": "text", "xy": [x - 9, pole_top - 44], "text": str(index + 1), "fill": "#2a1215", "size": 26},
        ]
    # The close-up settles here, so this is what the move ends on.
    ops += [
        {"op": "rect", "xy": [560, 96, 900, 176], "fill": [0x0B, 0x16, 0x28, 0xB0]},
        {"op": "line", "xy": [560, 176, 900, 176], "fill": "#ff6b6b", "width": 4},
        {"op": "text", "xy": [580, 116], "text": "opentoonz-mcp", "fill": "#e8eef7", "size": 40},
    ]
    return ops


def main() -> int:
    ctx = get_context()
    print("runtime:", ctx.runtime.version or "OpenToonz (unknown version)")

    ws, _ = workspace_mod.create(ctx, WORKSPACE)
    scenes.scene_new(ctx, WORKSPACE, SCENE, width=WIDTH, height=HEIGHT)
    print(f"scene {WIDTH}x{HEIGHT}")

    # One static drawing, held for the whole shot: all the motion is the camera.
    draw.draw_frame(ws.drawings / "world.0001.png", world_frame(), width=WIDTH, height=HEIGHT)
    scenes.import_level(ctx, WORKSPACE, "world", [str(ws.drawings / "world.0001.png")], SCENE)
    scenes.set_exposure(ctx, WORKSPACE, SCENE, "world", [FRAMES])

    moved = scenes.camera_move(ctx, WORKSPACE, SCENE, [START, END])
    print(
        f"camera: {moved.first_frame}-{moved.last_frame}, channels {', '.join(moved.channels)}, "
        f"{moved.eased_segments} eased segment(s)"
    )

    gif, rendered = render_mod.render_gif(ctx, WORKSPACE, SCENE, fps=FPS, out_name=SCENE, max_width=GIF_WIDTH)
    print(f"rendered {len(rendered.frames)} frames")

    destination = Path("docs/camera.gif")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(gif, destination)
    print(f"gif:   {destination.resolve()} ({destination.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
