import asyncio
from pathlib import Path

import pytest

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
    out = server.opentoonz_render("w", "main", start=1, end=3)
    assert seen["frame_range"] == (1, 3)
    assert out.startswith("OK")


def test_opentoonz_render_needs_both_range_bounds(context, monkeypatch):
    from opentoonz_mcp import server

    monkeypatch.setattr(server, "get_context", lambda: context)
    out = server.opentoonz_render("w", "main", start=1)
    assert out.startswith("ERROR") and "end" in out
