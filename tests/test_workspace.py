import threading
import time
import warnings
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


# -- locking ------------------------------------------------------------------
def test_lock_serialises_threads(context):
    """Two callers on one workspace must never interleave."""
    W.create(context, "w")
    order = []
    start = threading.Barrier(2)

    def work(tag):
        start.wait()
        with W.lock(context, "w"):
            order.append(f"{tag}-in")
            time.sleep(0.05)
            order.append(f"{tag}-out")

    threads = [threading.Thread(target=work, args=(tag,)) for tag in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # each operation finished before the next began, in some order
    assert order[1] == order[0].replace("-in", "-out")
    assert order[3] == order[2].replace("-in", "-out")


def test_lock_is_reentrant_within_a_thread(context):
    """set_exposure calls set_cells, render_video calls render_frames: no deadlock."""
    W.create(context, "w")
    with W.lock(context, "w"), W.lock(context, "w"):
        assert W.require(context, "w").name == "w"  # reached without blocking


def test_lock_requires_an_existing_workspace(context):
    with pytest.raises(WorkspaceError), W.lock(context, "nope"):
        pass


def test_lock_times_out_when_the_workspace_is_busy(context):
    W.create(context, "w")
    holding, release = threading.Event(), threading.Event()

    def holder():
        with W.lock(context, "w"):
            holding.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert holding.wait(5)
    try:
        with pytest.raises(WorkspaceError, match="Timed out"), W.lock(context, "w", timeout=0.15):
            pass
    finally:
        release.set()
        thread.join()


def test_locked_wraps_an_operation(context):
    W.create(context, "w")
    seen = []

    @W.locked
    def operation(ctx, workspace, value):
        seen.append(workspace)
        return value * 2

    assert operation(context, "w", 21) == 42
    assert seen == ["w"]
    assert operation.__name__ == "operation"


def test_disk_usage_and_human_size(context):
    ws, _ = W.create(context, "w")
    (ws.render / "frame.png").write_bytes(b"x" * 2048)
    assert W.disk_usage(ws) >= 2048
    assert W.human_size(512) == "512 B"
    assert W.human_size(1024) == "1.0 KB"
    assert W.human_size(5 * 1024 * 1024) == "5.0 MB"


def test_lock_warns_once_when_fcntl_is_unavailable(context, monkeypatch):
    """Without fcntl the lock is a no-op — which must not pass unnoticed."""
    W.create(context, "w")
    monkeypatch.setattr(W, "fcntl", None)
    monkeypatch.setattr(W, "_warned_no_locking", False)

    with pytest.warns(RuntimeWarning, match="NOT serialised"), W.lock(context, "w"):
        pass

    # once per process, not once per operation
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with W.lock(context, "w"):
            pass
