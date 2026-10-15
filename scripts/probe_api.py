#!/usr/bin/env python3
"""Probe the installed OpenToonz scripting API and report what is available.

This is a development tool, not an MCP tool. It answers the questions that gate
feature work, most of which cannot be determined from the documentation: the
scripting surface is a *subset* of the GUI, and it changes between releases.

What it establishes (as of OpenToonz 1.8.0 on Linux):

* ``scene.setCameraSize`` / ``setFrameCount`` / ``removeLevel`` / ``clearCell``
  do **not** exist — the JS API cannot resize a scene or delete anything.
* ``scene.setCell(row, col, "<level name>", fid)`` **does** accept a name, and
  raises a clear error for an unknown level.
* ``scene.loadLevel(name, "<path>/<level>..png")`` loads **SVG** as a Vector level.
* ``level.setFrame(fid, image)`` on a loaded level **is** visible to the renderer.
* Scene settings (``cameraRes``, ``cameraSize``, ``fps``, ``framecount``) live in
  the ``.tnz`` file, which is plain XML — and a JS scene round-trip preserves
  edits made to it. That is how :mod:`opentoonz_mcp.scenes` resizes scenes.

Re-run it after an OpenToonz upgrade to see whether new capabilities appeared::

    OPENTOONZ_RUNTIME=/path/to/squashfs-root python scripts/probe_api.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

from opentoonz_mcp import bridge, draw  # noqa: E402
from opentoonz_mcp import render as render_mod  # noqa: E402
from opentoonz_mcp import workspace as workspace_mod  # noqa: E402
from opentoonz_mcp.context import get_context  # noqa: E402

OK = bridge.OK_MARKER

#: Identifiers worth asking ``typeof`` about. ``typeof`` never throws for an
#: undeclared identifier, so this safely inventories the global object.
CANDIDATE_GLOBALS = (
    "Scene",
    "Level",
    "Image",
    "Renderer",
    "Camera",
    "FilePath",
    "ImageBuilder",
    "OutlineVectorizer",
    "CenterlineVectorizer",
    "Rasterizer",
    "ToonzRasterConverter",
    "Transform",
    "Cell",
    "Column",
    "Xsheet",
    "Project",
    "Palette",
    "Style",
    "Sound",
    "Audio",
)

#: Methods looked for on a ``Scene`` instance (``typeof`` is safe when absent).
SCENE_METHODS = (
    "frameCount",
    "columnCount",
    "getLevels",
    "getCell",
    "setCell",
    "save",
    "load",
    "setCameraSize",
    "getCameraSize",
    "setCameraRect",
    "setFrameRate",
    "setFps",
    "setFrameCount",
    "setFieldSize",
    "setOutputSize",
    "removeLevel",
    "deleteLevel",
    "clearCell",
    "removeCell",
)

#: Properties/methods looked for on a loaded ``Level``.
LEVEL_MEMBERS = (
    "name",
    "type",
    "path",
    "frameCount",
    "getPath",
    "getFrameCount",
    "getFrame",
    "getFrameId",
    "setFrame",
    "save",
    "saveAs",
    "load",
    "getPalette",
    "isReadOnly",
)

SVG_RECT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">'
    '<rect x="20" y="20" width="160" height="160" fill="#ff0000"/></svg>'
)
SVG_PATH = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">'
    '<path d="M20,20 L180,20 L180,180 L20,180 Z" fill="#00ff00"/></svg>'
)


def js(value: object) -> str:
    """Quote a value for embedding in JavaScript."""
    return json.dumps(str(value))


def solid(path: Path, colour: str, size: int = 200) -> Path:
    """Write a solid-colour RGBA PNG."""
    return draw.draw_frame(
        path,
        [{"op": "rect", "xy": [0, 0, size, size], "fill": colour}],
        width=size,
        height=size,
        background=None,
    )


def build_js(assets: dict[str, Path]) -> str:
    """The introspection + behaviour script."""
    typeof_lines = "\n".join(f'P("GLOBAL.{n}", typeof {n});' for n in CANDIDATE_GLOBALS)
    scene_lines = "\n".join(f'has(scene, "scene", "{m}");' for m in SCENE_METHODS)
    level_lines = "\n".join(f'has(level, "level", "{m}");' for m in LEVEL_MEMBERS)

    return f"""
// ---------- helpers (QScriptEngine is ES5; keep it plain) ----------
function P(key, value) {{ print("PROBE|" + key + "|" + value); }}
function safe(fn) {{ try {{ return String(fn()); }} catch (e) {{ return "ERR:" + e; }} }}
function names(obj) {{
  var seen = {{}}, key, out = [];
  for (key in obj) {{ seen[key] = 1; }}
  if (typeof Object.getOwnPropertyNames === "function") {{
    var own = Object.getOwnPropertyNames(obj);
    for (var i = 0; i < own.length; i++) {{ seen[own[i]] = 1; }}
  }}
  for (key in seen) {{ out.push(key); }}
  return out.sort().join(",");
}}
function has(obj, label, name) {{ P(label + "." + name, typeof obj[name]); }}

