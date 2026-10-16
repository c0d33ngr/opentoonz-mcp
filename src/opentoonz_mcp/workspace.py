"""Workspace management: isolated project folders under the workspaces root.

A workspace is intentionally thin — drawings, render output, and the generated
scripts. The (large) shared OpenToonz ``stuff`` tree lives once in the data home
and is referenced through ``-TOONZROOT``, so workspaces stay small.

Because a scene is read, edited and rewritten as a whole, two callers working on
one workspace would silently drop each other's changes. Every scene or render
operation therefore runs under a per-workspace lock (:func:`lock`).
"""

from __future__ import annotations

import functools
import re
import threading
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .context import Context
from .errors import WorkspaceError

try:  # POSIX. Windows is not a supported target yet; see lock().
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

SUBDIRS = ("drawings", "render", "scripts")

#: A name that may become a file inside a workspace: one plain path segment.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MAX_NAME = 64


def _invalid(label: str, value: str) -> WorkspaceError:
    return WorkspaceError(
        f"Invalid {label} {value!r}: use 1-{_MAX_NAME} characters from A-Z a-z 0-9 _ - . "
        "(a single name — no path separators and no '..')."
    )


def safe_scene_name(scene: str) -> str:
    """Validate a scene name and return it with a ``.tnz`` extension.

    Scenes live directly under the workspace root, so a scene name is a single
    path segment. Anything that could escape the workspace — an absolute path, a
    separator, or ``..`` — is rejected rather than quietly resolved.
    """
    name = (scene or "").strip()
    if name.endswith(".tnz"):
        name = name[: -len(".tnz")]
    if not name or len(name) > _MAX_NAME or not _SAFE_NAME_RE.match(name) or ".." in name:
        raise _invalid("scene name", scene)
    return name + ".tnz"


def safe_out_name(out_name: str) -> str:
    """Validate a render output stem: a single plain name, no path, no ``..``.

    The stem becomes part of output file names *and* an ffmpeg glob
    (``<stem>*.png``), so an unvalidated one could write to — or delete files in —
    a directory outside the render folder.
    """
    name = (out_name or "").strip().rstrip("_")
    if not name or len(name) > _MAX_NAME or not _SAFE_NAME_RE.match(name) or ".." in name:
        raise _invalid("output name", out_name)
    return name


#: How long to wait for a busy workspace before giving up.
LOCK_TIMEOUT = 120.0
_LOCK_POLL = 0.05

#: The lock is re-entrant within a thread (set_exposure calls set_cells,
#: render_video calls render_frames), so track the depth per thread.
_held = threading.local()

#: Warn once, not once per operation, when locking is unavailable.
_warned_no_locking = False


def _warn_no_locking() -> None:
    """Say, once, that this platform gets no locking at all.

    Without ``fcntl`` there is nothing to serialise on, so the lock quietly
    becomes a no-op. Quietly is the wrong default: two callers on one workspace
    would still drop each other's edits, and nothing would say so.
    """
    global _warned_no_locking
    if not _warned_no_locking:
        _warned_no_locking = True
        warnings.warn(
            "Workspace locking needs fcntl, which this platform lacks: operations on one "
            "workspace are NOT serialised and concurrent edits may be lost.",
            RuntimeWarning,
            stacklevel=3,
        )


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
        """Resolve a *validated* scene name to a path inside the workspace.

        Raises :class:`WorkspaceError` for a name that is not a plain segment, so
        a caller cannot read or write a scene outside its own workspace.
        """
        return self.root / safe_scene_name(scene)

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


def disk_usage(workspace: Workspace) -> int:
    """Total bytes stored under a workspace (drawings, renders, scripts).

    Entries that vanish mid-walk (a render clearing its stale frames) are
    skipped rather than raised, since this only ever runs to report a size.
    """
    total = 0
    for path in workspace.root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:  # pragma: no cover - depends on a concurrent writer
            continue
    return total


def human_size(size: float) -> str:
    """Format a byte count for display (``1.4 MB``)."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"  # pragma: no cover - unreachable


@contextmanager
def lock(context: Context, name: str, timeout: float | None = None):
    """Hold a workspace's lock for the duration of an operation.

    The lock is an ``flock`` on ``<workspace>/.lock``: advisory, cheap, and
    released automatically if the process dies. It is re-entrant within a
    thread, so a tool may call another locked operation. Nesting does not
    deadlock, and two *threads* (or processes) are properly serialised.

    On platforms without ``fcntl`` there is nothing to lock with, so the lock
    degrades to a no-op — and says so once, rather than silently losing edits.
    The runtime layer is Linux-first (see docs/architecture.md).
    """
    workspace = require(context, name)
    if getattr(_held, "root", None) == workspace.root and getattr(_held, "depth", 0):
        _held.depth += 1
        try:
            yield workspace
        finally:
            _held.depth -= 1
        return

    handle = None
    if fcntl is None:
        _warn_no_locking()
    else:
        # Held open for the whole operation and closed in the finally below, so
        # it cannot be a with-block.
        handle = open(workspace.root / ".lock", "a+")  # noqa: SIM115
        deadline = time.monotonic() + (LOCK_TIMEOUT if timeout is None else timeout)
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise WorkspaceError(
                        f"Timed out waiting for the workspace lock on '{name}' after "
                        f"{timeout if timeout is not None else LOCK_TIMEOUT:.0f}s — "
                        "another operation is still using it."
                    ) from None
                time.sleep(_LOCK_POLL)

    _held.root, _held.depth = workspace.root, 1
    try:
        yield workspace
    finally:
        _held.root, _held.depth = None, 0
        if handle is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def locked(fn):
    """Wrap a ``(context, workspace, ...)`` operation so it runs under the lock.

    Serialising whole operations — not just individual file writes — is the
    point: the read-modify-write spans an OpenToonz subprocess, so the lock has
    to cover that too.
    """

    @functools.wraps(fn)
    def wrapper(context: Context, workspace: str, *args, **kwargs):
        with lock(context, workspace):
            return fn(context, workspace, *args, **kwargs)

    return wrapper
