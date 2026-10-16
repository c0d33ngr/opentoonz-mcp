import asyncio
import json
from pathlib import Path

import pytest
from PIL import Image

from opentoonz_mcp.errors import WorkspaceError
from opentoonz_mcp.server import _format_exposure, mcp

EXPECTED_TOOLS = {
    "opentoonz_health",
    "opentoonz_doctor",
    "opentoonz_create_workspace",
    "opentoonz_list_workspaces",
    "opentoonz_scene_new",
    "opentoonz_set_scene_settings",
    "opentoonz_scene_info",
    "opentoonz_import_images_as_level",
    "opentoonz_extract_frames",
    "opentoonz_set_cells",
    "opentoonz_exposure",
    "opentoonz_camera_move",
    "opentoonz_draw_frame",
    "opentoonz_draw_frames",
    "opentoonz_tween_frames",
    "opentoonz_render_frame",
    "opentoonz_render",
    "opentoonz_render_video",
    "opentoonz_render_gif",
    "opentoonz_render_batch",
    "opentoonz_clean",
    "opentoonz_delete_workspace",
    "opentoonz_run_script",
}


def test_all_tools_registered():
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOLS


def test_tools_have_descriptions():
    tools = asyncio.run(mcp.list_tools())
    for tool in tools:
        assert tool.description and tool.description.strip()


@pytest.mark.parametrize(
    ("pairs", "expected"),
    [
        ([(0, 1), (1, 1), (2, 2), (3, 2)], "fid 1: rows 0-1, fid 2: rows 2-3"),
        ([(0, 1)], "fid 1: row 0"),
        ([(0, 1), (1, 2)], "fid 1: row 0, fid 2: row 1"),
        ([(2, 5), (3, 5), (4, 5)], "fid 5: rows 2-4"),
        ([], ""),
    ],
)
def test_format_exposure_compresses_runs(pairs, expected):
    assert _format_exposure(pairs) == expected


def test_opentoonz_render_forwards_a_frame_range(context, monkeypatch):
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    seen = {}

    def fake_render(ctx, workspace, scene, out_name="render", **kwargs):
        seen.update({"workspace": workspace, "scene": scene, "out_name": out_name, **kwargs})
        return render_mod.RenderResult(
            ok=True, frames=[Path("/x/render_0001.png")], log="", exit_code=0, timed_out=False, duration=0.1
        )

    monkeypatch.setattr(render_mod, "render_frames", fake_render)
    res = asyncio.run(server.opentoonz_render("w", "main", start=1, end=3))
    assert seen["frame_range"] == (1, 3)
    assert res.content[0].text.startswith("OK")


def test_opentoonz_render_needs_both_range_bounds(context, monkeypatch):
    from opentoonz_mcp import server

    monkeypatch.setattr(server, "get_context", lambda: context)
    res = asyncio.run(server.opentoonz_render("w", "main", start=1))
    assert res.is_error and "end" in res.content[0].text


# -- structured results (C1) and inline images (A1) ---------------------------
def _call(name, **args):
    """Invoke a tool the way a client does, so content blocks are visible."""
    return asyncio.run(mcp.call_tool(name, args))


def test_render_frame_returns_an_image_and_structured_data(context, monkeypatch, tmp_path):
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    png = tmp_path / "look_0001.png"
    Image.new("RGBA", (32, 18), (1, 2, 3, 255)).save(png)
    monkeypatch.setattr(
        render_mod,
        "render_frame",
        lambda *a, **k: render_mod.RenderResult(
            ok=True, frames=[png], log="", exit_code=0, timed_out=False, duration=0.1
        ),
    )
    res = _call("opentoonz_render_frame", workspace="w", scene="main")
    assert [type(block).__name__ for block in res.content] == ["TextContent", "ImageContent"]
    assert res.structured_content["width"] == 32 and res.structured_content["height"] == 18
    assert res.structured_content["output"].endswith("look_0001.png")