// ---------- global inventory ----------
P("GLOBALS", safe(function () {{ return names(this); }}));
{typeof_lines}

// ---------- Scene capabilities ----------
var scene = new Scene();
{scene_lines}

// ---------- Level + Image ----------
var level = scene.loadLevel("probelevel", {js(assets["seq"])});
{level_lines}
var img = new Image({js(assets["red"])});
P("MEMBERS.Image", safe(function () {{ return names(img); }}));

// ---------- does loading an existing name duplicate the level? ----------
P("loadLevel.duplicate", safe(function () {{
  var before = scene.getLevels().length;
  scene.loadLevel("probelevel", {js(assets["seq"])});
  var after = scene.getLevels().length;
  return "levels before=" + before + " after=" + after;
}}));

// ---------- setCell by level name ----------
P("setCell.byName", safe(function () {{ scene.setCell(0, 3, "probelevel", 1); return "ok"; }}));
P("setCell.missingName", safe(function () {{ scene.setCell(0, 4, "no_such_level", 1); return "ok"; }}));

// ---------- SVG -> Vector level ----------
P("loadLevel.svg_rect", safe(function () {{
  var lv = scene.loadLevel("svgrect", {js(assets["svg_rect"])});
  return "ok type=" + lv.type + " frames=" + lv.frameCount;
}}));
P("loadLevel.svg_path", safe(function () {{
  var lv = scene.loadLevel("svgpath", {js(assets["svg_path"])});
  return "ok type=" + lv.type + " frames=" + lv.frameCount;
}}));

