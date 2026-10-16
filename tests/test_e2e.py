"""End-to-end tests. Require a real OpenToonz runtime: run with ``pytest -m e2e``."""

from __future__ import annotations

import subprocess

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


# -- camera moves -------------------------------------------------------------
def _camera_scene(ctx, name):
    """A 640x360 scene holding one 40x40 marker at (280,160), for 12 frames."""
    ws, _ = W.create(ctx, name)
    scenes.scene_new(ctx, name, "main", width=640, height=360)
    marker = ws.drawings / "marker.0001.png"
    draw.draw_frame(
        marker,
        [{"op": "rect", "xy": [280, 160, 320, 200], "fill": "#ff6b6b"}],
        width=640,
        height=360,
        background=None,
    )
    scenes.import_level(ctx, name, "marker", [str(marker)], "main")
    scenes.set_exposure(ctx, name, "main", "marker", [12])
    return ws


def _look(ctx, name, out_name, frame):
    rendered = R.render_frame(ctx, name, "main", frame=frame, out_name=out_name)
    assert rendered.frames, rendered.log
    with Image.open(rendered.frames[0]) as img:
        return img.convert("RGBA").getchannel("A").getbbox()


def _aperture(bbox):
    """Centre and size of an alpha bounding box, which scales are easier on."""
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2, (y0 + y1) / 2), (x1 - x0, y1 - y0)


def _close(actual, expected, tol=3):
    return all(abs(a - b) <= tol for a, b in zip(actual, expected, strict=True))


def test_camera_move_pans_the_render(live_context):
    """Panning the camera must move the artwork 1:1 in pixels (120 dpi)."""
    ctx = live_context
    _camera_scene(ctx, "cam")
    centre, size = _aperture(_look(ctx, "cam", "base", 1))
    assert _close(centre, (300, 180)) and _close(size, (40, 40))

    moved = scenes.camera_move(ctx, "cam", "main", [{"frame": 1, "x": 0}, {"frame": 12, "x": 120}])
    assert moved.channels == ["x"]
    # camera right -> artwork left by 120 px, unchanged in size
    centre, size = _aperture(_look(ctx, "cam", "pan", 12))
    assert _close(centre, (180, 180)) and _close(size, (40, 40))


def test_camera_move_ease_softens_the_motion(live_context):
    """An eased segment leaves its pose slowly; a linear one moves at a steady rate.

    Ease and linear agree at the midpoint, so this samples the first quarter of
    the move, where a full ease is clearly behind a linear ramp.
    """
    ctx = live_context
    _camera_scene(ctx, "camease")

    linear = scenes.camera_move(ctx, "camease", "main", [{"frame": 1, "x": 0}, {"frame": 12, "x": 120}])
    assert linear.eased_segments == 0
    centre, _ = _aperture(_look(ctx, "camease", "linear", 4))
    # 3 of 11 rows is 0.273 of the 120 px pan
    assert _close(centre, (267, 180))

    eased = scenes.camera_move(ctx, "camease", "main", [{"frame": 1, "x": 0, "ease": True}, {"frame": 12, "x": 120}])
    assert eased.eased_segments == 1
    centre, _ = _aperture(_look(ctx, "camease", "eased", 4))
    # getEaseInOutValue with a full ease over 11 rows is x^2/60.5 at row 3, i.e.
    # 0.149 of the pan, so the artwork has barely left the pose
    assert _close(centre, (282, 180))


def test_camera_move_zooms_about_the_frame_centre(live_context):
    """Zoom is a magnification: 2 makes the artwork twice as large."""
    ctx = live_context
    _camera_scene(ctx, "camzoom")
    scenes.camera_move(ctx, "camzoom", "main", [{"frame": 1, "zoom": 1}, {"frame": 12, "zoom": 2}])
    centre, size = _aperture(_look(ctx, "camzoom", "zoom", 12))
    # twice as large about the frame centre (320,180): the marker's own centre
    # (300,180) is carried out to (280,180), and its 40 px width becomes 80.
    assert _close(centre, (280, 180), tol=4) and _close(size, (80, 80), tol=6)


def test_camera_move_second_call_replaces_the_first(live_context):
    """Otherwise a pan would silently survive a later zoom (verified pitfall)."""
    ctx = live_context
    _camera_scene(ctx, "camswap")
    scenes.camera_move(ctx, "camswap", "main", [{"frame": 1, "x": 0}, {"frame": 12, "x": 120}])
    scenes.camera_move(ctx, "camswap", "main", [{"frame": 1, "zoom": 1}, {"frame": 12, "zoom": 2}])
    assert "<x>" not in (W.require(ctx, "camswap").scene_path("main")).read_text(encoding="utf-8")
    # the pan is gone, so the marker sits where a pure zoom puts it
    centre, size = _aperture(_look(ctx, "camswap", "swap", 12))
    assert _close(centre, (280, 180), tol=4) and _close(size, (80, 80), tol=6)


