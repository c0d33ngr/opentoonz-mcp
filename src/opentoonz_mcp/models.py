"""Structured results for the data-returning tools.

Each of these tools still returns a human-readable summary as its first content
block; the model is the machine-readable payload beside it, so a client can act
on a result without parsing prose. ``server._structured`` assembles the two.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LevelReport(BaseModel):
    """One level inside a scene."""

    name: str
    type: str
    frames: str
    path: str


class CellReport(BaseModel):
    """One occupied cell of the xsheet."""

    row: int
    column: int
    level: str
    fid: str


class SceneReport(BaseModel):
    """The shape of a saved scene (``opentoonz_scene_info``)."""

    scene: str
    frames: int
    columns: int
    levels: list[LevelReport] = Field(default_factory=list)
    cells: list[CellReport] = Field(default_factory=list)
    cells_truncated: bool = False


class WorkspaceReport(BaseModel):
    """One workspace's contents (``opentoonz_list_workspaces``)."""

    name: str
    scenes: list[str] = Field(default_factory=list)
    videos: list[str] = Field(default_factory=list)
    gifs: list[str] = Field(default_factory=list)
    frames: int = 0
    size_bytes: int = 0
    size: str = ""


class RenderReport(BaseModel):
    """The outcome of a render (a frame, a frame sequence, a video or a GIF)."""

    output: str
    frames: int
    duration: float
    width: int | None = None
    height: int | None = None
    downscaled_from: str | None = None
    fps: int | None = None


class BatchItem(BaseModel):
    """One scene's outcome inside a batch render."""

    scene: str
    ok: bool
    frames: int = 0
    output: str | None = None
    error: str | None = None


class BatchReport(BaseModel):
    """Rendering several scenes at once (``opentoonz_render_batch``)."""

    workspace: str
    kind: str
    rendered: int = 0
    failed: int = 0
    items: list[BatchItem] = Field(default_factory=list)
