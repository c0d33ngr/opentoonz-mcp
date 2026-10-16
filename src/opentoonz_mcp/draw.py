"""PIL-based frame authoring, so agents can *draw* and not only assemble.

OpenToonz's scripting API has no brush engine, so raster level frames are
produced here (RGBA PNGs) and then imported as a level. The API is a tiny,
intentional subset of PIL: flat vector-style primitives plus text.

A "frame" is a :class:`Frame`. A frame can also be built from a list of JSON
dicts ("ops"), which is what the MCP tool accepts:

    {"op": "rect",    "xy": [x0, y0, x1, y1], "fill": "#e0b184"}
    {"op": "round_rect", "xy": [x0, y0, x1, y1], "radius": 24, "fill": "#e0b184"}
    {"op": "ellipse", "box": [x0, y0, x1, y1], "fill": "#ff6b6b", "outline": "#000", "width": 4}
    {"op": "line",    "xy": [x0, y0, x1, y1], "fill": "#ffffff", "width": 3}
    {"op": "polygon", "points": [[x, y], ...], "fill": "#...", "outline": "#..."}
    {"op": "polyline","points": [[x, y], ...], "fill": "#...", "width": 3}
    {"op": "star",    "box": [x0, y0, x1, y1], "points": 5, "inner": 0.45, "fill": "#ffd166"}
    {"op": "arc",     "box": [x0, y0, x1, y1], "start": 0, "end": 180, "style": "pieslice", "fill": "#..."}
    {"op": "bezier",  "points": [[x, y], ... 4 control points], "fill": "#...", "width": 3}
    {"op": "curve",   "points": [[x, y], ...], "fill": "#...", "width": 3}
    {"op": "gradient","xy": [x0, y0, x1, y1], "colors": ["#101828", "#4cd964"], "direction": "vertical"}
    {"op": "text",    "xy": [x, y], "text": "Hi", "fill": "#fff", "size": 64, "anchor": "la"}
    {"op": "image",   "path": "/abs/art.png", "xy": [x, y], "size": [w, h], "opacity": 0.5}

The ``image`` op composites an existing RGBA PNG (optionally resized), which is
how art made elsewhere joins a drawn frame. ``curve`` is a Catmull-Rom spline
through every point; ``bezier`` is a single cubic through exactly four.

Colours accept ``#rgb``, ``#rrggbb``, ``#rrggbbaa``, or ``[r, g, b(, a)]``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .errors import OpentoonzMCPError

Color = tuple[int, int, int, int]

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_BACKGROUND = "#181a2e"

#: ``Frame.image`` is the PIL surface, so the ``image`` op needs a real name.
_OP_ALIASES = {"image": "paste_image"}

#: Allowed keys per op. Checking them turns a typo into a message that names the
#: key and the alternatives, instead of a raw ``TypeError`` from ``method(**kwargs)``
#: — and it keeps ``getattr`` from ever reaching an unrelated ``Frame`` method.
_OP_SCHEMA: dict[str, frozenset[str]] = {
    "rect": frozenset({"xy", "fill", "outline", "width"}),
    "ellipse": frozenset({"box", "fill", "outline", "width"}),
    "line": frozenset({"xy", "fill", "width"}),
    "polygon": frozenset({"points", "fill", "outline", "width"}),
    "polyline": frozenset({"points", "fill", "width"}),
    "round_rect": frozenset({"xy", "radius", "fill", "outline", "width"}),
    "star": frozenset({"box", "points", "inner", "rotation", "fill", "outline", "width"}),
    "arc": frozenset({"box", "start", "end", "style", "fill", "outline", "width"}),
    "bezier": frozenset({"points", "steps", "fill", "width"}),
    "curve": frozenset({"points", "steps", "fill", "width"}),
    "gradient": frozenset({"xy", "colors", "direction"}),
    "text": frozenset({"xy", "text", "fill", "size", "anchor"}),
    "paste_image": frozenset({"path", "xy", "size", "opacity"}),
}

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def parse_color(value: Any) -> Color:
    """Parse a colour into an ``(r, g, b, a)`` tuple."""
    if value is None:
        return (0, 0, 0, 0)
    if isinstance(value, (list, tuple)):
        vals = [int(v) for v in value]
        if len(vals) == 3:
            vals.append(255)
        if len(vals) != 4:
            raise OpentoonzMCPError(f"Colour sequence must have 3 or 4 values, got {value!r}")
        if any(v < 0 or v > 255 for v in vals):
            raise OpentoonzMCPError(f"Colour values must be in 0..255, got {value!r}")
        return (vals[0], vals[1], vals[2], vals[3])  # type: ignore[return-value]
    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) == 6:
        text += "ff"
    if len(text) != 8:
        raise OpentoonzMCPError(f"Unrecognised colour: {value!r}")
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]
    except ValueError as exc:  # pragma: no cover - defensive
        raise OpentoonzMCPError(f"Unrecognised colour: {value!r}") from exc


def _cubic(points: Sequence[tuple[float, float]], t: float) -> tuple[float, float]:
    """One point on a cubic Bézier, at parameter ``t`` in 0..1."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = points
    u = 1.0 - t
    a, b, c, d = u**3, 3 * u**2 * t, 3 * u * t**2, t**3
    return (a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3)


