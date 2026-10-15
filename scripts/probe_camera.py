#!/usr/bin/env python3
"""Probe whether the OpenToonz camera can be animated by editing the ``.tnz``.

This is a development tool, not an MCP tool. It exists because the camera is the
one part of a scene the scripting API cannot reach at all: there is no ``Camera``
object, no ``scene.setCameraPosition``, and no stage-object setter anywhere in
the JS surface. If camera moves are to be possible headlessly at all, they have
to be written into the scene file.

What it establishes (as of OpenToonz 1.8.0 on Linux):

* The camera is a **stage object**: ``<pegbar activeboth="yes" id="Camera1">``
  inside the xsheet's ``<pegbars>``, carrying its own ``<camera>`` block.
* Its motion lives in *channels* (``x``, ``y``, ``sc``, ``rot``...). A static
  channel is a ``<default>``; an animated one is a ``<keyframes>`` list of
  ``<L>frame value</L>`` (``L`` = linear).
* Those channels are read, *rendered* and re-saved by OpenToonz, so a patched
  move is real and non-destructive rather than a paint-over.
* Camera position is in scene units (inches at 120 dpi: ``cameraRes/cameraSize``),
  ``sc`` is a scale the renderer *divides* by (0.5 renders twice as large), and
  ``rot`` is degrees about the frame centre.

The probe writes its own XML rather than calling
:func:`opentoonz_mcp.scenes.camera_move`, so it measures the mechanism itself and
stays a useful check of the library. Re-run it after an OpenToonz upgrade::

    OPENTOONZ_RUNTIME=/path/to/squashfs-root python scripts/probe_camera.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

from opentoonz_mcp import (  # noqa: E402
    bridge,
    draw,
    scenes,  # noqa: E402
)
from opentoonz_mcp import render as render_mod  # noqa: E402
from opentoonz_mcp import workspace as workspace_mod  # noqa: E402
from opentoonz_mcp.context import get_context  # noqa: E402

WORKSPACE = "camera-probe"
SCENE = "probe"
SIZE = (640, 360)
#: A 40x40 marker, off-centre so pan and zoom are both visible.
MARKER = (280, 160, 320, 200)
FRAMES = 12


def report(ok: bool, label: str, detail: str) -> bool:
    print(f"[{'ok' if ok else '!!'}] {label}: {detail}")
    return ok


def patch(text: str, channels: dict[str, list[tuple[int, float]]]) -> str:
    """Write animated channels into Camera1's pegbar, by hand."""
    start = text.index('<pegbar activeboth="yes" id="Camera1">')
    end = text.index("</pegbar>", start)
    block = text[start:end]
    for tag in ("x", "y", "sc", "rot"):
        block = re.sub(rf"<{tag}>[\s\S]*?</{tag}>", "", block)
    lines = []
    for tag, rows in channels.items():
        lines += [f"\n        <{tag}>\n          <default>\n            {rows[0][1]:g} \n          </default>"]
        lines.append("          <keyframes>")
        lines += [f"\n            <L>\n              {frame} {value:g} \n            </L>" for frame, value in rows]
        lines += ["\n            </keyframes>", f"\n          </{tag}>"]
    anchor = block.index("<nodePos>")
    line_start = block.rfind("\n", 0, anchor) + 1
    block = block[:line_start] + "".join(lines) + "\n        " + block[line_start:]
    return text[:start] + block + text[end:]


def aperture(ws: workspace_mod.Workspace, out_name: str) -> tuple[float, float] | None:
    """Render frame 1 and frame FRAMES, and return the marker's size/centre drift."""
    rendered = render_mod.render_frame(get_context(), WORKSPACE, SCENE, frame=FRAMES, out_name=out_name)
    if not rendered.frames:
        return None
    with Image.open(rendered.frames[0]) as img:
        box = img.convert("RGBA").getchannel("A").getbbox()
    if box is None:
        return None
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), (box[2] - box[0], box[3] - box[1])


