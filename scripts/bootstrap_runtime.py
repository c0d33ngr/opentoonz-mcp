#!/usr/bin/env python3
"""Extract an OpenToonz AppImage into a reusable runtime directory.

The AppImage launcher (``AppRun``) mangles CLI arguments and drops OpenToonz into
GUI mode, so opentoonz-mcp runs the *extracted* binary. This helper does the
one-time extraction and tells you what to set.

Example:
    python scripts/bootstrap_runtime.py --appimage ~/Downloads/OpenToonz.AppImage
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_DEST = Path("~/.local/share/opentoonz-mcp/runtime").expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--appimage", required=True, type=Path, help="path to OpenToonz.AppImage")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"where to extract (default: {DEFAULT_DEST})")
    args = parser.parse_args(argv)

    appimage = args.appimage.expanduser().resolve()
    if not appimage.is_file():
        print(f"error: not a file: {appimage}", file=sys.stderr)
        return 1

    dest = args.dest.expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    print(f"extracting {appimage.name} -> {dest} ...")
    try:
        subprocess.run([str(appimage), "--appimage-extract"], cwd=dest, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"error: extraction failed ({exc})", file=sys.stderr)
        return 1

    root = dest / "squashfs-root"
    ot_bin = root / "usr" / "bin" / "OpenToonz"
    tc_bin = root / "usr" / "bin" / "tcomposer"
    missing = [str(p) for p in (ot_bin, tc_bin) if not p.is_file()]
    if missing:
        print("error: extraction did not produce:", *missing, sep="\n  ", file=sys.stderr)
        return 1

    print("\nRuntime ready. Set this in your MCP client's environment:\n")
    print(f'  OPENTOONZ_RUNTIME="{root}"\n')
    print("Verify with the opentoonz_doctor tool, or:")
    print(
        f'  OPENTOONZ_RUNTIME="{root}" '
        'python -c "from opentoonz_mcp.context import get_context; '
        'print(get_context().runtime.version)"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