def _catmull_rom(p0, p1, p2, p3, t: float) -> tuple[float, float]:
    """One point on the Catmull-Rom spline segment ``p1``→``p2``, at ``t`` in 0..1."""
    t2, t3 = t * t, t * t * t
    return tuple(
        0.5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3)
        for a, b, c, d in zip(p0, p1, p2, p3, strict=True)
    )


def _sample_stops(stops: Sequence[Color], position: float) -> Color:
    """Blend a colour from evenly-spaced stops at ``position`` in 0..1."""
    if position <= 0:
        return stops[0]
    if position >= 1:
        return stops[-1]
    scaled = position * (len(stops) - 1)
    index = int(scaled)
    frac = scaled - index
    low, high = stops[index], stops[index + 1]
    return tuple(int(round(low[i] + (high[i] - low[i]) * frac)) for i in range(4))  # type: ignore[return-value]


@lru_cache(maxsize=64)
def _font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:  # pragma: no cover - corrupt font
                continue
    return ImageFont.load_default()


class Frame:
    """A single RGBA frame with simple drawing primitives."""

    def __init__(
        self,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        background: Any = DEFAULT_BACKGROUND,
    ) -> None:
        if width <= 0 or height <= 0:
            raise OpentoonzMCPError(f"Frame size must be positive, got {width}x{height}")
        self.width = int(width)
        self.height = int(height)
        fill = (0, 0, 0, 0) if background is None else parse_color(background)
        self.image = Image.new("RGBA", (self.width, self.height), fill)
        self.draw = ImageDraw.Draw(self.image)

    # -- primitives ---------------------------------------------------------
    def rect(self, xy: Sequence[float], fill: Any = None, outline: Any = None, width: int = 1) -> Frame:
        self.draw.rectangle(
            list(xy),
            fill=parse_color(fill) if fill is not None else None,
            outline=parse_color(outline) if outline is not None else None,
            width=int(width),
        )
        return self

    def ellipse(self, box: Sequence[float], fill: Any = None, outline: Any = None, width: int = 1) -> Frame:
        self.draw.ellipse(
            list(box),
            fill=parse_color(fill) if fill is not None else None,
            outline=parse_color(outline) if outline is not None else None,
            width=int(width),
        )
        return self

    def line(self, xy: Sequence[float], fill: Any = "#ffffff", width: int = 1) -> Frame:
        self.draw.line(list(xy), fill=parse_color(fill), width=int(width), joint="curve")
        return self

    def polygon(
        self, points: Iterable[Sequence[float]], fill: Any = None, outline: Any = None, width: int = 1
    ) -> Frame:
        pts = [tuple(p) for p in points]
        self.draw.polygon(
            pts,
            fill=parse_color(fill) if fill is not None else None,
            outline=parse_color(outline) if outline is not None else None,
            width=int(width),
        )
        return self

    def polyline(self, points: Iterable[Sequence[float]], fill: Any = "#ffffff", width: int = 1) -> Frame:
        pts = [tuple(p) for p in points]
        self.draw.line(pts, fill=parse_color(fill), width=int(width), joint="curve")
        return self

    def round_rect(
        self, xy: Sequence[float], radius: float = 0, fill: Any = None, outline: Any = None, width: int = 1
    ) -> Frame:
        self.draw.rounded_rectangle(
            list(xy),
            radius=float(radius),
            fill=parse_color(fill) if fill is not None else None,
            outline=parse_color(outline) if outline is not None else None,
            width=int(width),
        )
        return self

    def star(
        self,
        box: Sequence[float],
        points: int = 5,
        inner: float = 0.5,
        rotation: float = -90,
        fill: Any = None,
        outline: Any = None,
        width: int = 1,
    ) -> Frame:
        """A star with ``points`` tips inside ``box``, tips on the box edge.

        ``inner`` is the valley radius as a fraction of the tip radius, and
        ``rotation`` (degrees) turns the star; the default points the first tip up.
        """
        count = int(points)
        if count < 3:
            raise OpentoonzMCPError(f"star needs at least 3 points, got {points!r}")
        ratio = float(inner)
        if not 0.0 < ratio < 1.0:
            raise OpentoonzMCPError(f"star inner radius must be between 0 and 1, got {inner!r}")
        x0, y0, x1, y1 = (float(v) for v in box)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
        vertices = []
        for i in range(count * 2):
            angle = math.radians(float(rotation) + i * 180.0 / count)
            factor = 1.0 if i % 2 == 0 else ratio
            vertices.append((cx + rx * factor * math.cos(angle), cy + ry * factor * math.sin(angle)))
        self.draw.polygon(
            vertices,
            fill=parse_color(fill) if fill is not None else None,
            outline=parse_color(outline) if outline is not None else None,
            width=int(width),
        )
        return self

    def arc(
        self,
        box: Sequence[float],
        start: float = 0,
        end: float = 90,
        style: str = "pieslice",
        fill: Any = None,
        outline: Any = None,
        width: int = 1,
    ) -> Frame:
        """An arc/wedge inside ``box``, from ``start`` to ``end`` degrees.

        Angles run clockwise from 3 o'clock, as PIL defines them. ``style`` is
        ``pieslice`` (a filled wedge), ``chord`` (a filled segment), or ``arc``
        (a stroked curve, which uses ``fill`` as its stroke).
        """
        common = {"start": float(start), "end": float(end), "width": int(width)}
        if style == "arc":
            self.draw.arc(list(box), fill=parse_color(fill or "#ffffff"), **common)
        elif style in ("pieslice", "chord"):
            drawer = self.draw.pieslice if style == "pieslice" else self.draw.chord
            drawer(
                list(box),
                fill=parse_color(fill) if fill is not None else None,
                outline=parse_color(outline) if outline is not None else None,
                **common,
            )
        else:
            raise OpentoonzMCPError(f"arc style must be 'pieslice', 'chord' or 'arc', got {style!r}")
        return self

    def bezier(
        self, points: Iterable[Sequence[float]], steps: int = 32, fill: Any = "#ffffff", width: int = 1
    ) -> Frame:
        """A cubic Bézier stroked through its **four** control points."""
        control = [(float(p[0]), float(p[1])) for p in points]
        if len(control) != 4:
            raise OpentoonzMCPError(f"bezier needs exactly 4 control points, got {len(control)}")
        count = max(2, int(steps))
        path = [_cubic(control, i / (count - 1)) for i in range(count)]
        self.draw.line(path, fill=parse_color(fill), width=int(width), joint="curve")
        return self

    def curve(self, points: Iterable[Sequence[float]], steps: int = 16, fill: Any = "#ffffff", width: int = 1) -> Frame:
        """A smooth Catmull-Rom spline that **passes through** every point."""
        anchors = [(float(p[0]), float(p[1])) for p in points]
        if len(anchors) < 2:
            raise OpentoonzMCPError("curve needs at least 2 points")
        count = max(2, int(steps))
        path: list[tuple[float, float]] = []
        for index in range(len(anchors) - 1):
            before = anchors[index - 1] if index > 0 else anchors[index]
            after = anchors[index + 2] if index + 2 < len(anchors) else anchors[index + 1]
            for step in range(count):
                path.append(_catmull_rom(before, anchors[index], anchors[index + 1], after, step / count))
        path.append(anchors[-1])
        self.draw.line(path, fill=parse_color(fill), width=int(width), joint="curve")
        return self

    def gradient(self, xy: Sequence[float], colors: Iterable[Any], direction: str = "vertical") -> Frame:
        """Fill a rectangle with a linear gradient between two or more colours."""
        stops = [parse_color(colour) for colour in colors]
        if len(stops) < 2:
            raise OpentoonzMCPError("gradient needs at least two colours")
        if direction not in ("vertical", "horizontal"):
            raise OpentoonzMCPError(f"gradient direction must be 'vertical' or 'horizontal', got {direction!r}")
        x0, y0, x1, y1 = (float(v) for v in xy)
        horizontal = direction == "horizontal"
        # PIL rectangles are inclusive of both edges, so the ramp covers span + 1 rows.
        span = max(1, int((x1 - x0) if horizontal else (y1 - y0)) + 1)
        for i in range(span):
            colour = _sample_stops(stops, i / max(1, span - 1))
            if horizontal:
                self.draw.line([(x0 + i, y0), (x0 + i, y1)], fill=colour)
            else:
                self.draw.line([(x0, y0 + i), (x1, y0 + i)], fill=colour)
        return self

    def text(self, xy: Sequence[float], text: str, fill: Any = "#ffffff", size: int = 64, anchor: str = "la") -> Frame:
        self.draw.text(tuple(xy), str(text), fill=parse_color(fill), font=_font(int(size)), anchor=anchor)
        return self

    def paste_image(
        self,
        path: str | Path,
        xy: Sequence[float] = (0, 0),
        size: Sequence[float] | None = None,
        opacity: float | None = None,
    ) -> Frame:
        """Composite an existing RGBA PNG onto the frame at ``xy``.

        ``size`` rescales it to ``[width, height]``; ``opacity`` (0..1) fades it.
        Anything outside the frame is clipped.
        """
        source = Path(path)
        if not source.is_file():
            raise OpentoonzMCPError(f"Image not found: {path}")
        with Image.open(source) as opened:
            overlay = opened.convert("RGBA")
        if size is not None:
            width, height = (int(size[0]), int(size[1]))
            if width <= 0 or height <= 0:
                raise OpentoonzMCPError(f"size must be positive, got {size!r}")
            overlay = overlay.resize((width, height), Image.LANCZOS)
        if opacity is not None:
            factor = float(opacity)
            if not 0.0 <= factor <= 1.0:
                raise OpentoonzMCPError(f"opacity must be between 0 and 1, got {opacity!r}")
            overlay.putalpha(overlay.getchannel("A").point(lambda value: int(value * factor)))
        # Composite into a same-size layer so alpha_composite can do proper
        # "over" maths (a masked paste would halve the alpha of faded art), then
        # copy back in place — self.draw holds a reference to self.image.
        layer = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        layer.paste(overlay, (int(xy[0]), int(xy[1])))
        self.image.paste(Image.alpha_composite(self.image, layer))
        return self

    # -- composition --------------------------------------------------------
    def apply(self, ops: Iterable[dict[str, Any]]) -> Frame:
        """Apply a list of op dicts (see module docstring)."""
        for op in ops:
            if not isinstance(op, dict) or "op" not in op:
                raise OpentoonzMCPError(f"Each drawing op must be a dict with an 'op' key, got {op!r}")
            name = _OP_ALIASES.get(str(op["op"]), str(op["op"]))
            if name not in _OP_SCHEMA:
                raise OpentoonzMCPError(f"Unknown drawing op: {name!r}")
            kwargs = {k: v for k, v in op.items() if k != "op"}
            unknown = sorted(set(kwargs) - _OP_SCHEMA[name])
            if unknown:
                raise OpentoonzMCPError(
                    f"Unknown key(s) for drawing op {op['op']!r}: {', '.join(unknown)}. "
                    f"Allowed: {', '.join(sorted(_OP_SCHEMA[name]))}."
                )
            getattr(self, name)(**kwargs)
        return self

    def save(self, path: str | Path) -> Path:
        """Save the frame as an RGBA PNG and return its path.

        The parent directory is the caller's responsibility: the workspace owns
        its layout, and creating parents here would let an unvalidated path
        mkdir anywhere.
        """
        path = Path(path)
        self.image.save(path, format="PNG")
        return path


