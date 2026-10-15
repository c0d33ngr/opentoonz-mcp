"""End-to-end tests. Require a real OpenToonz runtime: run with ``pytest -m e2e``."""

from __future__ import annotations

import pytest
from PIL import Image

from opentoonz_mcp import bridge, draw, scenes
from opentoonz_mcp import render as R
from opentoonz_mcp import workspace as W

pytestmark = pytest.mark.e2e

HD = (1920, 1080)


def _draw_ball(ws, name="ball", n=3, color="#ff6b6b", size=HD):
    """Draw a moving ball on a dark background, at the scene's size."""
    width, height = size
    frames = []
    for i in range(n):
        cx, cy = width // 2, height // 2
        ops = [
            {"op": "rect", "xy": [0, 0, width, height], "fill": "#101828"},
            {"op": "ellipse", "box": [cx - 100, cy - 200 + i * 150, cx + 100, cy + i * 150], "fill": color},
        ]
        path = ws.drawings / f"{name}.{i + 1:04d}.png"
        draw.draw_frame(path, ops, width=width, height=height)
        frames.append(str(path))
    return frames


def _pixels(path):
    with Image.open(path) as img:
        return list(img.convert("RGBA").getdata())


def test_pipeline_to_video(live_context):
    ctx = live_context
    ws, created = W.create(ctx, "e2e")
    assert created

    frames = _draw_ball(ws)
    imported = scenes.import_level(ctx, "e2e", "ball", frames, "main")
    assert imported.result.ok, imported.result.summary()
    assert len(imported.copied) == 3
    assert imported.reused is False
    assert imported.frame_count == 3

    info = scenes.scene_info(ctx, "e2e", "main")
    assert info.frame_count == 3
    assert len(info.levels) == 1
    assert len(info.cells) == 3
    assert info.cells_truncated is False

    frame = R.render_frame(ctx, "e2e", "main", frame=1)
    assert frame.frames, frame.log
    with Image.open(frame.frames[0]) as img:
        assert img.size == HD
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


def test_reimport_reuses_the_level(live_context):
    """OpenToonz errors on a duplicate level name, so a re-import must reuse it."""
    ctx = live_context
    ws, _ = W.create(ctx, "reuse")
    first = scenes.import_level(ctx, "reuse", "ball", _draw_ball(ws), "main")
    assert first.result.ok and first.reused is False
    second = scenes.import_level(ctx, "reuse", "ball", _draw_ball(ws), "main")
    assert second.result.ok and second.reused is True
    info = scenes.scene_info(ctx, "reuse", "main")
    assert [level.name for level in info.levels] == ["ball"]
    assert info.frame_count == 3


def test_reimport_clears_previous_drawings(live_context):
    """A shorter re-import must not leave orphaned frames behind."""
    ctx = live_context
    ws, _ = W.create(ctx, "shrink")
    scenes.import_level(ctx, "shrink", "ball", _draw_ball(ws, n=5), "main")
    assert (ws.drawings / "ball.0005.png").is_file()
    scenes.import_level(ctx, "shrink", "ball", _draw_ball(ws, n=3), "main")
    assert not (ws.drawings / "ball.0004.png").exists()
    assert not (ws.drawings / "ball.0005.png").exists()
    info = scenes.scene_info(ctx, "shrink", "main")
    assert info.levels[0].frame_count == "3"


def test_stale_frames_cleared(live_context):
    ctx = live_context
    ws, _ = W.create(ctx, "stale")
    frames = _draw_ball(ws)
    scenes.import_level(ctx, "stale", "ball", frames, "main")
    full = R.render_frames(ctx, "stale", "main", out_name="seq")
    assert len(full.frames) == 3
    one = R.render_frames(ctx, "stale", "main", out_name="seq", frame=1)
    assert len(one.frames) == 1


def test_scene_settings_resize_the_render(live_context):
    """Camera resolution is patched into the .tnz and must survive a scene save."""
    ctx = live_context
    ws, _ = W.create(ctx, "resize")
    settings = scenes.scene_new(ctx, "resize", "small", width=640, height=360)
    assert (settings.width, settings.height) == (640, 360)
    assert settings.camera_size == "5.333333 3"

    frames = _draw_ball(ws, size=(640, 360))
    imported = scenes.import_level(ctx, "resize", "ball", frames, "small")
    assert imported.result.ok

    rendered = R.render_frames(ctx, "resize", "small", out_name="small")
    assert rendered.frames, rendered.log
    with Image.open(rendered.frames[0]) as img:
        assert img.size == (640, 360)
        # Art drawn at the scene's size must fill the frame, not float in it.
        rgba = img.convert("RGBA")
        assert rgba.getchannel("A").getbbox() == (0, 0, 640, 360)
        assert rgba.getpixel((320, 180))[3] == 255


