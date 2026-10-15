"""Environment-driven configuration for opentoonz-mcp.

Everything is overridable through ``OPENTOONZ_*`` environment variables so the
tool is portable across machines. No paths are hard-coded to a user account.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

#: Where mutable state lives when the user does not override it:
#: the shared OpenToonz "stuff" tree, an isolated HOME, and workspaces.
DEFAULT_DATA_HOME = "~/.local/share/opentoonz-mcp"


def _str(source: Mapping[str, str], name: str) -> str | None:
    value = source.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _path(source: Mapping[str, str], name: str) -> Path | None:
    value = _str(source, name)
    return Path(value).expanduser() if value else None


def _int(source: Mapping[str, str], name: str, default: int) -> int:
    value = _str(source, name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _bool(source: Mapping[str, str], name: str, default: bool) -> bool:
    value = _str(source, name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration."""

    data_home: Path
    workspaces_root: Path
    runtime_dir: Path | None = None
    ot_bin: Path | None = None
    tcomposer_bin: Path | None = None
    stuff_root_override: Path | None = None
    ffmpeg: str = "ffmpeg"
    script_timeout: int = 90
    render_timeout: int = 600
    keep_scripts: bool = True

    @property
    def stuff_root(self) -> Path:
        """The shared OpenToonz ``TOONZROOT`` tree."""
        return self.stuff_root_override or (self.data_home / "stuff")

    @property
    def home(self) -> Path:
        """An isolated ``HOME`` used for OpenToonz subprocesses.

        This keeps OpenToonz from writing into the user's real
        ``~/.config/OpenToonz`` and makes runs reproducible.
        """
        return self.data_home / "home"

    @classmethod
    def from_env(cls, source: Mapping[str, str] | None = None) -> Settings:
        """Build settings from the process environment or a supplied mapping."""
        src: Mapping[str, str] = os.environ if source is None else source
        data_home = (_path(src, "OPENTOONZ_MCP_HOME") or Path(DEFAULT_DATA_HOME)).expanduser()
        workspaces_root = _path(src, "OPENTOONZ_WORKSPACES") or (data_home / "workspaces")
        return cls(
            data_home=data_home,
            workspaces_root=workspaces_root,
            runtime_dir=_path(src, "OPENTOONZ_RUNTIME"),
            ot_bin=_path(src, "OPENTOONZ_BIN"),
            tcomposer_bin=_path(src, "OPENTOONZ_TCOMPOSER_BIN"),
            stuff_root_override=_path(src, "OPENTOONZ_STUFF"),
            ffmpeg=_str(src, "OPENTOONZ_FFMPEG") or "ffmpeg",
            script_timeout=_int(src, "OPENTOONZ_SCRIPT_TIMEOUT", 90),
            render_timeout=_int(src, "OPENTOONZ_RENDER_TIMEOUT", 600),
            keep_scripts=_bool(src, "OPENTOONZ_KEEP_SCRIPTS", True),
        )


def settings_from_env(source: Mapping[str, str] | None = None) -> Settings:
    """Convenience wrapper around :meth:`Settings.from_env`."""
    return Settings.from_env(source)
