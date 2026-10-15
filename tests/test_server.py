import asyncio

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
    "opentoonz_draw_frame",
    "opentoonz_draw_frames",
    "opentoonz_render_frame",
    "opentoonz_render",
    "opentoonz_render_video",
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