def test_scene_settings_can_change_after_import(live_context):
    ctx = live_context
    ws, _ = W.create(ctx, "late")
    scenes.import_level(ctx, "late", "ball", _draw_ball(ws), "main")
    changed = scenes.set_scene_settings(ctx, "late", "main", width=480, height=270)
    assert "cameraRes=480x270" in changed.changed
    assert changed.camera_size == "4 2.25"
    rendered = R.render_frames(ctx, "late", "main", out_name="late")
    assert rendered.frames
    with Image.open(rendered.frames[0]) as img:
        assert img.size == (480, 270)
        # 1920x1080 art renders 1:1, so a 480x270 frame shows its centre.
        assert img.convert("RGBA").getchannel("A").getbbox() == (0, 0, 480, 270)


def test_exposure_holds_drawings(live_context):
    """Holding on 2s: each drawing repeats, and nothing renders empty."""
    ctx = live_context
    ws, _ = W.create(ctx, "hold")
    scenes.import_level(ctx, "hold", "ball", _draw_ball(ws), "main")

    result, placements = scenes.set_exposure(ctx, "hold", "main", "ball", [2])
    assert result.ok, result.summary()
    assert placements == [(0, 1), (1, 1), (2, 2), (3, 2), (4, 3), (5, 3)]

    info = scenes.scene_info(ctx, "hold", "main")
    assert info.frame_count == 6

    rendered = R.render_frames(ctx, "hold", "main", out_name="hold")
    assert len(rendered.frames) == 6

    first, second, third = (_pixels(p) for p in rendered.frames[:3])
    assert first == second  # drawing 1 held for two frames
    assert first != third  # drawing 2 is different
    assert any(pixel[3] for pixel in second)  # held rows are not blank


def test_exposure_varying_holds(live_context):
    ctx = live_context
    ws, _ = W.create(ctx, "vary")
    scenes.import_level(ctx, "vary", "ball", _draw_ball(ws), "main")
    _, placements = scenes.set_exposure(ctx, "vary", "main", "ball", [3, 1, 2])
    assert placements == [(0, 1), (1, 1), (2, 1), (3, 2), (4, 3), (5, 3)]
    info = scenes.scene_info(ctx, "vary", "main")
    assert info.frame_count == 6


def test_exposure_requires_an_imported_level(live_context):
    ctx = live_context
    W.create(ctx, "empty")
    scenes.scene_new(ctx, "empty", "main")
    with pytest.raises(Exception, match="not in scene"):
        scenes.set_exposure(ctx, "empty", "main", "ghost", [2])


def test_image_op_composites_into_a_rendered_level(live_context):
    """The drawing layer's image op must survive the trip through OpenToonz."""
    ctx = live_context
    ws, _ = W.create(ctx, "compose")
    art = ws.drawings / "art.png"
    draw.draw_frame(
        art,
        [{"op": "rect", "xy": [0, 0, 400, 400], "fill": "#ff0000"}],
        width=400,
        height=400,
        background=None,
    )
    frame = ws.drawings / "shot.0001.png"
    draw.draw_frame(
        frame,
        [
            {"op": "rect", "xy": [0, 0, 1920, 1080], "fill": "#101828"},
            {"op": "image", "path": str(art), "xy": [200, 200], "size": [400, 400]},
        ],
    )
    scenes.import_level(ctx, "compose", "shot", [str(frame)], "main")
    info = scenes.scene_info(ctx, "compose", "main")
    assert info.levels[0].frame_count == "1"

    # The imported drawing is a copy, so re-check the copy rather than the source.
    with Image.open(ws.drawings / "shot.0001.png") as img:
        assert img.getpixel((400, 400))[:3] == (255, 0, 0)
        assert img.getpixel((100, 100))[:3] == (16, 24, 40)

    rendered = R.render_frames(ctx, "compose", "main", out_name="compose")
    assert rendered.frames, rendered.log
    with Image.open(rendered.frames[0]) as img:
        assert img.size == HD
        assert img.getchannel("A").getbbox() is not None


def test_run_script_escape_hatch(live_context):
    ctx = live_context
    ws, _ = W.create(ctx, "script")
    result = bridge.run_script(ctx, ws.root, 'print("ESCAPE-HATCH");\nprint("__OTMCP_OK__");\n')
    assert result.ok
    assert "ESCAPE-HATCH" in result.stdout
