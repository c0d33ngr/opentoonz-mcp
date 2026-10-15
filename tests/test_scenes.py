import re

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


# -- camera moves (patched into the .tnz XML) ---------------------------------
#: Trimmed from a real OpenToonz 1.8 scene: the camera is a stage object in the
#: xsheet's <pegbars>, carrying its own <camera> block. A second pegbar and the
#: level column are present to prove the patcher only touches the camera.
CAMERA_TNZ = """<tnz framecount="1" version="71.1">
  <properties>
    <cameras>
      <camera>
        <cameraSize>
          5.33333 3
        </cameraSize>
        <cameraRes>
          640 360
        </cameraRes>
        </camera>
      </cameras>
  </properties>
  <xsheet>
    <columns>
      <levelColumn id='2'>
        <status>
          0
        </status>
        </levelColumn>
      </columns>
    <pegbars>
      <pegbar activeboth="yes" id="Camera1">
        <parent handle="B" id="None" parentHandle="B">
          </parent>
        <isOpened>
          0
        </isOpened>
        <center>
          0 0 0 0
        </center>
        <status>
          0
        </status>
        <sx>
          <default>
            1
          </default>
          </sx>
        <sc>
          <default>
            1
          </default>
          </sc>
        <nodePos>
          1.234e+09 5.678e+09
        </nodePos>
        <camera>
          <cameraSize>
            5.33333 3
          </cameraSize>
          <cameraRes>
            640 360
          </cameraRes>
          </camera>
        </pegbar>
      <pegbar id="Col1">
        <parent handle="B" id="Table" parentHandle="B">
          </parent>
        <status>
          0
        </status>
        <nodePos>
          1.234e+09 5.678e+09
        </nodePos>
        </pegbar>
      </grid_dimension>
      </pegbars>
  </xsheet>
</tnz>
"""


def _write_camera_scene(context, workspace="w", scene="main"):
    ws, _ = workspace_mod.create(context, workspace)
    path = ws.scene_path(scene)
    path.write_text(CAMERA_TNZ, encoding="utf-8")
    return ws, path


def test_px_per_inch_is_read_from_the_scene():
    """640 px over a 5.33333 inch camera is 120 dpi, matching IMAGE_DPI."""
    assert scenes_mod._px_per_inch(CAMERA_TNZ) == pytest.approx(120, rel=1e-6)


def test_px_per_inch_falls_back_when_the_camera_is_missing():
    assert scenes_mod._px_per_inch("<tnz/>") == scenes_mod.IMAGE_DPI


def test_camera_keys_default_to_no_movement():
    keys = scenes_mod._normalise_camera_keys([{"frame": 1}, {"frame": 24, "x": 120}])
    assert [key.frame for key in keys] == [1, 24]
    assert keys[0] == scenes_mod.CameraKey(frame=1)
    assert keys[1] == scenes_mod.CameraKey(frame=24, x=120.0)


def test_camera_keys_are_sorted():
    keys = scenes_mod._normalise_camera_keys([{"frame": 24, "zoom": 2}, {"frame": 1}])
    assert [key.frame for key in keys] == [1, 24]


def test_camera_keys_accept_a_single_keyframe():
    keys = scenes_mod._normalise_camera_keys({"frame": 5, "x": 10})
    assert keys == [scenes_mod.CameraKey(frame=5, x=10.0)]


@pytest.mark.parametrize(
    "keyframes",
    [
        [],
        [{"x": 10}],
        [{"frame": 0}],
        [{"frame": -3}],
        [{"frame": 1.5}],
        [{"frame": "one"}],
        [{"frame": 1, "zoom": 0}],
        [{"frame": 1, "zoom": -2}],
        [{"frame": 1, "x": "left"}],
        [{"frame": 1}, {"frame": 1, "x": 5}],
        "not-a-list",
        [42],
    ],
)
def test_camera_keys_reject_bad_input(keyframes):
    with pytest.raises(OpentoonzMCPError):
        scenes_mod._normalise_camera_keys(keyframes)


def test_camera_channels_convert_units_and_drop_neutral_channels():
    """Only the channels a move actually uses are written."""
    keys = scenes_mod._normalise_camera_keys([{"frame": 1, "x": 0}, {"frame": 25, "x": 120, "zoom": 4}])
    channels = scenes_mod._camera_channels(keys, 120.0)
    # 1-based tool frames become 0-based xsheet rows; 120 px is 1 scene unit.
    assert [(row.row, row.value) for row in channels["x"]] == [(0, 0.0), (24, 1.0)]
    assert [(row.row, row.value) for row in channels["sc"]] == [(0, 1.0), (24, 0.25)]
    assert all(row.ease is False for row in channels["x"])
    assert "y" not in channels
    assert "rot" not in channels


def test_camera_channels_neutral_move_is_empty():
    keys = scenes_mod._normalise_camera_keys([{"frame": 1}, {"frame": 24, "zoom": 1}])
    assert scenes_mod._camera_channels(keys, 120.0) == {}


def test_camera_ease_is_symmetric_over_half_the_segment_each_side():
    keys = scenes_mod._normalise_camera_keys([{"frame": 1, "x": 0, "ease": True}, {"frame": 13, "x": 120}])
    ease_in, ease_out = scenes_mod._ease_lengths(keys)
    # a 12-frame segment gets 6 frames of ease at each end
    assert (ease_in, ease_out) == ([0.0, 6.0], [6.0, 0.0])