def test_render_frame_defaults_to_a_downscaled_preview(context, monkeypatch, tmp_path):
    """A full-size 1080p image on every look is expensive; the default is small."""
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    png = tmp_path / "look_0001.png"
    Image.new("RGBA", (1920, 1080), (0, 0, 0, 255)).save(png)
    seen = {}

    def fake(ctx, workspace, scene, frame=1, out_name="look", max_width=None):
        seen["max_width"] = max_width
        return render_mod.RenderResult(ok=True, frames=[png], log="", exit_code=0, timed_out=False, duration=0.1)

    monkeypatch.setattr(render_mod, "render_frame", fake)
    _call("opentoonz_render_frame", workspace="w", scene="main")
    assert seen["max_width"] == server.DEFAULT_PREVIEW_WIDTH


def test_render_frame_full_size_on_request(context, monkeypatch, tmp_path):
    """max_width=0 opts out of the preview downscale."""
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    png = tmp_path / "look_0001.png"
    Image.new("RGBA", (1920, 1080), (0, 0, 0, 255)).save(png)
    seen = {}

    def fake(ctx, workspace, scene, frame=1, out_name="look", max_width=None):
        seen["max_width"] = max_width
        return render_mod.RenderResult(ok=True, frames=[png], log="", exit_code=0, timed_out=False, duration=0.1)

    monkeypatch.setattr(render_mod, "render_frame", fake)
    _call("opentoonz_render_frame", workspace="w", scene="main", max_width=0)
    assert seen["max_width"] is None


def test_render_returns_structured_content(context, monkeypatch, tmp_path):
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    frame = tmp_path / "render_0001.png"
    Image.new("RGBA", (8, 8)).save(frame)
    monkeypatch.setattr(
        render_mod,
        "render_frames",
        lambda *a, **k: render_mod.RenderResult(
            ok=True, frames=[frame], log="", exit_code=0, timed_out=False, duration=0.5
        ),
    )
    res = _call("opentoonz_render", workspace="w", scene="main")
    assert res.structured_content["frames"] == 1
    assert res.content[0].type == "text"  # the human summary is still there


def test_list_workspaces_returns_structured_content(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.render / "clip.mp4").write_bytes(b"x")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call("opentoonz_list_workspaces")
    reports = res.structured_content["workspaces"]
    assert reports[0]["name"] == "w" and "clip.mp4" in reports[0]["videos"]


def test_scene_info_returns_structured_content(context, monkeypatch):
    from opentoonz_mcp import scenes as scenes_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    info = scenes_mod.SceneInfo(
        frame_count=3,
        column_count=1,
        levels=[scenes_mod.LevelInfo("ball", "Raster", "3", "/x/ball..png")],
        cells=[scenes_mod.CellInfo(0, 0, "ball", "1")],
    )
    monkeypatch.setattr(scenes_mod, "scene_info", lambda *a, **k: info)
    res = _call("opentoonz_scene_info", workspace="w", scene="main")
    assert res.structured_content["frames"] == 3
    assert res.structured_content["levels"][0]["name"] == "ball"
    assert res.structured_content["cells"][0]["fid"] == "1"


def test_opentoonz_clean_refuses_without_confirmation(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.render / "clip.mp4").write_bytes(b"x")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call("opentoonz_clean", workspace="w")
    assert res.is_error and "confirm" in res.content[0].text
    assert (ws.render / "clip.mp4").is_file()  # nothing was touched


def test_opentoonz_clean_removes_files_with_confirmation(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.render / "clip.mp4").write_bytes(b"x" * 50)
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call("opentoonz_clean", workspace="w", confirm=True)
    assert not res.is_error
    assert res.structured_content["bytes_freed"] >= 50
    assert not (ws.render / "clip.mp4").exists()


