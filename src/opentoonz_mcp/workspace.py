"""Workspace management: isolated project folders under the workspaces root.

A workspace is intentionally thin — drawings, render output, and the generated
scripts. The (large) shared OpenToonz ``stuff`` tree lives once in the data home
and is referenced through ``-TOONZROOT``, so workspaces stay small.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .context import Context
from .errors import WorkspaceError

SUBDIRS = ("drawings", "render", "scripts")


@dataclass(frozen=True)
class Workspace:
    name: str
    root: Path

    @property
    def drawings(self) -> Path:
        return self.root / "drawings"

    @property
    def render(self) -> Path:
        return self.root / "render"

    @property
    def scripts(self) -> Path:
        return self.root / "scripts"

    def scene_path(self, scene: str) -> Path:
        """Resolve a scene name to a path (scenes live at the workspace root)."""
        path = Path(scene)
        name = scene if scene.endswith(".tnz") else scene + ".tnz"
        if path.is_absolute():
            return Path(name)
        return (self.root / name).resolve()

    def scenes(self) -> list[Path]:
        return sorted(self.root.glob("*.tnz"))


def _root(context: Context) -> Path:
    return context.settings.workspaces_root.expanduser().resolve()


def resolve(context: Context, name: str) -> Path:
    """Resolve a workspace name to a safe path inside the workspaces root."""
    if not name or not name.strip():
        raise WorkspaceError("Workspace name must not be empty.")
    root = _root(context)
    candidate = (root / name).resolve()
    if candidate == root or root not in candidate.parents:
        raise WorkspaceError(f"Workspace escapes the workspaces root: {name!r}")
    return candidate


def create(context: Context, name: str) -> tuple[Workspace, bool]:
    """Create a workspace (idempotent). Returns ``(workspace, created)``."""
    root = resolve(context, name)
    created = not root.is_dir()
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return Workspace(name=name, root=root), created


def require(context: Context, name: str) -> Workspace:
    """Return an existing workspace, or raise a helpful error."""
    root = resolve(context, name)
    if not root.is_dir():
        raise WorkspaceError(f"Workspace '{name}' does not exist. Create it first with opentoonz_create_workspace.")
    for sub in SUBDIRS:
        (root / sub).mkdir(exist_ok=True)
    return Workspace(name=name, root=root)


def list_workspaces(context: Context) -> list[Workspace]:
    root = _root(context)
    if not root.is_dir():
        return []
    return [Workspace(name=child.name, root=child) for child in sorted(root.iterdir()) if child.is_dir()]
