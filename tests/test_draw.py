import pytest
from PIL import Image

from opentoonz_mcp import draw as draw_mod
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


def test_round_rect_op_rounds_its_corners():
    frame = Frame(40, 40, background=None).apply(
        [{"op": "round_rect", "xy": [0, 0, 39, 39], "radius": 12, "fill": "#ffffff"}]
    )
    assert frame.image.getpixel((20, 20))[3] == 255  # the middle is filled
    assert frame.image.getpixel((0, 0))[3] == 0  # the corner is rounded away


def test_star_op_fills_a_five_point_star():
    frame = Frame(41, 41, background=None).apply(
        [{"op": "star", "box": [0, 0, 40, 40], "points": 5, "inner": 0.45, "fill": "#ffffff"}]
    )
    assert frame.image.getpixel((20, 20))[3] == 255  # the body is filled
    assert frame.image.getpixel((0, 0))[3] == 0  # the box corner is outside the star


def test_arc_op_pieslice_fills_a_wedge():
    frame = Frame(41, 41, background=None).apply(
        [{"op": "arc", "box": [0, 0, 40, 40], "start": 0, "end": 180, "style": "pieslice", "fill": "#ffffff"}]
    )
    # PIL angles run clockwise from 3 o'clock, so 0..180 is the lower half.
    assert frame.image.getpixel((20, 35))[3] == 255
    assert frame.image.getpixel((20, 5))[3] == 0


def test_bezier_op_draws_a_curve():
    frame = Frame(41, 41, background=None).apply(
        [{"op": "bezier", "points": [[0, 40], [10, 0], [30, 0], [40, 40]], "fill": "#ffffff", "width": 3}]
    )
    assert frame.image.getchannel("A").getbbox() is not None


def test_curve_op_passes_through_its_points():
    frame = Frame(41, 41, background=None).apply(
        [{"op": "curve", "points": [[0, 20], [20, 0], [40, 20]], "fill": "#ffffff", "width": 3}]
    )
    assert frame.image.getchannel("A").getbbox() is not None
    assert frame.image.getpixel((0, 20))[3] == 255  # starts on its first point
    assert frame.image.getpixel((40, 20))[3] == 255  # ends on its last


def test_gradient_op_runs_top_to_bottom():
    frame = Frame(41, 41, background=None).apply(
        [{"op": "gradient", "xy": [0, 0, 40, 40], "colors": ["#000000", "#ffffff"], "direction": "vertical"}]
    )
    assert frame.image.getpixel((20, 0))[0] < 40
    assert frame.image.getpixel((20, 40))[0] > 215


def test_gradient_op_needs_at_least_two_colours():
    with pytest.raises(OpentoonzMCPError):
        Frame(8, 8, background=None).apply([{"op": "gradient", "xy": [0, 0, 8, 8], "colors": ["#000000"]}])


def test_op_must_be_a_dict():
    with pytest.raises(OpentoonzMCPError):
        Frame(8, 8, background=None).apply(["rect"])


def test_unknown_op_key_is_rejected():
    """A typo'd key must name itself, not surface a raw TypeError."""
    with pytest.raises(OpentoonzMCPError, match="bogus"):
        Frame(8, 8, background=None).apply([{"op": "rect", "xy": [0, 0, 1, 1], "bogus": 1}])


def test_op_key_error_lists_the_allowed_keys():
    with pytest.raises(OpentoonzMCPError) as info:
        Frame(8, 8, background=None).apply([{"op": "text", "xy": [0, 0], "text": "x", "colour": "#fff"}])
    message = str(info.value)
    assert "colour" in message and "fill" in message


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


# -- tweening (B1) -------------------------------------------------------------
def _sprite(tmp_path, name="sprite.png", size=20):
    path = tmp_path / name
    Image.new("RGBA", (size, size), (255, 0, 0, 255)).save(path)
    return path


def test_tween_interpolates_position(tmp_path):
    """xy is the drawing's centre, so a straight move lands on even steps."""
    sprite = _sprite(tmp_path)
    frames = draw_mod.tween(
        {"path": str(sprite), "xy": [10, 20]},
        {"path": str(sprite), "xy": [110, 20]},
        3,
        width=120,
        height=40,
    )
    assert len(frames) == 3
    assert frames[0].getpixel((10, 20))[:3] == (255, 0, 0)
    assert frames[1].getpixel((60, 20))[:3] == (255, 0, 0)
    assert frames[2].getpixel((110, 20))[:3] == (255, 0, 0)


def test_tween_interpolates_opacity(tmp_path):
    sprite = _sprite(tmp_path)
    frames = draw_mod.tween(
        {"path": str(sprite), "xy": [20, 20], "opacity": 1.0},
        {"path": str(sprite), "xy": [20, 20], "opacity": 0.0},
        3,
        width=40,
        height=40,
        background=None,
    )
    assert frames[0].getpixel((20, 20))[3] == 255
    assert frames[2].getpixel((20, 20))[3] == 0
    assert 0 < frames[1].getpixel((20, 20))[3] < 255


def test_tween_ease_slows_the_start(tmp_path):
    sprite = _sprite(tmp_path)
    start, end = {"path": str(sprite), "xy": [10, 20]}, {"path": str(sprite), "xy": [110, 20]}
    linear = draw_mod.tween(start, end, 5, width=120, height=40, background=None)
    eased = draw_mod.tween(start, end, 5, width=120, height=40, background=None, ease=True)

    def centre_x(frame):
        box = frame.getchannel("A").getbbox()
        return (box[0] + box[2]) / 2

    assert centre_x(eased[1]) < centre_x(linear[1])  # barely left the pose
    assert centre_x(eased[-1]) == centre_x(linear[-1])  # still arrives


def test_tween_needs_at_least_two_frames(tmp_path):
    sprite = _sprite(tmp_path)
    with pytest.raises(OpentoonzMCPError, match="at least 2"):
        draw_mod.tween({"path": str(sprite)}, {"path": str(sprite)}, 1)


def test_tween_rejects_a_missing_image(tmp_path):
    with pytest.raises(OpentoonzMCPError, match="Image not found"):
        draw_mod.tween({"path": str(tmp_path / "nope.png")}, {"path": str(tmp_path / "nope.png")}, 3)