print("{OK}");
"""


def collect(stdout: str) -> dict[str, str]:
    """Parse ``PROBE|key|value`` lines out of the script output."""
    found: dict[str, str] = {}
    for line in stdout.splitlines():
        if line.startswith("PROBE|"):
            _, key, value = line.split("|", 2)
            found[key] = value
    return found


def show(found: dict[str, str], prefix: str) -> None:
    for key in sorted(found):
        if key.startswith(prefix):
            print(f"    {key:34} {found[key]}")


def check_svg_renders(ctx, ws: workspace_mod.Workspace) -> None:
    """Q2b: a Vector (SVG) level must actually rasterise during a render."""
    print("\n[2b] does an SVG/Vector level render?")
    scene_path = ws.scene_path("svgcheck")
    code = "\n".join(
        [
            "var scene = new Scene();",
            f'var rect = scene.loadLevel("svgrect", {js(ws.root / "assets" / "shape_rect.svg")});',
            f'var path = scene.loadLevel("svgpath", {js(ws.root / "assets" / "shape_path.svg")});',
            "scene.setCell(0, 0, rect, 1);",
            "scene.setCell(0, 1, path, 1);",
            f"scene.save({js(scene_path)});",
            f'print("{OK}");',
        ]
    )
    result = bridge.run_script(ctx, ws.root, code)
    if not result.ok:
        print("     setup failed:", result.summary(out_tail=500))
        return
    rendered = render_mod.render_frames(ctx, ws.name, "svgcheck", out_name="svgcheck")
    if not rendered.frames:
        print("     render produced no frames:", rendered.log[-300:])
        return
    with Image.open(rendered.frames[0]) as image:
        rgba = image.convert("RGBA")
        opaque = sum(1 for px in rgba.getdata() if px[3] > 0)
    print(f"     {rendered.frames[0].name} {rgba.size} opaque_pixels={opaque}")
    print("     -> non-zero means vector levels render" if opaque else "     -> BLANK: vector levels do not rasterise")


def check_setframe(ctx, ws: workspace_mod.Workspace, assets: dict[str, Path]) -> None:
    """Q3: is ``level.setFrame`` on a loaded level visible to the renderer?"""
    print("\n[3] level.setFrame persistence (the render is the ground truth)")
    seq = ws.drawings / "persist..png"
    for index, colour in enumerate(("#0000ff", "#00ff00", "#ffff00"), start=1):
        solid(ws.drawings / f"persist.{index:04d}.png", colour)

    scene_path = ws.scene_path("persist")
    code = "\n".join(
        [
            "var scene = new Scene();",
            f'var level = scene.loadLevel("persist", {js(seq)});',
            "for (var r = 0; r < level.frameCount; r++) { scene.setCell(r, 0, level, r + 1); }",
            f"scene.save({js(scene_path)});",
            f'print("{OK}");',
        ]
    )
    if not bridge.run_script(ctx, ws.root, code).ok:
        print("     setup failed")
        return

    code = "\n".join(
        [
            f"var scene = new Scene({js(scene_path)});",
            f"var img = new Image({js(assets['red'])});",
            "var levels = scene.getLevels();",
            "for (var i = 0; i < levels.length; i++) {",
            "  if (levels[i].name === 'persist') { levels[i].setFrame(2, img); }",
            "}",
            f"scene.save({js(scene_path)});",
            f'print("{OK}");',
        ]
    )
    if not bridge.run_script(ctx, ws.root, code).ok:
        print("     setFrame script failed")
        return

    rendered = render_mod.render_frames(ctx, ws.name, "persist", out_name="persist")
    if not rendered.frames:
        print("     render produced no frames")
        return
    for path in rendered.frames:
        with Image.open(path) as image:
            pixel = image.convert("RGBA").getpixel((100, 100))
        print(f"     {path.name}: pixel@100,100={pixel}")
    print("     -> frame 2 red means setFrame persisted; blue/green means it did not")


def check_camera_res(ctx, ws: workspace_mod.Workspace) -> None:
    """Q1b: ``cameraRes`` lives in the ``.tnz`` XML — does patching it stick?"""
    print("\n[1b] scene resize by patching .tnz XML (the JS API has no setter)")
    scene_path = ws.scene_path("resize")
    code = "\n".join(
        [
            "var scene = new Scene();",
            f'var level = scene.loadLevel("probelevel", {js(ws.drawings / "probelevel..png")});',
            "scene.setCell(0, 0, level, 1);",
            f"scene.save({js(scene_path)});",
            f'print("{OK}");',
        ]
    )
    if not bridge.run_script(ctx, ws.root, code).ok:
        print("     setup failed")
        return

    before = render_mod.render_frames(ctx, ws.name, "resize", out_name="resize_before")
    text = scene_path.read_text(encoding="utf-8")
    patched = text.replace("1920 1080", "640 360", 1)
    if patched == text:
        print("     cameraRes not found in the .tnz")
        return
    scene_path.write_text(patched, encoding="utf-8")

    after = render_mod.render_frames(ctx, ws.name, "resize", out_name="resize_after")
    sizes = []
    for label, result in (("before", before), ("after", after)):
        size = Image.open(result.frames[0]).size if result.frames else None
        sizes.append(f"{label}={size}")
    print("     " + "  ".join(sizes))

    # A JS round-trip must not clobber the edit.
    code = "\n".join(
        [
            f"var scene = new Scene({js(scene_path)});",
            "scene.setCell(1, 1, 'probelevel', 3);",
            f"scene.save({js(scene_path)});",
            f'print("{OK}");',
        ]
    )
    bridge.run_script(ctx, ws.root, code)
    roundtrip = render_mod.render_frames(ctx, ws.name, "resize", out_name="resize_roundtrip")
    size = Image.open(roundtrip.frames[0]).size if roundtrip.frames else None
    print(f"     after JS round-trip={size}")
    print("     -> 'after' 640x360 means patching works and survives a scene save")


def main() -> int:
    ctx = get_context()
    print("runtime:", ctx.runtime.version)
    ws, _ = workspace_mod.create(ctx, "api-probe")

    assets = ws.root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for index, colour in enumerate(("#0000ff", "#00ff00", "#ffff00"), start=1):
        solid(ws.drawings / f"probelevel.{index:04d}.png", colour)
    red = solid(assets / "red.png", "#ff0000")
    svg_rect = assets / "shape_rect.svg"
    svg_rect.write_text(SVG_RECT, encoding="utf-8")
    svg_path = assets / "shape_path.svg"
    svg_path.write_text(SVG_PATH, encoding="utf-8")

    result = bridge.run_script(
        ctx,
        ws.root,
        build_js({"seq": ws.drawings / "probelevel..png", "red": red, "svg_rect": svg_rect, "svg_path": svg_path}),
        timeout=180,
    )
    found = collect(result.stdout)
    if not result.ok:
        print("script did not complete:", result.failure)

    print("\n[1] globals")
    show(found, "GLOBAL.")
    print("\n[2] scene methods")
    show(found, "scene.")
    print("\n[3] level members")
    show(found, "level.")
    print("\n[4] image members")
    show(found, "MEMBERS.")
    print("\n[5] behaviour")
    behaviour = (
        "loadLevel.duplicate",
        "setCell.byName",
        "setCell.missingName",
        "loadLevel.svg_rect",
        "loadLevel.svg_path",
    )
    for key in behaviour:
        print(f"    {key:34} {found.get(key, '(missing)')}")

    check_svg_renders(ctx, ws)
    check_setframe(ctx, ws, {"red": red})
    check_camera_res(ctx, ws)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