def test_opentoonz_tween_frames_writes_a_sequence(context, monkeypatch, tmp_path):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    sprite = tmp_path / "s.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(sprite)
    out = server.opentoonz_tween_frames(
        "w",
        "ball",
        {"path": str(sprite), "xy": [10, 10]},
        {"path": str(sprite), "xy": [30, 10]},
        3,
        width=40,
        height=20,
    )
    assert out.startswith("OK")
    assert (ws.drawings / "ball.0001.png").is_file()
    assert (ws.drawings / "ball.0003.png").is_file()


def test_opentoonz_extract_frames_returns_the_paths(context, monkeypatch):
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    frames = [ws.drawings / f"shot.{index:04d}.png" for index in (1, 2)]
    monkeypatch.setattr(render_mod, "extract_frames", lambda *a, **k: frames)
    out = server.opentoonz_extract_frames("w", "shot", "/tmp/clip.mp4")
    assert out.startswith("OK: extracted 2 frames")
    assert "shot.0002.png" in out


def test_opentoonz_delete_workspace_refuses_without_confirmation(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call("opentoonz_delete_workspace", workspace="w")
    assert res.is_error and "confirm" in res.content[0].text
    assert ws.root.is_dir()  # nothing was touched


def test_opentoonz_delete_workspace_removes_it(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.render / "clip.mp4").write_bytes(b"x" * 20)
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call("opentoonz_delete_workspace", workspace="w", confirm=True)
    assert not res.is_error
    assert not ws.root.exists()


# -- elicitation confirmation for destructive tools ----------------------------
class _Elicitor:
    """Stands in for fastmcp's Context, answering the confirmation prompt."""

    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.prompts = []

    async def elicit(self, message, response_type=None, **kwargs):
        self.prompts.append(message)
        if self.error is not None:
            raise self.error
        return self.answer


def test_clean_can_be_confirmed_by_elicitation(context, monkeypatch):
    from fastmcp.server.elicitation import AcceptedElicitation

    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.render / "clip.mp4").write_bytes(b"x")
    monkeypatch.setattr(server, "get_context", lambda: context)
    elicitor = _Elicitor(AcceptedElicitation(data=True))
    res = asyncio.run(server.opentoonz_clean("w", ctx=elicitor))
    assert not res.is_error
    assert not (ws.render / "clip.mp4").exists()
    assert elicitor.prompts  # a human was actually asked


def test_clean_declined_by_the_user_refuses(context, monkeypatch):
    from fastmcp.server.elicitation import DeclinedElicitation

    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.render / "clip.mp4").write_bytes(b"x")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = asyncio.run(server.opentoonz_clean("w", ctx=_Elicitor(DeclinedElicitation())))
    assert res.is_error
    assert (ws.render / "clip.mp4").is_file()


def test_clean_falls_back_to_confirm_when_elicitation_is_unsupported(context, monkeypatch):
    """No way to ask a human: keep requiring the explicit flag, not assume consent."""
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.render / "clip.mp4").write_bytes(b"x")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = asyncio.run(server.opentoonz_clean("w", ctx=_Elicitor(error=RuntimeError("unsupported"))))
    assert res.is_error and "confirm" in res.content[0].text
    assert (ws.render / "clip.mp4").is_file()


def test_clean_with_confirm_skips_the_prompt(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.render / "clip.mp4").write_bytes(b"x")
    monkeypatch.setattr(server, "get_context", lambda: context)
    elicitor = _Elicitor()
    res = asyncio.run(server.opentoonz_clean("w", confirm=True, ctx=elicitor))
    assert not res.is_error
    assert elicitor.prompts == []


def test_delete_workspace_can_be_confirmed_by_elicitation(context, monkeypatch):
    from fastmcp.server.elicitation import AcceptedElicitation

    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = asyncio.run(server.opentoonz_delete_workspace("w", ctx=_Elicitor(AcceptedElicitation(data=True))))
    assert not res.is_error
    assert not ws.root.exists()


def test_delete_workspace_declined_by_the_user_refuses(context, monkeypatch):
    from fastmcp.server.elicitation import DeclinedElicitation

    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = asyncio.run(server.opentoonz_delete_workspace("w", ctx=_Elicitor(DeclinedElicitation())))
    assert res.is_error
    assert ws.root.is_dir()


