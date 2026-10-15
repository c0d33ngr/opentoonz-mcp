from opentoonz_mcp.scenes import parse_scene_info

SAMPLE = """\
FRAMECOUNT=3
COLUMNS=2
LEVEL|ball|Raster|3|/ws/drawings/ball..png
LEVEL|bg|Raster|3|/ws/drawings/bg..png
CELL|0|0|ball|1
CELL|1|0|ball|2
CELL|2|0|ball|3
CELL|0|1|bg|1
__OTMCP_OK__
"""


def test_parse_scene_info():
    info = parse_scene_info(SAMPLE)
    assert info.frame_count == 3
    assert info.column_count == 2
    assert [level.name for level in info.levels] == ["ball", "bg"]
    assert info.levels[0].type == "Raster"
    assert len(info.cells) == 4
    assert info.cells[0].row == 0
    assert info.cells[0].column == 0
    assert info.cells[3].level == "bg"


def test_parse_empty():
    info = parse_scene_info("")
    assert info.frame_count == 0
    assert info.column_count == 0
    assert info.levels == []
    assert info.cells == []