def main() -> int:
    context = get_context()
    context.prepare()
    workspace, _ = workspace_mod.create(context, WORKSPACE)

    scenes.scene_new(context, WORKSPACE, SCENE, width=SIZE[0], height=SIZE[1])
    marker = workspace.drawings / "marker.0001.png"
    draw.draw_frame(
        marker,
        [{"op": "rect", "xy": list(MARKER), "fill": "#ff6b6b"}],
        width=SIZE[0],
        height=SIZE[1],
        background=None,
    )
    scenes.import_level(context, WORKSPACE, "marker", [str(marker)], SCENE)
    scenes.set_exposure(context, WORKSPACE, SCENE, "marker", [FRAMES])

    scene_path = workspace.scene_path(SCENE)
    text = scene_path.read_text(encoding="utf-8")
    results: list[bool] = []

    print("== scene ==")
    per_unit = scenes._px_per_inch(text)
    results.append(report("Camera1" in text, "camera stage object", "found" if "Camera1" in text else "MISSING"))
    results.append(report(per_unit > 0, "pixels per scene unit", f"{per_unit:g}"))

    print("\n== baseline (no camera keys) ==")
    base = aperture(workspace, "probe-base")
    if base is None:
        report(False, "baseline render", "no visible marker — cannot probe")
        return 1
    (bx, by), (bw, bh) = base
    results.append(
        report(abs(bx - (MARKER[0] + MARKER[2]) / 2) < 2, "marker composites 1:1", f"centre ({bx:g}, {by:g})")
    )

    # Each channel is written alone, so the effects can be attributed. One scene
    # unit is per_unit pixels, measured above.
    pan = 1.0
    keys = FRAMES - 1
    checks = [
        (
            "x",
            {"x": [(0, 0.0), (keys, pan)]},
            lambda c, s: (c[0] - bx, c[1] - by),
            (-per_unit, 0.0),
            "pans left",
        ),
        (
            "y",
            {"y": [(0, 0.0), (keys, pan)]},
            lambda c, s: (c[0] - bx, c[1] - by),
            (0.0, per_unit),
            "pans down",
        ),
        ("sc", {"sc": [(0, 1.0), (keys, 0.5)]}, lambda c, s: s, (2 * bw, 2 * bh), "renders twice as large"),
        ("rot", {"rot": [(0, 0.0), (keys, 30.0)]}, lambda c, s: s, (bw * 1.366, bh * 1.366), "rotates 30 degrees"),
    ]
    print(f"\n== channels (frame {FRAMES} vs baseline) ==")
    for tag, channels, measure, expected, description in checks:
        scene_path.write_text(patch(text, channels), encoding="utf-8")
        observed = aperture(workspace, f"probe-{tag}")
        if observed is None:
            results.append(report(False, tag, "the render went empty"))
            continue
        deltas = measure(observed[0], observed[1])
        ok = all(abs(got - want) <= max(2.0, abs(want) * 0.03) for got, want in zip(deltas, expected, strict=True))
        results.append(report(ok, tag, f"{description}: measured {deltas[0]:.1f}, {deltas[1]:.1f} px"))

    print("\n== does OpenToonz keep what we wrote? ==")
    prepared = patch(text, {"x": [(0, 0.0), (keys, pan)], "sc": [(0, 1.0), (keys, 0.5)]})
    scene_path.write_text(prepared, encoding="utf-8")
    code = f'var scene = new Scene("{scene_path}");\nscene.save("{scene_path}");\nprint("{bridge.OK_MARKER}");\n'
    kept = bridge.run_script_or_raise(context, workspace.root, code).ok
    saved = scene_path.read_text(encoding="utf-8")
    results.append(report(kept and saved.count("<keyframes>") == 2, "save round-trip", "keyframes preserved"))
    results.append(
        report('id="Camera1"' in saved and "<xsheet>" in saved, "scene still well-formed", f"{len(saved)} bytes")
    )

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
