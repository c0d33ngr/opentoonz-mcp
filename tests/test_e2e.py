"""End-to-end tests. Require a real OpenToonz runtime: run with ``pytest -m e2e``."""

from __future__ import annotations

import pytest
from PIL import Image

from opentoonz_mcp import bridge, draw, scenes
from opentoonz_mcp import render as R
from opentoonz_mcp import workspace as W

pytestmark = pytest.mark.e2e


def _draw_ball(ws, name="ball", n=3, color="#ff6b6b"):
    frames = []
    for i in range(n):
        ops = [
            {"op": "rect", "xy": [0, 0, 1920, 1080], "fill": "#101828"},
            {"op": "ellipse", "box": [860, 400 + i * 150, 1060, 600 + i * 150], "fill": color},
        ]
        path = ws.drawings / f"{name}.{i + 1:04d}.png"
        draw.draw_frame(path, ops)
        frames.append(str(path))
    return frames


def test_pipeline_to_video(live_context):
    ctx = live_context
    ws, created = W.create(ctx, "e2e")
    assert created

    frames = _draw_ball(ws)
    result, copied = scenes.import_level(ctx, "e2e", "ball", frames, "main")
    assert result.ok, result.summary()
    assert len(copied) == 3

    info = scenes.scene_info(ctx, "e2e", "main")
    assert info.frame_count == 3
    assert len(info.levels) == 1
    assert len(info.cells) == 3

    frame = R.render_frame(ctx, "e2e", "main", frame=1)
    assert frame.frames, frame.log
    with Image.open(frame.frames[0]) as img:
        assert img.size == (1920, 1080)
        assert img.mode == "RGBA"
        assert img.getchannel("A").getbbox() is not None

    video, rendered = R.render_video(ctx, "e2e", "main", fps=12, out_name="clip")
    assert video.is_file() and video.stat().st_size > 0
    assert len(rendered.frames) == 3


def test_multi_level_import_is_additive(live_context):
    ctx = live_context
    ws, _ = W.create(ctx, "multi")
    scenes.import_level(ctx, "multi", "ball", _draw_ball(ws, "ball"), "main", column=0)
    scenes.import_level(ctx, "multi", "bg", _draw_ball(ws, "bg", color="#4cd964"), "main", column=1)
    info = scenes.scene_info(ctx, "multi", "main")
    assert {level.name for level in info.levels} == {"ball", "bg"}
    assert {cell.column for cell in info.cells} == {0, 1}


def test_stale_frames_cleared(live_context):
    ctx = live_context
    ws, _ = W.create(ctx, "stale")
    frames = _draw_ball(ws)
    scenes.import_level(ctx, "stale", "ball", frames, "main")
    full = R.render_frames(ctx, "stale", "main", out_name="seq")
    assert len(full.frames) == 3
    one = R.render_frames(ctx, "stale", "main", out_name="seq", frame=1)
    assert len(one.frames) == 1


def test_run_script_escape_hatch(live_context):
    ctx = live_context
    ws, _ = W.create(ctx, "script")
    result = bridge.run_script(ctx, ws.root, 'print("ESCAPE-HATCH");\nprint("__OTMCP_OK__");\n')
    assert result.ok
    assert "ESCAPE-HATCH" in result.stdout
