"""Shared application context: settings + resolved runtime + prepared state."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import runtime as runtime_mod
from .config import Settings, settings_from_env
from .errors import RuntimeNotFoundError


@dataclass
class Context:
    """Holds everything the tools need, prepared lazily and cheaply."""

    settings: Settings
    runtime: runtime_mod.Runtime
    _prepared: bool = field(default=False, repr=False, compare=False)

    @property
    def stuff_root(self) -> Path:
        return self.settings.stuff_root

    def prepare(self) -> Context:
        """Create the isolated HOME, workspaces root, and shared stuff tree."""
        if not self._prepared:
            self.settings.home.mkdir(parents=True, exist_ok=True)
            self.settings.workspaces_root.mkdir(parents=True, exist_ok=True)
            self.ensure_stuff()
            self._prepared = True
        return self

    def ensure_stuff(self) -> Path:
        """Ensure a writable shared ``TOONZROOT`` tree exists.

        Copied once from the runtime's bundled template; shared by every
        workspace so we never duplicate ~30 MB per project.
        """
        root = self.settings.stuff_root
        if (root / "projects").is_dir():
            return root
        template = self.runtime.template_stuff
        if template is None:
            raise RuntimeNotFoundError(
                "No OpenToonz 'stuff' template found next to the runtime. "
                "Point OPENTOONZ_RUNTIME at an extracted AppImage directory "
                "(containing usr/share/opentoonz/stuff) or set OPENTOONZ_STUFF "
                "to an existing stuff tree."
            )
        root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(template, root, dirs_exist_ok=True)
        return root


_context: Context | None = None


def get_context(refresh: bool = False) -> Context:
    """Return the process-wide context, building it on first use."""
    global _context
    if _context is None or refresh:
        settings = settings_from_env()
        _context = Context(settings=settings, runtime=runtime_mod.discover(settings))
    return _context


def set_context(context: Context | None) -> None:
    """Override the process-wide context (used by tests)."""
    global _context
    _context = context
