"""Locate the headless OpenToonz runtime (``OpenToonz`` + ``tcomposer``).

The Linux AppImage is a squashfs bundle; the ``AppRun`` launcher mangles CLI
arguments, so we always run the extracted inner binary directly. This module
finds that binary, its ``tcomposer`` sibling, and the bundled ``stuff`` template.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .errors import RuntimeNotFoundError

OT_BINARY = "OpenToonz"
TCOMPOSER_BINARY = "tcomposer"

#: Where the binaries may sit relative to a runtime root.
_BIN_SUBPATHS: tuple[tuple[str, ...], ...] = (("usr", "bin"), ("bin",), ())

#: Where the canonical ``stuff`` template may sit relative to a runtime root.
_STUFF_SUBPATHS: tuple[tuple[str, ...], ...] = (
    ("usr", "share", "opentoonz", "stuff"),
    ("share", "opentoonz", "stuff"),
    ("stuff",),
)


@dataclass(frozen=True)
class Runtime:
    """A located OpenToonz installation."""

    root: Path | None
    ot_bin: Path
    tcomposer_bin: Path
    template_stuff: Path | None = None
    version: str | None = None

    @property
    def ok(self) -> bool:
        return self.ot_bin.is_file() and self.tcomposer_bin.is_file()


def _first_existing(root: Path, names: tuple[str, ...]) -> Path | None:
    for parts in _BIN_SUBPATHS:
        for name in names:
            candidate = root.joinpath(*parts, name)
            if candidate.is_file():
                return candidate
    return None


def _find_template_stuff(root: Path | None) -> Path | None:
    if root is None:
        return None
    for parts in _STUFF_SUBPATHS:
        candidate = root.joinpath(*parts)
        if candidate.is_dir():
            return candidate
    return None


def _detect_version(tcomposer_bin: Path) -> str | None:
    """Return a version string like ``OpenToonz v1.8.0`` (best effort)."""
    try:
        proc = subprocess.run(
            [str(tcomposer_bin), "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in (proc.stdout + proc.stderr).splitlines():
        line = line.strip()
        if line and "opentoonz" in line.lower():
            return line
    return None


def discover(settings: Settings) -> Runtime:
    """Find the runtime from settings/environment, or raise a helpful error."""
    root: Path | None = None
    if settings.runtime_dir is not None:
        runtime_dir = settings.runtime_dir
        root = runtime_dir.parent if runtime_dir.is_file() else runtime_dir
        if not root.is_dir():
            raise RuntimeNotFoundError(f"OPENTOONZ_RUNTIME does not exist: {runtime_dir}")

    ot_bin = settings.ot_bin
    tc_bin = settings.tcomposer_bin

    if root is not None:
        ot_bin = ot_bin or _first_existing(root, (OT_BINARY, "opentoonz"))
        tc_bin = tc_bin or _first_existing(root, (TCOMPOSER_BINARY,))

    if ot_bin is None:
        found = shutil.which(OT_BINARY) or shutil.which("opentoonz")
        ot_bin = Path(found) if found else None
    if tc_bin is None:
        found = shutil.which(TCOMPOSER_BINARY)
        tc_bin = Path(found) if found else None

    if ot_bin is None or tc_bin is None:
        raise RuntimeNotFoundError(
            "Could not locate the OpenToonz runtime.\n"
            "Install OpenToonz and either put 'OpenToonz'/'tcomposer' on PATH, or set "
            "OPENTOONZ_RUNTIME to an extracted AppImage directory (the one containing "
            "usr/bin/OpenToonz), or set OPENTOONZ_BIN and OPENTOONZ_TCOMPOSER_BIN.\n"
            "See docs/installation.md."
        )
    if not ot_bin.is_file():
        raise RuntimeNotFoundError(f"OpenToonz binary not found: {ot_bin}")
    if not tc_bin.is_file():
        raise RuntimeNotFoundError(f"tcomposer binary not found: {tc_bin}")

    if root is None:
        root = ot_bin.parent.parent if ot_bin.parent.name == "bin" else ot_bin.parent

    return Runtime(
        root=root,
        ot_bin=ot_bin,
        tcomposer_bin=tc_bin,
        template_stuff=_find_template_stuff(root),
        version=_detect_version(tc_bin),
    )