def test_camera_ease_on_the_last_keyframe_is_ignored():
    """It has no segment to ease — which is what lets ease be stamped everywhere."""
    keys = scenes_mod._normalise_camera_keys(
        [{"frame": 1, "x": 0, "ease": True}, {"frame": 13, "x": 120, "ease": True}]
    )
    assert scenes_mod._ease_lengths(keys) == ([0.0, 6.0], [6.0, 0.0])


def test_camera_keys_reject_a_non_boolean_ease():
    with pytest.raises(OpentoonzMCPError, match="ease"):
        scenes_mod._normalise_camera_keys([{"frame": 1, "ease": "yes"}])


def test_camera_move_writes_ease_lengths_and_the_prev_handle(context):
    """Easing is an <E> tag carrying a length in frames, plus a <prev> handle.

    OpenToonz reads the ease *into* a keyframe from that keyframe's own <prev>
    child, so the ease-out cannot be stored on the keyframe the segment starts
    from — it has to be written on the one it arrives at.
    """
    _, path = _write_camera_scene(context)
    moved = scenes_mod.camera_move(context, "w", "main", [{"frame": 1, "x": 0, "ease": True}, {"frame": 13, "x": 240}])
    text = path.read_text(encoding="utf-8")
    assert moved.eased_segments == 1
    # 240 px is 2 scene units; the 12-frame segment eases over 6 frames each way.
    # The value is only ~2 (cameraSize is a 6-digit approximation), so match loosely.
    assert re.search(r"<E>\s*0 0 6 ", text)
    assert re.search(r"<prev>\s*1\.99\d+ -6 ", text)
    assert text.count("<E>") == 1
    assert text.count("<L>") == 1


def test_camera_move_without_ease_writes_no_ease_markup(context):
    _, path = _write_camera_scene(context)
    moved = scenes_mod.camera_move(context, "w", "main", [{"frame": 1, "x": 0}, {"frame": 13, "x": 240}])
    text = path.read_text(encoding="utf-8")
    assert moved.eased_segments == 0
    assert "<E>" not in text and "<prev>" not in text


def test_camera_move_writes_animated_channels(context):
    _, path = _write_camera_scene(context)
    moved = scenes_mod.camera_move(
        context, "w", "main", [{"frame": 1, "x": 0, "rotation": 0}, {"frame": 24, "x": 240, "rotation": 90}]
    )
    text = path.read_text(encoding="utf-8")
    assert moved.channels == ["x", "rot"]
    assert (moved.first_frame, moved.last_frame) == (1, 24)
    assert text.count("<keyframes>") == 2
    rows = re.findall(r"<L>\s*(\d+)\s+([\d.-]+)\s*</L>", text)
    assert [int(frame) for frame, _ in rows] == [0, 23, 0, 23]
    # 240 px at 120 dpi is 2 scene units, written on row 23 (frame 24 minus 1).
    # The value is not exactly 2: the scene's cameraSize is a 6-digit
    # approximation, so the stored dpi is 640/5.33333 rather than a clean 120.
    assert float(rows[1][1]) == pytest.approx(2.0, abs=1e-4)
    assert float(rows[3][1]) == pytest.approx(90.0)
    # the pegbar keeps everything it had before
    assert "<center>\n          0 0 0 0\n        </center>" in text
    assert "<sx>" in text


def test_camera_move_second_call_replaces_the_first(context):
    """Keyframes are complete poses: a later move must not inherit an old channel.

    Without this, panning and then zooming would leave the pan switched on.
    """
    _, path = _write_camera_scene(context)
    scenes_mod.camera_move(context, "w", "main", [{"frame": 1, "x": 0}, {"frame": 24, "x": 120}])
    assert "<x>" in path.read_text(encoding="utf-8")
    moved = scenes_mod.camera_move(context, "w", "main", [{"frame": 1, "zoom": 1}, {"frame": 24, "zoom": 2}])
    text = path.read_text(encoding="utf-8")
    assert moved.channels == ["sc"]
    assert "<x>" not in text
    assert text.count("<keyframes>") == 1


def test_camera_move_does_not_touch_other_pegbars_or_the_xsheet(context):
    _, path = _write_camera_scene(context)
    scenes_mod.camera_move(context, "w", "main", [{"frame": 1, "y": 0}, {"frame": 24, "y": 120}])
    text = path.read_text(encoding="utf-8")
    camera = text[text.index('id="Camera1"') : text.index("</pegbars>")]
    col1 = text[text.index('id="Col1"') : text.index("</pegbars>")]
    assert "keyframes" in camera
    assert "keyframes" not in col1
    assert "<levelColumn id='2'>" in text
    # <status> appears in both the level column and the pegbars; none may change.
    assert text.count("<status>") == 3


def test_camera_move_rejects_a_neutral_move(context):
    _write_camera_scene(context)
    with pytest.raises(OpentoonzMCPError, match="Nothing to animate"):
        scenes_mod.camera_move(context, "w", "main", [{"frame": 1}, {"frame": 24}])


def test_camera_move_missing_scene(context):
    workspace_mod.create(context, "w")
    with pytest.raises(OpentoonzMCPError, match="Scene not found"):
        scenes_mod.camera_move(context, "w", "nope", [{"frame": 1, "x": 10}, {"frame": 2, "x": 20}])


def test_camera_move_without_a_camera_pegbar(context):
    workspace_mod.create(context, "w")
    _, path = _write_scene(context)  # SAMPLE_TNZ has no pegbars
    with pytest.raises(OpentoonzMCPError, match="No <pegbar"):
        scenes_mod.camera_move(context, "w", "main", [{"frame": 1, "x": 10}, {"frame": 2, "x": 20}])
    assert path.read_text(encoding="utf-8") == SAMPLE_TNZ
