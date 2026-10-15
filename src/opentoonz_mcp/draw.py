"""PIL-based frame authoring, so agents can *draw* and not only assemble.

OpenToonz's scripting API has no brush engine, so raster level frames are
produced here (RGBA PNGs) and then imported as a level. The API is a tiny,
intentional subset of PIL: flat vector-style primitives plus text.

A "frame" is a :class:`Frame`. A frame can also be built from a list of JSON
dicts ("ops"), which is what the MCP tool accepts:

    {"op": "rect",    "xy": [x0, y0, x1, y1], "fill": "#e0b184"}
    {"op": "ellipse", "box": [x0, y0, x1, y1], "fill": "#ff6b6b", "outline": "#000", "width": 4}
    {"op": "line",    "xy": [x0, y0, x1, y1], "fill": "#ffffff", "width": 3}
    {"op": "polygon", "points": [[x, y], ...], "fill": "#...", "outline": "#..."}
    {"op": "polyline","points": [[x, y], ...], "fill": "#...", "width": 3}
    {"op": "text",    "xy": [x, y], "text": "Hi", "fill": "#fff", "size": 64, "anchor": "la"}

Colours accept ``#rgb``, ``#rrggbb``, ``#rrggbbaa``, or ``[r, g, b(, a)]``.
"""

from __future__ import annotations

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

    def text(self, xy: Sequence[float], text: str, fill: Any = "#ffffff", size: int = 64, anchor: str = "la") -> Frame:
        self.draw.text(tuple(xy), str(text), fill=parse_color(fill), font=_font(int(size)), anchor=anchor)
        return self

    # -- composition --------------------------------------------------------
    def apply(self, ops: Iterable[dict[str, Any]]) -> Frame:
        """Apply a list of op dicts (see module docstring)."""
        for op in ops:
            if not isinstance(op, dict) or "op" not in op:
                raise OpentoonzMCPError(f"Each drawing op must be a dict with an 'op' key, got {op!r}")
            name = str(op["op"])
            method = getattr(self, name, None)
            if method is None or name.startswith("_"):
                raise OpentoonzMCPError(f"Unknown drawing op: {name!r}")
            kwargs = {k: v for k, v in op.items() if k != "op"}
            method(**kwargs)
        return self

    def save(self, path: str | Path) -> Path:
        """Save the frame as an RGBA PNG and return its path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
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