def test_camera_move_survives_an_opentoonz_round_trip(live_context):
    """A JS load/save — which every level import performs — must keep the move."""
    ctx = live_context
    ws = _camera_scene(ctx, "camkeep")
    scenes.camera_move(
        ctx,
        "camkeep",
        "main",
        [{"frame": 1, "x": 0, "zoom": 1, "rotation": 0}, {"frame": 6, "x": 120, "zoom": 2, "rotation": 15}],
    )
    scene_path = ws.scene_path("main")
    code = f'var scene = new Scene("{scene_path}");\nscene.save("{scene_path}");\nprint("{bridge.OK_MARKER}");\n'
    assert bridge.run_script_or_raise(ctx, ws.root, code).ok
    text = scene_path.read_text(encoding="utf-8")
    assert text.count("<keyframes>") == 3
    for tag in ("<x>", "<sc>", "<rot>"):
        assert tag in text


# -- output polish -------------------------------------------------------------
def test_render_frame_max_width_downscales_only_the_preview(live_context):
    """One small file for looking at, full resolution for what is delivered."""
    ctx = live_context
    _camera_scene(ctx, "preview")

    preview = R.render_frame(ctx, "preview", "main", frame=1, out_name="small", max_width=320)
    assert preview.downscaled_from == (640, 360)
    with Image.open(preview.frames[0]) as img:
        assert img.size == (320, 180)

    full = R.render_frame(ctx, "preview", "main", frame=1, out_name="big")
    assert full.downscaled_from is None
    with Image.open(full.frames[0]) as img:
        assert img.size == (640, 360)


def test_render_gif_makes_a_looping_file(live_context):
    ctx = live_context
    _camera_scene(ctx, "gifreel")
    gif, rendered = R.render_gif(ctx, "gifreel", "main", fps=8, out_name="reel", max_width=200)
    assert gif.is_file() and gif.stat().st_size > 0
    assert len(rendered.frames) == 12
    with Image.open(gif) as img:
        assert img.size[0] == 200
        assert getattr(img, "n_frames", 1) == 12


def test_render_video_muxes_an_external_track(live_context, tmp_path):
    """OpenToonz audio is unreachable, so the soundtrack is always external."""
    ctx = live_context
    _camera_scene(ctx, "mux")
    track = tmp_path / "score.wav"
    subprocess.run(
        [ctx.settings.ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(track)],
        capture_output=True,
        check=True,
    )
    video, rendered = R.render_video(ctx, "mux", "main", fps=8, out_name="clip", audio=str(track))
    assert video.is_file() and rendered.frames
    probed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    assert probed.stdout.strip() == "aac"


# -- ranges, directory import, encoding, cleaning ------------------------------
def test_render_frame_range_renders_only_that_section(live_context):
    ctx = live_context
    ws, _ = W.create(ctx, "range")
    scenes.import_level(ctx, "range", "ball", _draw_ball(ws, n=5), "main")
    full = R.render_frames(ctx, "range", "main", out_name="seq")
    assert len(full.frames) == 5
    section = R.render_frames(ctx, "range", "main", out_name="seq", frame_range=(1, 3))
    assert len(section.frames) == 3
    assert [p.name for p in section.frames] == ["seq_0001.png", "seq_0002.png", "seq_0003.png"]


def test_import_level_accepts_a_directory(live_context, tmp_path):
    """A directory is the usual shape an exported sequence arrives in."""
    ctx = live_context
    W.create(ctx, "dirimport")
    seq = tmp_path / "frames"
    seq.mkdir()
    for i in range(1, 4):
        Image.new("RGBA", (64, 64), (i * 60, 0, 0, 255)).save(seq / f"shot_{i}.png")
    imported = scenes.import_level(ctx, "dirimport", "shot", [str(seq)], "main")
    assert imported.result.ok, imported.result.summary()
    assert [p.name for p in imported.copied] == ["shot.0001.png", "shot.0002.png", "shot.0003.png"]


def test_render_video_crf_and_scale_reach_ffmpeg(live_context):
    """scale resizes the delivered MP4 (even dimensions kept for yuv420p)."""
    ctx = live_context
    _camera_scene(ctx, "encode")
    video, rendered = R.render_video(ctx, "encode", "main", fps=8, out_name="clip", crf=30, scale=0.5)
    assert video.is_file() and rendered.frames
    probed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    assert probed.stdout.strip() == "320,180"


def test_clean_reclaims_workspace_space(live_context):
    ctx = live_context
    ws, _ = W.create(ctx, "tidy")
    scenes.import_level(ctx, "tidy", "ball", _draw_ball(ws), "main")
    R.render_frames(ctx, "tidy", "main", out_name="seq")
    before = W.disk_usage(ws)
    assert before > 0

    targets, freed = W.clean(ctx, "tidy", "all")
    assert sorted(targets) == ["drawings", "render", "scripts"]
    assert 0 < freed <= before
    assert W.disk_usage(ws) < before
    assert ws.root.is_dir()  # the workspace itself is kept
