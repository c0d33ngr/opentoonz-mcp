"""Fetch a usable OpenToonz runtime from an AppImage.

The AppImage launcher (``AppRun``) mangles CLI arguments and drops OpenToonz into
GUI mode, so opentoonz-mcp always runs the *extracted* binary. This does the
one-time extraction and reports the ``OPENTOONZ_RUNTIME`` value to use::

    opentoonz-mcp fetch-runtime --appimage ~/Downloads/OpenToonz.AppImage

It lives in the package (not just in ``scripts/``) so that an installed copy —
``pipx install``, ``uvx`` — can bootstrap itself without a clone.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .errors import OpentoonzMCPError

#: Where the extracted runtime goes unless told otherwise.
DEFAULT_DEST = Path("~/.local/share/opentoonz-mcp/runtime").expanduser()

#: Binaries the extracted runtime must contain for the tools to work.
REQUIRED_BINARIES = ("OpenToonz", "tcomposer")


def fetch_runtime(appimage: str | Path, dest: str | Path | None = None) -> Path:
    """Extract ``appimage`` under ``dest`` and return the runtime root.

    Raises :class:`OpentoonzMCPError` naming the offending path if the AppImage
    is missing, or if the extraction does not produce the binaries the tools
    need — a partial runtime is worse than none, because it fails later.
    """
    source = Path(appimage).expanduser().resolve()
    if not source.is_file():
        raise OpentoonzMCPError(f"Not an AppImage: {source}")

    target = Path(dest).expanduser().resolve() if dest is not None else DEFAULT_DEST
    target.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([str(source), "--appimage-extract"], cwd=target, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OpentoonzMCPError(f"Extracting {source.name} failed: {exc}") from exc

    root = target / "squashfs-root"
    missing = [name for name in REQUIRED_BINARIES if not (root / "usr" / "bin" / name).is_file()]
    if missing:
        raise OpentoonzMCPError(f"{source.name} extracted without {', '.join(missing)} — is it an OpenToonz AppImage?")
    return root


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add this command's arguments to ``parser``."""
    parser.add_argument("--appimage", required=True, type=Path, help="path to OpenToonz.AppImage")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"where to extract (default: {DEFAULT_DEST})")


def run(args: argparse.Namespace) -> int:
    """Carry out a parsed ``fetch-runtime`` command; return an exit code."""
    try:
        root = fetch_runtime(args.appimage, args.dest)
    except OpentoonzMCPError as exc:
        print(f"error: {exc}", file=sys.stderr)
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


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point, for ``python -m`` and the scripts/ shim."""
    parser = argparse.ArgumentParser(
        prog="opentoonz-mcp fetch-runtime",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_arguments(parser)
    return run(parser.parse_args(argv))
