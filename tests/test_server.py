import asyncio

from opentoonz_mcp.server import mcp

EXPECTED_TOOLS = {
    "opentoonz_health",
    "opentoonz_doctor",
    "opentoonz_create_workspace",
    "opentoonz_list_workspaces",
    "opentoonz_scene_new",
    "opentoonz_scene_info",
    "opentoonz_import_images_as_level",
    "opentoonz_set_cells",
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
