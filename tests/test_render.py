"""Faked-subprocess tests for the render layer (no OpenToonz runtime needed).

Rendering shells out to ``tcomposer`` and then ``ffmpeg``; faking ``subprocess.run``
lets the command lines, the preview downscale and the GIF filter graph be
asserted exactly, which the e2e suite cannot do cheaply.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from opentoonz_mcp import render
from opentoonz_mcp import workspace as W
from opentoonz_mcp.errors import OpentoonzMCPError, RenderError


@pytest.fixture()
def prepared(context):
    context._prepared = True
    return context


def _scene(context, name="main"):
    ws, _ = W.create(context, "w")
    ws.scene_path(name).write_text('<tnz framecount="3"/>', encoding="utf-8")
    return ws


def _fake(monkeypatch, handlers):
    """Route faked subprocess.run calls by program name; record every argv."""
    calls = []

    def fake_run(cmd, **kwargs):
        argv = [str(part) for part in cmd]
        calls.append(argv)
        handler = handlers.get(Path(argv[0]).name)
        if handler is None:
            raise AssertionError(f"unexpected command: {argv}")
        return handler(argv)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _tcomposer(*sizes):
    """A tcomposer stand-in that writes one PNG per given size."""

    def handler(argv):
        prefix = Path(argv[argv.index("-o") + 1])
        for index, size in enumerate(sizes, start=1):
            Image.new("RGBA", size, (255, 0, 0, 255)).save(prefix.parent / f"{prefix.stem}{index:04d}.png")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return handler


def _writes_output():
    """An ffmpeg stand-in that just creates the file it was asked for."""

    def handler(argv):
        Path(argv[-1]).write_bytes(b"fake")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return handler


def test_render_frame_downscales_the_preview_in_place(prepared, monkeypatch):
    _scene(prepared)
    _fake(monkeypatch, {"tcomposer": _tcomposer((640, 360))})
    result = render.render_frame(prepared, "w", "main", frame=1, max_width=320)
    assert result.downscaled_from == (640, 360)
    with Image.open(result.frames[0]) as img:
        assert img.size == (320, 180)  # aspect ratio kept


def test_render_frame_keeps_frames_that_are_already_small(prepared, monkeypatch):
    _scene(prepared)
    _fake(monkeypatch, {"tcomposer": _tcomposer((320, 180))})
    result = render.render_frame(prepared, "w", "main", max_width=640)
    assert result.downscaled_from is None
    with Image.open(result.frames[0]) as img:
        assert img.size == (320, 180)


def test_render_frame_rejects_a_bad_max_width(prepared, monkeypatch):
    _scene(prepared)
    _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36))})
    with pytest.raises(RenderError, match="max_width"):
        render.render_frame(prepared, "w", "main", max_width=0)


def test_render_frames_clears_the_previous_preview(prepared, monkeypatch):
    ws = _scene(prepared)
    stale = ws.render / "look_0009.png"
    stale.write_bytes(b"old")
    _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36))})
    result = render.render_frame(prepared, "w", "main")
    assert not stale.exists()
    assert len(result.frames) == 1


def test_render_frames_explains_a_missing_scene(prepared):
    _scene(prepared)
    with pytest.raises(RenderError, match="Scene not found"):
        render.render_frames(prepared, "w", "nope")


def test_render_frames_passes_a_frame_range(prepared, monkeypatch):
    _scene(prepared)
    calls = _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36))})
    render.render_frames(prepared, "w", "main", frame_range=(1, 3))
    cmd = calls[-1]
    at = cmd.index("-range")
    assert cmd[at + 1 : at + 3] == ["1", "3"]


def test_render_frames_passes_a_single_frame(prepared, monkeypatch):
    _scene(prepared)
    calls = _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36))})
    render.render_frames(prepared, "w", "main", frame=4)
    cmd = calls[-1]
    assert cmd[cmd.index("-frame") + 1] == "4"


def test_a_missing_tcomposer_is_explained(prepared, monkeypatch):
    _scene(prepared)

    def explode(argv):
        raise FileNotFoundError("tcomposer")

    _fake(monkeypatch, {"tcomposer": explode})
    with pytest.raises(RenderError, match="tcomposer not found"):
        render.render_frames(prepared, "w", "main")


def test_render_video_muxes_an_external_track(prepared, monkeypatch, tmp_path):
    _scene(prepared)
    track = tmp_path / "score.wav"
    track.write_bytes(b"RIFF")
    calls = _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36)), "ffmpeg": _writes_output()})
    video, result = render.render_video(prepared, "w", "main", fps=12, audio=str(track))
    assert video.suffix == ".mp4" and video.exists() and result.frames
    muxer = calls[-1]
    assert str(track) in muxer
    assert muxer[muxer.index("-c:a") + 1] == "aac"
    assert "-shortest" in muxer
    assert muxer[muxer.index("-framerate") + 1] == "12"


def test_render_video_without_audio_stays_video_only(prepared, monkeypatch):
    _scene(prepared)
    calls = _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36)), "ffmpeg": _writes_output()})
    render.render_video(prepared, "w", "main")
    assert "-c:a" not in calls[-1]


def test_render_video_applies_crf_and_scale(prepared, monkeypatch):
    _scene(prepared)
    calls = _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36)), "ffmpeg": _writes_output()})
    render.render_video(prepared, "w", "main", crf=18, scale=0.5)
    cmd = calls[-1]
    assert cmd[cmd.index("-crf") + 1] == "18"
    # even dimensions, because libx264 + yuv420p rejects odd ones
    assert cmd[cmd.index("-vf") + 1] == "scale=trunc(iw*0.5/2)*2:trunc(ih*0.5/2)*2"


def test_render_video_keeps_even_dimensions_when_scaled(prepared, monkeypatch):
    _scene(prepared)
    calls = _fake(monkeypatch, {"tcomposer": _tcomposer((65, 37)), "ffmpeg": _writes_output()})
    render.render_video(prepared, "w", "main", scale=2)
    assert calls[-1][calls[-1].index("-vf") + 1] == "scale=trunc(iw*2.0/2)*2:trunc(ih*2.0/2)*2"


def test_render_video_forces_even_dimensions_without_scale(prepared, monkeypatch):
    """libx264 + yuv420p rejects odd width/height, and a scene can be odd-sized.

    The even-dimension filter used to be applied only when ``scale`` was given,
    so an odd-sized scene failed at the encoder.
    """
    _scene(prepared)
    calls = _fake(monkeypatch, {"tcomposer": _tcomposer((65, 37)), "ffmpeg": _writes_output()})
    render.render_video(prepared, "w", "main")
    cmd = calls[-1]
    assert "-crf" not in cmd
    assert cmd[cmd.index("-vf") + 1] == "scale=trunc(iw/2)*2:trunc(ih/2)*2"


@pytest.mark.parametrize("kwargs", [{"crf": -1}, {"crf": 52}, {"scale": 0}, {"scale": -1}])
def test_render_video_rejects_bad_crf_or_scale(prepared, kwargs):
    _scene(prepared)
    with pytest.raises(RenderError, match="crf|scale"):
        render.render_video(prepared, "w", "main", **kwargs)


def test_render_video_rejects_a_missing_track_before_rendering(prepared):
    _scene(prepared)
    with pytest.raises(RenderError, match="Audio file not found"):
        render.render_video(prepared, "w", "main", audio="/nope/missing.wav")


def test_render_gif_builds_a_palette_filter(prepared, monkeypatch):
    _scene(prepared)
    calls = _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36), (64, 36)), "ffmpeg": _writes_output()})
    gif, result = render.render_gif(prepared, "w", "main", fps=10, out_name="reel", max_width=320, colors=64)
    assert gif.name == "reel.gif" and gif.exists() and len(result.frames) == 2
    command = calls[-1]
    chain = command[command.index("-filter_complex") + 1]
    assert chain.startswith("scale=320:-1:flags=lanczos,split[s0][s1]")
    assert "palettegen=max_colors=64" in chain and "paletteuse" in chain
    assert command[command.index("-loop") + 1] == "0"


def test_render_gif_without_a_width_keeps_the_frame_size(prepared, monkeypatch):
    _scene(prepared)
    calls = _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36)), "ffmpeg": _writes_output()})
    render.render_gif(prepared, "w", "main")
    chain = calls[-1][calls[-1].index("-filter_complex") + 1]
    assert chain.startswith("split[s0][s1]")


@pytest.mark.parametrize(("kwargs", "message"), [({"colors": 1}, "colors"), ({"fps": 0}, "fps")])
def test_render_gif_validates_its_inputs(prepared, kwargs, message):
    _scene(prepared)
    with pytest.raises(RenderError, match=message):
        render.render_gif(prepared, "w", "main", **kwargs)


@pytest.mark.parametrize("out_name", ["../evil", "a/b", "..", "/abs", "a" * 65])
def test_render_rejects_a_traversing_out_name(prepared, monkeypatch, out_name):
    """The stem becomes file names and an ffmpeg glob — it must stay a plain name."""
    _scene(prepared)
    _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36))})
    with pytest.raises(RenderError, match="output name"):
        render.render_frames(prepared, "w", "main", out_name=out_name)


def test_render_rejects_a_traversing_scene_name(prepared):
    _scene(prepared)
    with pytest.raises(W.WorkspaceError, match="scene name"):
        render.render_frames(prepared, "w", "../evil")


# -- output stems must not collide by prefix -----------------------------------
def test_clear_stale_spares_a_similarly_named_render(prepared):
    """``a_`` must not match ``a_b_0001.png``: a prefix is not this render's."""
    ws = _scene(prepared)
    keep = ws.render / "a_b_0001.png"
    keep.write_bytes(b"keep")
    stale = ws.render / "a_0001.png"
    stale.write_bytes(b"stale")
    render._clear_stale(ws.render, "a_")
    assert not stale.exists()
    assert keep.exists()


