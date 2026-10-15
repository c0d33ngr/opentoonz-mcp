from pathlib import Path

import pytest

from opentoonz_mcp.config import Settings
from opentoonz_mcp.errors import RuntimeNotFoundError
from opentoonz_mcp.runtime import discover


def _make_runtime(root: Path) -> Path:
    (root / "usr" / "bin").mkdir(parents=True)
    (root / "usr" / "bin" / "OpenToonz").write_text("")
    (root / "usr" / "bin" / "tcomposer").write_text("")
    return root


def test_discover_from_runtime_dir(tmp_path):
    root = _make_runtime(tmp_path / "rt")
    (root / "usr" / "share" / "opentoonz" / "stuff" / "projects").mkdir(parents=True)
    settings = Settings(data_home=tmp_path / "d", workspaces_root=tmp_path / "w", runtime_dir=root)
    runtime = discover(settings)
    assert runtime.ot_bin == root / "usr" / "bin" / "OpenToonz"
    assert runtime.tcomposer_bin == root / "usr" / "bin" / "tcomposer"
    assert runtime.template_stuff == root / "usr" / "share" / "opentoonz" / "stuff"
    assert runtime.root == root


def test_discover_missing_raises(tmp_path):
    settings = Settings(data_home=tmp_path / "d", workspaces_root=tmp_path / "w", runtime_dir=tmp_path / "nope")
    with pytest.raises(RuntimeNotFoundError):
        discover(settings)


def test_discover_explicit_bins(tmp_path):
    root = _make_runtime(tmp_path / "rt")
    settings = Settings(
        data_home=tmp_path / "d",
        workspaces_root=tmp_path / "w",
        ot_bin=root / "usr" / "bin" / "OpenToonz",
        tcomposer_bin=root / "usr" / "bin" / "tcomposer",
    )
    runtime = discover(settings)
    assert runtime.ok
    assert runtime.template_stuff is None  # no runtime_dir given


def test_bad_runtime_dir_raises(tmp_path):
    settings = Settings(data_home=tmp_path / "d", workspaces_root=tmp_path / "w", runtime_dir=tmp_path / "ghost")
    with pytest.raises(RuntimeNotFoundError):
        discover(settings)
