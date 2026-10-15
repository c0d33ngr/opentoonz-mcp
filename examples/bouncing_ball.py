#!/usr/bin/env python3
"""Draw a bouncing ball, import it as a level, and render an MP4 — end to end.

Usage:
    OPENTOONZ_RUNTIME=/path/to/squashfs-root python examples/bouncing_ball.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Allow running straight from a checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opentoonz_mcp import draw, scenes  # noqa: E402
from opentoonz_mcp import render as render_mod  # noqa: E402
from opentoonz_mcp import workspace as workspace_mod  # noqa: E402
from opentoonz_mcp.context import get_context  # noqa: E402


def main() -> int:
    ctx = get_context()
    print("runtime:", ctx.runtime.version or "OpenToonz (unknown version)")

    ws, _ = workspace_mod.create(ctx, "bouncing-ball")
    width, height = draw.DEFAULT_WIDTH, draw.DEFAULT_HEIGHT
    count = 24

    frames = []
    for i in range(count):
        t = i / (count - 1)
        y = 200 + (height - 620) * abs(math.sin(t * math.pi * 2))
        ops = [
            {"op": "rect", "xy": [0, 0, width, height], "fill": "#101828"},
            {"op": "rect", "xy": [0, height - 120, width, height], "fill": "#1c2436"},
            {"op": "ellipse", "box": [width / 2 - 90, y - 90, width / 2 + 90, y + 90], "fill": "#ff6b6b"},
        ]
        path = ws.drawings / f"ball.{i + 1:04d}.png"
        draw.draw_frame(path, ops)
        frames.append(str(path))
    print(f"drew {len(frames)} frames")

    result, copied = scenes.import_level(ctx, "bouncing-ball", "ball", frames, "main")
    print(f"imported {len(copied)} frames (ok={result.ok})")

    look = render_mod.render_frame(ctx, "bouncing-ball", "main", frame=1)
    print("look:", look.frames[0] if look.frames else "FAILED")

    video, rendered = render_mod.render_video(ctx, "bouncing-ball", "main", fps=12, out_name="bouncing-ball")
    print(f"video: {video} ({len(rendered.frames)} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