def test_render_frames_does_not_collect_a_similarly_named_render(prepared, monkeypatch):
    """The frame list is what the render reports — it must be exactly this stem."""
    ws = _scene(prepared)
    other = ws.render / "a_b_0001.png"
    other.write_bytes(b"other")
    _fake(monkeypatch, {"tcomposer": _tcomposer((64, 36))})
    result = render.render_frames(prepared, "w", "main", out_name="a")
    assert [p.name for p in result.frames] == ["a_0001.png"]
    assert other.exists()


# -- frame extraction (B5) -----------------------------------------------------
def _extractor(count=3):
    """An ffmpeg stand-in that writes ``count`` numbered PNGs at the pattern."""

    def handler(argv):
        pattern = Path(argv[-1])
        template = pattern.name.replace("%04d", "{:04d}")
        for index in range(1, count + 1):
            Image.new("RGBA", (16, 9), (0, 0, 255, 255)).save(pattern.parent / template.format(index))
        return subprocess.CompletedProcess(argv, 0, "", "")

    return handler


def test_extract_frames_writes_a_level(prepared, monkeypatch, tmp_path):
    W.create(prepared, "w")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not really a video")
    calls = _fake(monkeypatch, {"ffmpeg": _extractor(3)})
    frames = render.extract_frames(prepared, "w", "shot", str(video))
    assert [p.name for p in frames] == ["shot.0001.png", "shot.0002.png", "shot.0003.png"]
    assert "-vf" not in calls[-1]  # no resample or resize by default


