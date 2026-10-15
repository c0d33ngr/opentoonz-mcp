"""Shared pytest fixtures and runtime detection helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentoonz_mcp.config import Settings
from opentoonz_mcp.context import Context
from opentoonz_mcp.runtime import Runtime, discover

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = REPO_ROOT / "runtime" / "squashfs-root"


def runtime_root() -> Path:
    return Path(os.environ.get("OPENTOONZ_RUNTIME", DEFAULT_RUNTIME)).expanduser()


def runtime_available() -> bool:
    root = runtime_root()
    return (root / "usr" / "bin" / "OpenToonz").is_file() and (root / "usr" / "bin" / "tcomposer").is_file()


requires_runtime = pytest.mark.skipif(not runtime_available(), reason="OpenToonz runtime not available")


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(data_home=tmp_path / "data", workspaces_root=tmp_path / "ws")


@pytest.fixture()
def context(settings: Settings) -> Context:
    """A context with a dummy runtime, for pure-unit tests."""
    dummy = Runtime(
        root=None,
        ot_bin=Path("/nonexistent/OpenToonz"),
        tcomposer_bin=Path("/nonexistent/tcomposer"),
    )
    return Context(settings=settings, runtime=dummy)


@pytest.fixture()
def live_context(tmp_path: Path) -> Context:
    """A context bound to the real runtime, for e2e tests."""
    if not runtime_available():
        pytest.skip("OpenToonz runtime not available")
    settings = Settings(
        data_home=tmp_path / "data",
        workspaces_root=tmp_path / "ws",
        runtime_dir=runtime_root(),
    )
    return Context(settings=settings, runtime=discover(settings))
