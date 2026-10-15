import pytest

from opentoonz_mcp import draw
from opentoonz_mcp import scenes as scenes_mod
from opentoonz_mcp import workspace as workspace_mod
from opentoonz_mcp.bridge import ScriptResult
from opentoonz_mcp.errors import OpentoonzMCPError
from opentoonz_mcp.scenes import (
    expand_exposures,
    parse_scene_info,
    set_scene_settings,
    validate_level_name,
)

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

#: Trimmed from a real OpenToonz 1.8 scene. OpenToonz writes a trailing space
#: after each value (``"16 9 \n"``); the patchers must tolerate the surrounding
#: whitespace either way, so it is normalised away here to keep the file
#: whitespace-clean.
SAMPLE_TNZ = """<tnz framecount="1" version="71.1">
  <properties>
    <cameras>
      <camera>
        <cameraSize>
          16 9
        </cameraSize>
        <cameraRes>
          1920 1080
        </cameraRes>
        </camera>
      </cameras>
    <outputs>
      <output name="main">
        <fps>
          24
        </fps>
        <path>
          "+outputs/.tif"
        </path>
      </output>
    </outputs>
  </properties>
</tnz>
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
    assert info.cells_truncated is False


def test_parse_empty():
    info = parse_scene_info("")
    assert info.frame_count == 0
    assert info.column_count == 0
    assert info.levels == []
    assert info.cells == []


def test_parse_scene_info_reports_truncation():
    info = parse_scene_info("FRAMECOUNT=5000\nCOLUMNS=1\nTRUNCATED=1\nCELL|0|0|a|1\n")
    assert info.cells_truncated is True
    assert info.frame_count == 5000


def _write_scene(context, workspace="w", scene="main"):
    ws, _ = workspace_mod.create(context, workspace)
    path = ws.scene_path(scene)
    path.write_text(SAMPLE_TNZ, encoding="utf-8")
    return ws, path


def test_set_scene_settings_resizes_camera(context):
    _, path = _write_scene(context)
    settings = set_scene_settings(context, "w", "main", width=1280, height=720)
    text = path.read_text(encoding="utf-8")
    assert settings.width == 1280
    assert settings.height == 720
    assert settings.camera_size == "10.666667 6"
    assert "1280 720" in text
    assert "1920 1080" not in text
    assert "cameraRes=1280x720" in settings.changed


def test_camera_size_scales_with_the_resolution(context):
    """The physical camera size must grow with the resolution.

    Leaving it at the 16x9 default while shrinking the resolution renders art at
    a fraction of its size (640x360 art came out 213x120 in a 640x360 frame).
    Keeping the ratio at 120 dpi means art draws 1:1 at any resolution.
    """
    _, path = _write_scene(context)
    settings = set_scene_settings(context, "w", "main", width=512, height=512)
    assert settings.camera_size == "4.266667 4.266667"
    width, height = (float(part) for part in settings.camera_size.split())
    assert settings.width / width == pytest.approx(120, rel=1e-5)
    assert settings.height / height == pytest.approx(120, rel=1e-5)
    assert "4.266667 4.266667" in path.read_text(encoding="utf-8")


def test_camera_size_for_a_default_scene_is_the_16_9_default(context):
    """1920x1080 over 120 dpi is exactly the 16x9 the default scene ships with."""
    _write_scene(context)
    settings = set_scene_settings(context, "w", "main", width=1920, height=1080)
    assert settings.changed == []
    assert settings.camera_size == "16 9"


def test_set_scene_settings_partial_keeps_the_other_dimension(context):
    _, path = _write_scene(context)
    settings = set_scene_settings(context, "w", "main", width=960)
    assert (settings.width, settings.height) == (960, 1080)
    assert "960 1080" in path.read_text(encoding="utf-8")


def test_set_scene_settings_sets_fps(context):
    _, path = _write_scene(context)
    settings = set_scene_settings(context, "w", "main", fps=12)
    assert settings.fps == 12
    assert "12" in path.read_text(encoding="utf-8")
    assert "fps=12" in settings.changed


def test_set_scene_settings_noop_is_reported(context):
    _write_scene(context)
    settings = set_scene_settings(context, "w", "main", width=1920, height=1080)
    assert settings.changed == []


@pytest.mark.parametrize("kwargs", [{"width": 0}, {"width": -5}, {"height": 1_000_000}, {"fps": 0}, {"width": "wide"}])
def test_set_scene_settings_rejects_bad_values(context, kwargs):
    _write_scene(context)
    with pytest.raises(OpentoonzMCPError):
        set_scene_settings(context, "w", "main", **kwargs)


def test_set_scene_settings_requires_something_to_change(context):
    _write_scene(context)
    with pytest.raises(OpentoonzMCPError, match="Nothing to change"):
        set_scene_settings(context, "w", "main")


def test_set_scene_settings_missing_scene(context):
    workspace_mod.create(context, "w")
    with pytest.raises(OpentoonzMCPError, match="Scene not found"):
        set_scene_settings(context, "w", "nope", width=100)


def test_expand_exposures_uniform_hold():
    assert expand_exposures([3], 3) == [(0, 1), (1, 1), (2, 1), (3, 2), (4, 2), (5, 2), (6, 3), (7, 3), (8, 3)]


def test_expand_exposures_per_drawing():
    assert expand_exposures([2, 4, 1], 3) == [
        (0, 1),
        (1, 1),
        (2, 2),
        (3, 2),
        (4, 2),
        (5, 2),
        (6, 3),
    ]


def test_expand_exposures_ignores_extra_values():
    assert expand_exposures([2, 2, 2, 9], 3) == [(0, 1), (1, 1), (2, 2), (3, 2), (4, 3), (5, 3)]


def test_expand_exposures_on_twos():
    assert expand_exposures([2], 4) == [(0, 1), (1, 1), (2, 2), (3, 2), (4, 3), (5, 3), (6, 4), (7, 4)]


def test_expand_exposures_on_ones_is_every_drawing():
    assert expand_exposures([1], 3) == [(0, 1), (1, 2), (2, 3)]


@pytest.mark.parametrize(
    ("exposures", "count"),
    [([], 3), ([0], 2), ([-1, 2], 2), ([1, 1], 5), ([3], 0)],
)
def test_expand_exposures_rejects_bad_input(exposures, count):
    with pytest.raises(OpentoonzMCPError):
        expand_exposures(exposures, count)


@pytest.mark.parametrize("name", ["ball", "bg_1", "shot-2", "A" * 64])
def test_validate_level_name_accepts(name):
    assert validate_level_name(name) == name


@pytest.mark.parametrize("name", ["", "a/b", "../evil", "a.b", "sp ace", "A" * 65, "héllo"])
def test_validate_level_name_rejects(name):
    with pytest.raises(OpentoonzMCPError):
        validate_level_name(name)


# -- import_level (the OpenToonz script call is stubbed out) -------------------
def _stub_script(monkeypatch, stdout="LEVEL-REUSED=0\nLEVEL-FRAMES=3\n__OTMCP_OK__\n"):
    """Replace the OpenToonz script runner with a fake that records calls."""
    calls: list[str] = []

    def fake(context, workspace_dir, code, **kwargs):
        calls.append(code)
        return ScriptResult(
            ok=True,
            stdout=stdout,
            stderr="",
            exit_code=0,
            timed_out=False,
            duration=0.0,
            script_path=workspace_dir / "scripts" / "fake.toonzscript",
        )

    monkeypatch.setattr(scenes_mod.bridge, "run_script_or_raise", fake)
    return calls


def _drawings(ws, name, count):
    paths = []
    for index in range(1, count + 1):
        path = ws.drawings / f"{name}.{index:04d}.png"
        draw.draw_frame(
            path, [{"op": "rect", "xy": [0, 0, 4, 4], "fill": "#ffffff"}], width=4, height=4, background=None
        )
        paths.append(str(path))
    return paths


def test_import_level_does_not_delete_its_own_sources(context, monkeypatch):
    """Drawing into drawings/ is the normal workflow — those files must survive."""
    ws, _ = workspace_mod.create(context, "w")
    sources = _drawings(ws, "ball", 3)
    _stub_script(monkeypatch)
    imported = scenes_mod.import_level(context, "w", "ball", sources, "main")
    assert [p.name for p in imported.copied] == ["ball.0001.png", "ball.0002.png", "ball.0003.png"]
    assert all(path.is_file() for path in imported.copied)


def test_import_level_clears_orphaned_frames(context, monkeypatch):
    ws, _ = workspace_mod.create(context, "w")
    _drawings(ws, "ball", 5)
    sources = [str(ws.drawings / f"ball.{i:04d}.png") for i in (1, 2, 3)]
    _stub_script(monkeypatch)
    scenes_mod.import_level(context, "w", "ball", sources, "main")
    assert not (ws.drawings / "ball.0004.png").exists()
    assert not (ws.drawings / "ball.0005.png").exists()
    assert (ws.drawings / "ball.0003.png").is_file()


def test_import_level_does_not_touch_a_similarly_named_level(context, monkeypatch):
    ws, _ = workspace_mod.create(context, "w")
    _drawings(ws, "balloon", 2)
    sources = _drawings(ws, "ball", 2)
    _stub_script(monkeypatch)
    scenes_mod.import_level(context, "w", "ball", sources, "main")
    assert (ws.drawings / "balloon.0001.png").is_file()
    assert (ws.drawings / "balloon.0002.png").is_file()


def test_import_level_reports_reuse(context, monkeypatch):
    ws, _ = workspace_mod.create(context, "w")
    sources = _drawings(ws, "ball", 2)
    _stub_script(monkeypatch, "LEVEL-REUSED=1\nLEVEL-FRAMES=7\n__OTMCP_OK__\n")
    imported = scenes_mod.import_level(context, "w", "ball", sources, "main")
    assert imported.reused is True
    assert imported.frame_count == 7


def test_import_level_rejects_svg(context, monkeypatch):
    ws, _ = workspace_mod.create(context, "w")
    svg = ws.drawings / "shape.svg"
    svg.write_text("<svg/>", encoding="utf-8")
    _stub_script(monkeypatch)
    with pytest.raises(OpentoonzMCPError, match="SVG"):
        scenes_mod.import_level(context, "w", "shape", [str(svg)], "main")


def test_import_level_validates_before_deleting(context, monkeypatch):
    """A bad path must fail before any existing drawings are removed."""
    ws, _ = workspace_mod.create(context, "w")
    _drawings(ws, "ball", 3)
    _stub_script(monkeypatch)
    with pytest.raises(OpentoonzMCPError, match="Image not found"):
        scenes_mod.import_level(context, "w", "ball", [str(ws.drawings / "ball.0001.png"), "/nope/x.png"], "main")
    assert (ws.drawings / "ball.0003.png").is_file()


def test_import_level_rejects_empty_and_bad_names(context, monkeypatch):
    workspace_mod.create(context, "w")
    _stub_script(monkeypatch)
    with pytest.raises(OpentoonzMCPError, match="at least one file"):
        scenes_mod.import_level(context, "w", "ball", [], "main")
    with pytest.raises(OpentoonzMCPError, match="Invalid level name"):
        scenes_mod.import_level(context, "w", "../evil", ["/dev/null"], "main")
