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
  channel is a ``<default>``; an animated one is a ``<keyframes>`` list whose
  entries are tagged with their interpolation type.
* Those channels are read, *rendered* and re-saved by OpenToonz, so a patched
  move is real and non-destructive rather than a paint-over.
* Camera position is in scene units (inches at 120 dpi: ``cameraRes/cameraSize``),
  ``sc`` is a scale the renderer *divides* by (0.5 renders twice as large), and
  ``rot`` is degrees about the frame centre.
* **Easing is real and writable.** ``<E>`` (EaseInOut) carries an ease *length in
  frames*, not a speed: ``m_speedOut.x`` on the segment's start keyframe is the
  ease-in, and ``m_speedIn.x`` — read only from the *next* keyframe's ``<prev>``
  child — is the (negative) ease-out. Both zero means "no easing", which renders
  exactly like linear, so an ease test must sample a **quartile**: ease and
  linear agree at the midpoint.

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

from opentoonz_mcp import bridge, draw, scenes  # noqa: E402
from opentoonz_mcp import render as render_mod  # noqa: E402
from opentoonz_mcp import workspace as workspace_mod  # noqa: E402
from opentoonz_mcp.context import get_context  # noqa: E402

WORKSPACE = "camera-probe"
SCENE = "probe"
SIZE = (640, 360)
#: A 40x40 marker, off-centre so pan and zoom are both visible.
MARKER = (280, 160, 320, 200)
FRAMES = 13  # rows 0..12, so the 25/50/75% samples land on whole rows 3/6/9
LAST = FRAMES - 1
#: frame numbers (1-based) whose channel value is 0, 0.25, 0.5, 0.75, 1.0 of the move
QUARTILES = (1, 4, 7, 10, 13)


def report(ok: bool, label: str, detail: str) -> bool:
    print(f"[{'ok' if ok else '!!'}] {label}: {detail}")
    return ok


def keyframe(tag: str, frame: int, value: float, speed_out: float = 0.0, speed_in: float | None = None) -> str:
    """One keyframe element, laid out the way OpenToonz writes it.

    ``speed_in`` (negative) becomes the ``<prev>`` child, which is where the
    ease-out of the *incoming* segment is stored.
    """
    inner = ""
    if speed_in is not None:
        inner += f"\n              <prev>\n                {value:g} {speed_in:g} \n              </prev>"
    if tag in ("E", "Ep"):
        fields = f"{frame} {value:g} {speed_out:g}"
    elif tag == "S":
        fields = f"{frame} {value:g} {speed_out:g} 0"
    else:
        fields = f"{frame} {value:g}"
    return f"\n            <{tag}>{inner}\n              {fields} \n            </{tag}>"


def patch(text: str, channels: dict[str, list[str]]) -> str:
    """Write animated channels into Camera1's pegbar, by hand."""
    start = text.index('<pegbar activeboth="yes" id="Camera1">')
    end = text.index("</pegbar>", start)
    block = text[start:end]
    for tag in ("x", "y", "sc", "rot"):
        block = re.sub(rf"<{tag}>[\s\S]*?</{tag}>", "", block)
    lines = []
    for tag, keyframes in channels.items():
        lines.append(
            f"\n        <{tag}>\n          <default>\n            0 \n          </default>\n          <keyframes>"
        )
        lines += keyframes
        lines.append("\n          </keyframes>")
        lines.append(f"\n        </{tag}>")
    anchor = block.index("<nodePos>")
    line_start = block.rfind("\n", 0, anchor) + 1
    block = block[:line_start] + "".join(lines) + "\n        " + block[line_start:]
    return text[:start] + block + text[end:]


def centre(frame: int, out_name: str) -> float | None:
    """Render one frame and return the marker's horizontal centre."""
    rendered = render_mod.render_frame(get_context(), WORKSPACE, SCENE, frame=frame, out_name=out_name)
    if not rendered.frames:
        return None
    with Image.open(rendered.frames[0]) as img:
        box = img.convert("RGBA").getchannel("A").getbbox()
    return None if box is None else (box[0] + box[2]) / 2