def test_extract_frames_builds_its_filters(prepared, monkeypatch, tmp_path):
    W.create(prepared, "w")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    calls = _fake(monkeypatch, {"ffmpeg": _extractor(1)})
    render.extract_frames(prepared, "w", "shot", str(video), fps=12, start=1.5, end=4, max_width=320)
    cmd = calls[-1]
    assert cmd[cmd.index("-ss") + 1] == "1.5"
    assert cmd[cmd.index("-to") + 1] == "4"
    assert cmd[cmd.index("-vf") + 1] == "fps=12,scale=320:-2"


def test_extract_frames_caps_the_frame_count(prepared, monkeypatch, tmp_path):
    """A long clip must not write unbounded PNGs; ffmpeg is told to stop."""
    W.create(prepared, "w")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    calls = _fake(monkeypatch, {"ffmpeg": _extractor(2)})
    render.extract_frames(prepared, "w", "shot", str(video))
    assert calls[-1][calls[-1].index("-frames:v") + 1] == str(render.MAX_EXTRACT_FRAMES)


def test_extract_frames_honours_an_explicit_cap(prepared, monkeypatch, tmp_path):
    W.create(prepared, "w")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    calls = _fake(monkeypatch, {"ffmpeg": _extractor(2)})
    render.extract_frames(prepared, "w", "shot", str(video), max_frames=100)
    assert calls[-1][calls[-1].index("-frames:v") + 1] == "100"


def test_extract_frames_rejects_a_bad_cap(prepared, monkeypatch, tmp_path):
    W.create(prepared, "w")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    with pytest.raises(RenderError, match="max_frames"):
        render.extract_frames(prepared, "w", "shot", str(video), max_frames=0)


def test_extract_frames_clears_previous_drawings(prepared, monkeypatch, tmp_path):
    ws, _ = W.create(prepared, "w")
    (ws.drawings / "shot.0005.png").write_bytes(b"old")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    _fake(monkeypatch, {"ffmpeg": _extractor(2)})
    frames = render.extract_frames(prepared, "w", "shot", str(video))
    assert len(frames) == 2
    assert not (ws.drawings / "shot.0005.png").exists()


@pytest.mark.parametrize("kwargs", [{"fps": 0}, {"max_width": 0}, {"start": -1}, {"end": -1}, {"start": 5, "end": 2}])
def test_extract_frames_validates_its_inputs(prepared, monkeypatch, tmp_path, kwargs):
    W.create(prepared, "w")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    with pytest.raises(RenderError):
        render.extract_frames(prepared, "w", "shot", str(video), **kwargs)


def test_extract_frames_rejects_a_missing_video(prepared):
    W.create(prepared, "w")
    with pytest.raises(RenderError, match="Video not found"):
        render.extract_frames(prepared, "w", "shot", "/nope/clip.mp4")


def test_extract_frames_rejects_a_bad_level_name(prepared, tmp_path):
    W.create(prepared, "w")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    with pytest.raises(OpentoonzMCPError, match="Invalid level name"):
        render.extract_frames(prepared, "w", "../evil", str(video))
