from pathlib import Path

import pytest

from opentoonz_mcp import workspace as W
from opentoonz_mcp.errors import WorkspaceError


def test_create_is_idempotent(context):
    ws, created = W.create(context, "demo")
    assert created is True
    assert ws.drawings.is_dir() and ws.render.is_dir() and ws.scripts.is_dir()
    ws2, created2 = W.create(context, "demo")
    assert created2 is False
    assert ws2.root == ws.root


def test_require_missing(context):
    with pytest.raises(WorkspaceError):
        W.require(context, "nope")


def test_list(context):
    W.create(context, "a")
    W.create(context, "b")
    assert [w.name for w in W.list_workspaces(context)] == ["a", "b"]


@pytest.mark.parametrize("name", ["", "  ", ".", "..", "../evil", "/etc", "a/../../evil"])
def test_rejects_escaping_names(context, name):
    with pytest.raises(WorkspaceError):
        W.resolve(context, name)


def test_nested_names_allowed(context):
    ws, _ = W.create(context, "series/ep1")
    assert ws.root.name == "ep1"


def test_scene_path(context):
    ws, _ = W.create(context, "demo")
    assert ws.scene_path("main") == ws.root / "main.tnz"
    assert ws.scene_path("main.tnz") == ws.root / "main.tnz"
    assert ws.scene_path(str(Path("/abs/x.tnz"))) == Path("/abs/x.tnz")
