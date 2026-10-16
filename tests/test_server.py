import asyncio
from pathlib import Path

import pytest
from PIL import Image

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
    "opentoonz_set_cells",
    "opentoonz_exposure",
    "opentoonz_camera_move",
    "opentoonz_draw_frame",
    "opentoonz_draw_frames",
    "opentoonz_render_frame",
    "opentoonz_render",
    "opentoonz_render_video",
    "opentoonz_render_gif",
    "opentoonz_clean",
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
    res = server.opentoonz_render("w", "main", start=1, end=3)
    assert seen["frame_range"] == (1, 3)
    assert res.content[0].text.startswith("OK")


def test_opentoonz_render_needs_both_range_bounds(context, monkeypatch):
    from opentoonz_mcp import server

    monkeypatch.setattr(server, "get_context", lambda: context)
    res = server.opentoonz_render("w", "main", start=1)
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