def draw_frame(
    path: str | Path,
    ops: Iterable[dict[str, Any]],
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    background: Any = DEFAULT_BACKGROUND,
) -> Path:
    """Draw one frame from ops and save it as an RGBA PNG."""
    frame = Frame(width=width, height=height, background=background).apply(ops)
    return frame.save(path)


# -- tweening ------------------------------------------------------------------
#: Keys a tween endpoint accepts, and the neutral value for each.
_PLACEMENT_DEFAULTS: dict[str, Any] = {
    "xy": (0.0, 0.0),
    "scale": 1.0,
    "rotation": 0.0,
    "opacity": 1.0,
}


def _placement(endpoint: dict[str, Any], *, label: str) -> dict[str, Any]:
    """Normalise one tween endpoint, checking every field up front."""
    if not isinstance(endpoint, dict) or "path" not in endpoint:
        raise OpentoonzMCPError(f"The {label} of a tween must be a dict with a 'path', got {endpoint!r}")
    unknown = sorted(set(endpoint) - {"path", *_PLACEMENT_DEFAULTS})
    if unknown:
        raise OpentoonzMCPError(
            f"Unknown key(s) for the {label} of a tween: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted({'path', *_PLACEMENT_DEFAULTS}))}."
        )
    source = Path(endpoint["path"])
    if not source.is_file():
        raise OpentoonzMCPError(f"Image not found: {source}")
    xy = endpoint.get("xy", _PLACEMENT_DEFAULTS["xy"])
    return {
        "path": source,
        "xy": (float(xy[0]), float(xy[1])),
        "scale": float(endpoint.get("scale", _PLACEMENT_DEFAULTS["scale"])),
        "rotation": float(endpoint.get("rotation", _PLACEMENT_DEFAULTS["rotation"])),
        "opacity": float(endpoint.get("opacity", _PLACEMENT_DEFAULTS["opacity"])),
    }


