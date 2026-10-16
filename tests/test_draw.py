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


def test_save_does_not_create_missing_directories(tmp_path):
    """Saving must not mkdir an unvalidated path — the workspace owns the layout."""
    with pytest.raises(FileNotFoundError):
        draw_frame(tmp_path / "missing" / "a.png", [{"op": "rect", "xy": [0, 0, 1, 1]}])


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


def _art(path, colour="#ff0000", size=20):
    return draw_frame(
        path,
        [{"op": "rect", "xy": [0, 0, size, size], "fill": colour}],
        width=size,
        height=size,
        background=None,
    )


def test_image_op_composites_onto_the_frame(tmp_path):
    art = _art(tmp_path / "art.png")
    path = draw_frame(
        tmp_path / "c.png",
        [
            {"op": "rect", "xy": [0, 0, 64, 20], "fill": "#0000ff"},
            {"op": "image", "path": str(art), "xy": [10, 10]},
        ],
        width=64,
        height=64,
        background=None,
    )
    with Image.open(path) as img:
        assert img.getpixel((5, 5)) == (0, 0, 255, 255)
        assert img.getpixel((15, 15)) == (255, 0, 0, 255)
        assert img.getpixel((5, 40)) == (0, 0, 0, 0)
        assert img.getpixel((63, 63)) == (0, 0, 0, 0)


def test_image_op_resizes(tmp_path):
    art = _art(tmp_path / "art.png")
    path = draw_frame(
        tmp_path / "c.png",
        [{"op": "image", "path": str(art), "xy": [0, 0], "size": [40, 40]}],
        width=64,
        height=64,
        background=None,
    )
    with Image.open(path) as img:
        assert img.getpixel((35, 35)) == (255, 0, 0, 255)
        assert img.getpixel((45, 45)) == (0, 0, 0, 0)


def test_image_op_is_clipped_at_the_edge(tmp_path):
    art = _art(tmp_path / "art.png")
    path = draw_frame(
        tmp_path / "c.png",
        [{"op": "image", "path": str(art), "xy": [-10, -10]}],
        width=64,
        height=64,
        background=None,
    )
    with Image.open(path) as img:
        assert img.getpixel((0, 0)) == (255, 0, 0, 255)
        assert img.getpixel((15, 15)) == (0, 0, 0, 0)


def test_image_op_opacity_fades(tmp_path):
    art = _art(tmp_path / "art.png")
    path = draw_frame(
        tmp_path / "c.png",
        [{"op": "image", "path": str(art), "xy": [0, 0], "opacity": 0.5}],
        width=64,
        height=64,
        background=None,
    )
    with Image.open(path) as img:
        assert img.getpixel((5, 5))[3] == 127


def test_image_op_opacity_over_an_opaque_base(tmp_path):
    art = _art(tmp_path / "art.png")
    path = draw_frame(
        tmp_path / "c.png",
        [
            {"op": "rect", "xy": [0, 0, 64, 64], "fill": "#0000ff"},
            {"op": "image", "path": str(art), "xy": [0, 0], "opacity": 0.5},
        ],
        width=64,
        height=64,
        background=None,
    )
    with Image.open(path) as img:
        pixel = img.getpixel((5, 5))
        assert pixel[3] == 255  # the blue base stays opaque
        assert pixel[0] == 127 and pixel[2] == 128  # red and blue blended


def test_image_op_missing_file_raises(tmp_path):
    with pytest.raises(OpentoonzMCPError, match="Image not found"):
        Frame(8, 8, background=None).apply([{"op": "image", "path": str(tmp_path / "nope.png")}])


@pytest.mark.parametrize("kwargs", [{"size": [0, 10]}, {"opacity": 2}, {"opacity": -1}])
def test_image_op_rejects_bad_arguments(tmp_path, kwargs):
    art = _art(tmp_path / "art.png")
    with pytest.raises(OpentoonzMCPError):
        Frame(32, 32, background=None).apply([{"op": "image", "path": str(art), "xy": [0, 0], **kwargs}])