# -- level-name validation (path traversal) ------------------------------------
#: A name that climbs out of the workspace's drawings/ folder.
_TRAVERSAL = "../../esc"


def _escaped(context):
    """The file the traversal would create, if it were not rejected."""
    return context.settings.workspaces_root / "esc.0001.png"


def test_draw_frame_rejects_a_traversing_level_name(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call(
        "opentoonz_draw_frame",
        workspace="w",
        level_name=_TRAVERSAL,
        ops=[{"op": "rect", "xy": [0, 0, 4, 4], "fill": "#ffffff"}],
    )
    assert "Invalid level name" in res.content[0].text
    assert not _escaped(context).exists()


def test_draw_frames_rejects_a_traversing_level_name(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call(
        "opentoonz_draw_frames",
        workspace="w",
        level_name=_TRAVERSAL,
        frames=[[{"op": "rect", "xy": [0, 0, 4, 4], "fill": "#ffffff"}]],
    )
    assert "Invalid level name" in res.content[0].text
    assert not _escaped(context).exists()


def test_tween_frames_rejects_a_traversing_level_name(context, monkeypatch, tmp_path):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    sprite = tmp_path / "s.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(sprite)
    res = _call(
        "opentoonz_tween_frames",
        workspace="w",
        level_name=_TRAVERSAL,
        start={"path": str(sprite)},
        end={"path": str(sprite)},
        frames=2,
    )
    assert "Invalid level name" in res.content[0].text
    assert not _escaped(context).exists()


def test_draw_frame_still_writes_a_plain_name(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call(
        "opentoonz_draw_frame",
        workspace="w",
        level_name="hero",
        ops=[{"op": "rect", "xy": [0, 0, 4, 4], "fill": "#ffffff"}],
    )
    assert res.content[0].text.startswith("OK")
    assert (ws.drawings / "hero.0001.png").is_file()


# -- doctor smoke (C3) ---------------------------------------------------------
def _script_result(ok):
    from opentoonz_mcp import bridge

    return bridge.ScriptResult(
        ok=ok,
        stdout="__OTMCP_OK__" if ok else "",
        stderr="",
        exit_code=0,
        timed_out=False,
        duration=0.2,
        script_path=Path("/tmp/smoke.toonzscript"),
    )


def test_smoke_reports_a_passing_script(context, monkeypatch):
    from opentoonz_mcp import bridge, server

    monkeypatch.setattr(bridge, "run_script", lambda *a, **k: _script_result(True))
    assert server._smoke(context).startswith("OK")


def test_smoke_reports_a_failing_script(context, monkeypatch):
    from opentoonz_mcp import bridge, server

    monkeypatch.setattr(bridge, "run_script", lambda *a, **k: _script_result(False))
    assert server._smoke(context).startswith("FAILED")


def test_doctor_only_smokes_when_asked(context, monkeypatch):
    from opentoonz_mcp import server

    monkeypatch.setattr(server, "get_context", lambda: context)
    monkeypatch.setattr(context, "prepare", lambda: None)
    monkeypatch.setattr(server, "_which_ffmpeg", lambda ctx: "/usr/bin/ffmpeg")
    assert "smoke        :" not in server.opentoonz_doctor()

    monkeypatch.setattr(server, "_smoke", lambda ctx: "OK")
    assert "smoke        : OK" in server.opentoonz_doctor(smoke=True)


def test_opentoonz_clean_orphans_reports_what_it_removed(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.root / "main.tnz").write_text("<scene>used</scene>", encoding="utf-8")
    (ws.drawings / "used.0001.png").write_bytes(b"x")
    (ws.drawings / "unused.0001.png").write_bytes(b"x")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call("opentoonz_clean", workspace="w", what="orphans", confirm=True)
    assert not res.is_error
    assert res.structured_content["cleaned"] == ["unused.0001.png"]
    assert "1 orphaned drawings" in res.content[0].text


# -- batch render (C4) ---------------------------------------------------------
def _render_result(*frames):
    from opentoonz_mcp import render as render_mod

    return render_mod.RenderResult(ok=True, frames=list(frames), log="", exit_code=0, timed_out=False, duration=0.1)


def _two_scenes(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    for name in ("a", "b"):
        ws.scene_path(name).write_text("<scene/>", encoding="utf-8")
    monkeypatch.setattr(server, "get_context", lambda: context)
    return ws


def test_opentoonz_render_batch_renders_every_scene(context, monkeypatch):
    from opentoonz_mcp import render as render_mod

    ws = _two_scenes(context, monkeypatch)

    def fake_video(ctx, workspace, scene, fps=24, out_name="video", **kwargs):
        path = ws.render / f"{out_name}.mp4"
        path.write_bytes(b"v")
        return path, _render_result(path)

    monkeypatch.setattr(render_mod, "render_video", fake_video)
    res = _call("opentoonz_render_batch", workspace="w")
    assert not res.is_error
    assert res.structured_content["rendered"] == 2
    assert [item["scene"] for item in res.structured_content["items"]] == ["a", "b"]


def test_opentoonz_render_batch_keeps_going_after_a_failure(context, monkeypatch):
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp.errors import RenderError

    ws = _two_scenes(context, monkeypatch)
    ran = []

    def fake_video(ctx, workspace, scene, fps=24, out_name="video", **kwargs):
        ran.append(scene)
        if scene == "a":
            raise RenderError("boom")
        path = ws.render / f"{out_name}.mp4"
        path.write_bytes(b"v")
        return path, _render_result(path)

    monkeypatch.setattr(render_mod, "render_video", fake_video)
    res = _call("opentoonz_render_batch", workspace="w")
    assert not res.is_error  # a partial batch is a result, not an error
    assert res.structured_content["rendered"] == 1
    assert res.structured_content["failed"] == 1
    assert ran == ["a", "b"]  # the second scene still ran


def test_opentoonz_render_batch_rejects_an_ambiguous_out_name(context, monkeypatch):
    _two_scenes(context, monkeypatch)
    res = _call("opentoonz_render_batch", workspace="w", out_name="clip")
    assert res.is_error and "ambiguous" in res.content[0].text


def test_opentoonz_render_batch_needs_scenes(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    res = _call("opentoonz_render_batch", workspace="w")
    assert res.is_error and "no scenes" in res.content[0].text


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"kind": "nope"}, "kind"),
        ({"kind": "video", "start": 1, "end": 2}, "start/end"),
        ({"kind": "frames", "start": 1}, "together"),
        ({"kind": "gif", "crf": 20}, "crf/scale"),
        ({"scenes": ["ghost"]}, "no such scene"),
    ],
)
def test_opentoonz_render_batch_validates(context, monkeypatch, kwargs, message):
    _two_scenes(context, monkeypatch)
    res = _call("opentoonz_render_batch", workspace="w", **kwargs)
    assert res.is_error and message in res.content[0].text


# -- progress reporting (C5) ---------------------------------------------------
class _ProgressRecorder:
    """Stands in for fastmcp's Context, which is injected at call time."""

    def __init__(self):
        self.calls = []

    async def report_progress(self, progress, total=None, message=None):
        self.calls.append((progress, total, message))


def test_opentoonz_render_reports_progress(context, monkeypatch):
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    monkeypatch.setattr(render_mod, "render_frames", lambda *a, **k: _render_result(ws.render / "render_0001.png"))
    recorder = _ProgressRecorder()
    asyncio.run(server.opentoonz_render("w", "main", ctx=recorder))
    assert recorder.calls
    assert recorder.calls[0][0] == 0
    assert recorder.calls[-1][0] == recorder.calls[-1][1]  # finishes at 100%


def test_opentoonz_render_runs_without_a_context(context, monkeypatch):
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    monkeypatch.setattr(render_mod, "render_frames", lambda *a, **k: _render_result(ws.render / "render_0001.png"))
    result = asyncio.run(server.opentoonz_render("w", "main"))  # no ctx at all
    assert not result.is_error


def test_opentoonz_render_video_reports_progress(context, monkeypatch):
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    monkeypatch.setattr(server, "get_context", lambda: context)
    video = ws.render / "video.mp4"
    monkeypatch.setattr(render_mod, "render_video", lambda *a, **k: (video, _render_result(video)))
    recorder = _ProgressRecorder()
    asyncio.run(server.opentoonz_render_video("w", "main", ctx=recorder))
    assert recorder.calls[-1][0] == recorder.calls[-1][1]


def test_opentoonz_render_batch_reports_per_scene_progress(context, monkeypatch):
    from opentoonz_mcp import render as render_mod
    from opentoonz_mcp import server

    ws = _two_scenes(context, monkeypatch)

    def fake_video(ctx, workspace, scene, fps=24, out_name="video", **kwargs):
        return ws.render / f"{out_name}.mp4", _render_result(ws.render / f"{out_name}.mp4")

    monkeypatch.setattr(render_mod, "render_video", fake_video)
    recorder = _ProgressRecorder()
    asyncio.run(server.opentoonz_render_batch("w", ctx=recorder))
    assert [call[0] for call in recorder.calls] == [0, 1, 2]
    assert all(call[1] == 2 for call in recorder.calls)


# -- MCP resources (C2) --------------------------------------------------------
def _read_resource(uri):
    return asyncio.run(mcp.read_resource(uri)).contents[0].content


def test_resources_are_registered():
    uris = {str(resource.uri) for resource in asyncio.run(mcp.list_resources())}
    templates = {template.uri_template for template in asyncio.run(mcp.list_resource_templates())}
    assert "opentoonz://workspaces" in uris
    assert {"opentoonz://workspace/{name}", "opentoonz://workspace/{name}/scene/{scene}"} <= templates


def test_workspaces_resource_lists_workspaces(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    (ws.render / "clip.mp4").write_bytes(b"x" * 10)
    monkeypatch.setattr(server, "get_context", lambda: context)
    payload = json.loads(_read_resource("opentoonz://workspaces"))
    assert payload[0]["name"] == "w"
    assert payload[0]["videos"] == ["clip.mp4"]
    assert payload[0]["size_bytes"] >= 10


def test_workspace_resource_describes_one_workspace(context, monkeypatch):
    from opentoonz_mcp import server
    from opentoonz_mcp import workspace as W

    ws, _ = W.create(context, "w")
    ws.scene_path("main").write_text("<scene/>", encoding="utf-8")
    monkeypatch.setattr(server, "get_context", lambda: context)
    payload = json.loads(_read_resource("opentoonz://workspace/w"))
    assert payload["name"] == "w"
    assert payload["scenes"] == ["main.tnz"]


def test_workspace_resource_rejects_a_missing_workspace(context, monkeypatch):
    from opentoonz_mcp import server

    monkeypatch.setattr(server, "get_context", lambda: context)
    with pytest.raises(WorkspaceError):
        server.workspace_resource("ghost")


def test_scene_resource_reports_the_scene(context, monkeypatch):
    from opentoonz_mcp import scenes as scenes_mod
    from opentoonz_mcp import server

    info = scenes_mod.SceneInfo(
        frame_count=12,
        column_count=2,
        levels=[scenes_mod.LevelInfo(name="ball", type="ToonzRasterLevel", frame_count="4", path="drawings/ball..png")],
        cells=[scenes_mod.CellInfo(row=0, column=0, level="ball", fid="1")],
    )
    monkeypatch.setattr(server, "get_context", lambda: context)
    monkeypatch.setattr(scenes_mod, "scene_info", lambda *a, **k: info)
    payload = json.loads(_read_resource("opentoonz://workspace/w/scene/main"))
    assert payload["frames"] == 12
    assert payload["levels"][0]["name"] == "ball"
    assert payload["cells"][0]["row"] == 0
