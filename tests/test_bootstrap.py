"""Tests for the runtime bootstrap command (no real AppImage needed)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opentoonz_mcp import bootstrap
from opentoonz_mcp.errors import OpentoonzMCPError


def _fake_extract(monkeypatch, *, binaries=("OpenToonz", "tcomposer")):
    """Stand in for ``--appimage-extract``, creating the tree it would leave."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])
        root = Path(kwargs["cwd"]) / "squashfs-root" / "usr" / "bin"
        root.mkdir(parents=True, exist_ok=True)
        for name in binaries:
            (root / name).write_bytes(b"#!/bin/sh\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_fetch_runtime_extracts_and_returns_the_root(tmp_path, monkeypatch):
    appimage = tmp_path / "OpenToonz.AppImage"
    appimage.write_bytes(b"#!/bin/sh\n")
    calls = _fake_extract(monkeypatch)
    root = bootstrap.fetch_runtime(appimage, tmp_path / "runtime")
    assert root.name == "squashfs-root"
    assert (root / "usr" / "bin" / "tcomposer").is_file()
    # extracted, never executed: the AppImage launcher breaks headless runs
    assert calls[0][1:] == ["--appimage-extract"]


def test_fetch_runtime_rejects_a_missing_appimage(tmp_path):
    with pytest.raises(OpentoonzMCPError, match="Not an AppImage"):
        bootstrap.fetch_runtime(tmp_path / "nope.AppImage")


def test_fetch_runtime_rejects_a_partial_extraction(tmp_path, monkeypatch):
    """A runtime missing tcomposer would fail much later and more confusingly."""
    appimage = tmp_path / "OpenToonz.AppImage"
    appimage.write_bytes(b"#!/bin/sh\n")
    _fake_extract(monkeypatch, binaries=("OpenToonz",))
    with pytest.raises(OpentoonzMCPError, match="tcomposer"):
        bootstrap.fetch_runtime(appimage, tmp_path / "runtime")


def test_fetch_runtime_reports_an_extraction_failure(tmp_path, monkeypatch):
    appimage = tmp_path / "OpenToonz.AppImage"
    appimage.write_bytes(b"#!/bin/sh\n")

    def boom(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(OpentoonzMCPError, match="failed"):
        bootstrap.fetch_runtime(appimage, tmp_path / "runtime")


def test_main_prints_the_environment_value(tmp_path, monkeypatch, capsys):
    appimage = tmp_path / "OpenToonz.AppImage"
    appimage.write_bytes(b"#!/bin/sh\n")
    _fake_extract(monkeypatch)
    assert bootstrap.main(["--appimage", str(appimage), "--dest", str(tmp_path / "runtime")]) == 0
    out = capsys.readouterr().out
    assert "OPENTOONZ_RUNTIME=" in out and "squashfs-root" in out


def test_main_reports_a_bad_appimage(tmp_path, capsys):
    assert bootstrap.main(["--appimage", str(tmp_path / "nope.AppImage")]) == 1
    assert "error:" in capsys.readouterr().err


def test_the_console_script_dispatches_subcommands():
    """An MCP client runs the bare command, so no subcommand must mean 'serve'."""
    from opentoonz_mcp.server import _build_parser

    parser = _build_parser()
    assert parser.parse_args([]).command is None
    args = parser.parse_args(["fetch-runtime", "--appimage", "x.AppImage"])
    assert args.command == "fetch-runtime" and args.appimage == Path("x.AppImage")
