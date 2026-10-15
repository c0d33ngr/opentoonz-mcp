"""Exception hierarchy for opentoonz-mcp."""

from __future__ import annotations


class OpentoonzMCPError(Exception):
    """Base class for every error raised by this package."""


class RuntimeNotFoundError(OpentoonzMCPError):
    """The OpenToonz runtime (OpenToonz / tcomposer) could not be located."""


class WorkspaceError(OpentoonzMCPError):
    """A workspace name or path was missing, invalid, or unsafe."""


class ScriptError(OpentoonzMCPError):
    """An OpenToonz ``.toonzscript`` run failed or timed out."""


class RenderError(OpentoonzMCPError):
    """Rendering a scene with ``tcomposer`` (or ffmpeg) failed."""
