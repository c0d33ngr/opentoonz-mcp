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
from opentoonz_mcp.errors import RenderError


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