def aperture(out_name: str) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Render the last frame and return the marker's (centre, size)."""
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
    base = aperture("probe-base")
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
    checks = [
        (
            "x",
            {"x": [keyframe("L", 0, 0.0), keyframe("L", LAST, pan)]},
            lambda c, s: (c[0] - bx, c[1] - by),
            (-per_unit, 0.0),
            "pans left",
        ),
        (
            "y",
            {"y": [keyframe("L", 0, 0.0), keyframe("L", LAST, pan)]},
            lambda c, s: (c[0] - bx, c[1] - by),
            (0.0, per_unit),
            "pans down",
        ),
        (
            "sc",
            {"sc": [keyframe("L", 0, 1.0), keyframe("L", LAST, 0.5)]},
            lambda c, s: s,
            (2 * bw, 2 * bh),
            "renders twice as large",
        ),
        (
            "rot",
            {"rot": [keyframe("L", 0, 0.0), keyframe("L", LAST, 30.0)]},
            lambda c, s: s,
            (bw * 1.366, bh * 1.366),
            "rotates 30 degrees",
        ),
    ]
    print(f"\n== channels (frame {FRAMES} vs baseline) ==")
    for tag, channels, measure, expected, description in checks:
        scene_path.write_text(patch(text, channels), encoding="utf-8")
        observed = aperture(f"probe-{tag}")
        if observed is None:
            results.append(report(False, tag, "the render went empty"))
            continue
        deltas = measure(observed[0], observed[1])
        ok = all(abs(got - want) <= max(2.0, abs(want) * 0.03) for got, want in zip(deltas, expected, strict=True))
        results.append(report(ok, tag, f"{description}: measured {deltas[0]:.1f}, {deltas[1]:.1f} px"))

    # -- easing ----------------------------------------------------------------
    # A 12-frame pan, sampled at 0/25/50/75/100%. Ease and linear agree at 50%,
    # so the quartiles are the only place the difference shows.
    print("\n== easing (pan over 12 frames, sampled at 0/25/50/75/100%) ==")
    linear_keys = {"x": [keyframe("L", 0, 0.0), keyframe("L", LAST, pan)]}
    eased_keys = {
        "x": [
            keyframe("E", 0, 0.0, speed_out=6.0),
            keyframe("E", LAST, pan, speed_out=0.0, speed_in=-6.0),
        ]
    }

    def sample_curve(channels: dict[str, list[str]] | None, out_name: str) -> list[float] | None:
        if channels is not None:
            scene_path.write_text(patch(text, channels), encoding="utf-8")
        first = centre(QUARTILES[0], out_name)
        if first is None:
            return None
        curve = []
        for index, frame in enumerate(QUARTILES):
            value = first if index == 0 else centre(frame, out_name)
            if value is None:
                return None
            curve.append((first - value) / per_unit)  # fraction of the pan
        return curve

    linear_curve = sample_curve(linear_keys, "probe-ease-linear")
    eased_curve = sample_curve(eased_keys, "probe-ease-eased")
    if linear_curve is None or eased_curve is None:
        results.append(report(False, "easing", "a render went empty"))
    else:
        print("  linear: " + " ".join(f"{v:.3f}" for v in linear_curve))
        print("  eased : " + " ".join(f"{v:.3f}" for v in eased_curve))
        results.append(
            report(
                all(
                    abs(got - want) < 0.02 for got, want in zip(linear_curve, (0.0, 0.25, 0.5, 0.75, 1.0), strict=True)
                ),
                "linear is linear",
                "quartiles 0.250 / 0.500 / 0.750",
            )
        )
        # getEaseInOutValue with e0=e1=6 over x3=12 predicts 0.125 / 0.5 / 0.875
        results.append(
            report(
                all(
                    abs(got - want) < 0.02 for got, want in zip(eased_curve, (0.0, 0.125, 0.5, 0.875, 1.0), strict=True)
                ),
                "ease is eased",
                "quartiles 0.125 / 0.500 / 0.875",
            )
        )
        results.append(
            report(
                min(abs(eased_curve[1] - linear_curve[1]), abs(eased_curve[3] - linear_curve[3])) > 0.05,
                "ease differs from linear at the quartiles",
                f"{abs(eased_curve[1] - linear_curve[1]):.3f} of the move",
            )
        )

    print("\n== does OpenToonz keep what we wrote? ==")
    scene_path.write_text(patch(text, eased_keys), encoding="utf-8")
    code = f'var scene = new Scene("{scene_path}");\nscene.save("{scene_path}");\nprint("{bridge.OK_MARKER}");\n'
    kept = bridge.run_script_or_raise(context, workspace.root, code).ok
    saved = scene_path.read_text(encoding="utf-8")
    results.append(report(kept and saved.count("<keyframes>") == 1, "save round-trip", "the keyframes survived"))
    results.append(
        report(
            "<E>" in saved and "<prev>" in saved,
            "ease survives a save",
            "the <E> tag and its <prev> handle are still there",
        )
    )
    # Render the file OpenToonz itself wrote — no re-patching, so this is the
    # saved file's own behaviour.
    after = sample_curve(None, "probe-ease-after")
    if after is None or eased_curve is None:
        results.append(report(False, "ease still renders after a save", "a render went empty"))
    else:
        results.append(
            report(
                all(abs(got - want) < 0.02 for got, want in zip(after, eased_curve, strict=True)),
                "ease still renders after a save",
                "quartiles unchanged through the round-trip",
            )
        )
    results.append(
        report('id="Camera1"' in saved and "<xsheet>" in saved, "scene still well-formed", f"{len(saved)} bytes")
    )

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