def _placed_layer(image: Image.Image, scale: float, rotation: float, opacity: float) -> Image.Image:
    """Scale, rotate (about its centre) and fade a copy of ``image``."""
    layer = image
    if scale != 1.0:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        layer = layer.resize(size, Image.LANCZOS)
    if rotation:
        layer = layer.rotate(rotation, resample=Image.BICUBIC, expand=True)
    if opacity != 1.0:
        layer = layer.copy()
        layer.putalpha(layer.getchannel("A").point(lambda value: int(value * opacity)))
    return layer


def tween(
    start: dict[str, Any],
    end: dict[str, Any],
    count: int,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    background: Any = DEFAULT_BACKGROUND,
    ease: bool = False,
) -> list[Image.Image]:
    """Render ``count`` frames moving one drawing from ``start`` to ``end``.

    OpenToonz's auto-inbetweening is GUI-only, so in-betweens are produced here
    and imported as a level. Each endpoint is ``{"path", "xy", "scale",
    "rotation", "opacity"}``; ``xy`` is the drawing's **centre**, so motion and
    rotation share one anchor. ``ease=True`` applies a smoothstep to the timing,
    so the move leaves and arrives gently instead of at a constant speed.
    """
    if count < 2:
        raise OpentoonzMCPError(f"a tween needs at least 2 frames, got {count!r}")
    first = _placement(start, label="start")
    last = _placement(end, label="end")
    with Image.open(first["path"]) as opened:
        art = opened.convert("RGBA")

    fill = (0, 0, 0, 0) if background is None else parse_color(background)
    frames: list[Image.Image] = []
    for index in range(int(count)):
        t = index / (count - 1)
        if ease:
            t = t * t * (3 - 2 * t)  # smoothstep
        blend = {key: first[key] + (last[key] - first[key]) * t for key in ("scale", "rotation", "opacity")}
        centre = (
            first["xy"][0] + (last["xy"][0] - first["xy"][0]) * t,
            first["xy"][1] + (last["xy"][1] - first["xy"][1]) * t,
        )
        canvas = Image.new("RGBA", (int(width), int(height)), fill)
        layer = _placed_layer(art, blend["scale"], blend["rotation"], blend["opacity"])
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        overlay.paste(layer, (round(centre[0] - layer.width / 2), round(centre[1] - layer.height / 2)))
        frames.append(Image.alpha_composite(canvas, overlay))
    return frames
