import pytest
from PIL import Image

from opentoonz_mcp.draw import Frame, draw_frame, parse_color
from opentoonz_mcp.errors import OpentoonzMCPError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#fff", (255, 255, 255, 255)),
        ("#000000", (0, 0, 0, 255)),
        ("#ff000080", (255, 0, 0, 128)),
        ([1, 2, 3], (1, 2, 3, 255)),
        ((1, 2, 3, 4), (1, 2, 3, 4)),
        (None, (0, 0, 0, 0)),
    ],
)
def test_parse_color(value, expected):
    assert parse_color(value) == expected


@pytest.mark.parametrize("value", ["nope", "#12345", [1, 2], [300, 0, 0]])
def test_parse_color_rejects_bad_values(value):
    with pytest.raises(OpentoonzMCPError):
        parse_color(value)


def test_frame_is_rgba_and_sized(tmp_path):
    path = draw_frame(
        tmp_path / "a.png", [{"op": "rect", "xy": [0, 0, 10, 10], "fill": "#ffffff"}], width=64, height=32
    )
    with Image.open(path) as img:
        assert img.size == (64, 32)
        assert img.mode == "RGBA"


def test_ops_produce_visible_content(tmp_path):
    ops = [
        {"op": "rect", "xy": [0, 0, 64, 64], "fill": "#101010"},
        {"op": "ellipse", "box": [16, 16, 48, 48], "fill": "#ff0000"},
        {"op": "line", "xy": [0, 0, 64, 64], "fill": "#ffffff", "width": 2},
        {"op": "text", "xy": [4, 4], "text": "hi", "fill": "#00ff00", "size": 20},
    ]
    path = draw_frame(tmp_path / "b.png", ops, width=64, height=64)
    with Image.open(path) as img:
        assert img.getchannel("A").getbbox() is not None


def test_unknown_op_raises():
    frame = Frame(8, 8, background=None)
    with pytest.raises(OpentoonzMCPError):
        frame.apply([{"op": "does_not_exist"}])


def test_op_must_be_a_dict():
    with pytest.raises(OpentoonzMCPError):
        Frame(8, 8, background=None).apply(["rect"])


def test_transparent_background():
    frame = Frame(8, 8, background=None)
    assert frame.image.getpixel((0, 0)) == (0, 0, 0, 0)


def test_negative_size_rejected():
    with pytest.raises(OpentoonzMCPError):
        Frame(0, 10)
