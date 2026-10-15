"""Faked-subprocess tests for the OpenToonz script bridge (no runtime needed).

The bridge is the one place that knows OpenToonz's real CLI behaviour — it exits
non-zero even on success, and only prints a marker when the script finished — so
those rules are pinned here rather than left to the e2e suite.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace

import pytest

from opentoonz_mcp import bridge
from opentoonz_mcp.errors import ScriptError


@pytest.fixture()
def prepared(context):
    context._prepared = True
    return context


def _fake(monkeypatch, *, stdout="", stderr="", returncode=1, error=None):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": [str(part) for part in cmd], "kwargs": kwargs})
        if error is not None:
            raise error
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_success_is_decided_by_the_marker_not_the_exit_code(prepared, tmp_path, monkeypatch):
    calls = _fake(monkeypatch, stdout=f"Loading main\n{bridge.OK_MARKER}\n", returncode=3)
    result = bridge.run_script(prepared, tmp_path / "ws", "print(1);")
    assert result.ok and result.exit_code == 3 and result.failure is None
    # it ran headlessly, through OpenToonz, with an isolated HOME
    assert calls[0]["cmd"][0] == str(prepared.runtime.ot_bin)
    assert "-TOONZROOT" in calls[0]["cmd"]
    assert calls[0]["kwargs"]["env"]["HOME"] == str(prepared.settings.home)
    assert calls[0]["kwargs"]["cwd"] == str(tmp_path / "ws")


def test_missing_marker_is_a_failure(prepared, tmp_path, monkeypatch):
    _fake(monkeypatch, stdout="Loading main\n", returncode=0)
    result = bridge.run_script(prepared, tmp_path / "ws", "print(1);")
    assert not result.ok
    assert "missing success marker" in result.failure


def test_timeout_is_reported(prepared, tmp_path, monkeypatch):
    _fake(monkeypatch, error=subprocess.TimeoutExpired(cmd="OpenToonz", timeout=1))
    result = bridge.run_script(prepared, tmp_path / "ws", "print(1);")
    assert result.timed_out and "timed out" in result.failure


def test_a_missing_binary_is_explained(prepared, tmp_path, monkeypatch):
    _fake(monkeypatch, error=FileNotFoundError("OpenToonz"))
    with pytest.raises(ScriptError, match="OPENTOONZ_RUNTIME"):
        bridge.run_script(prepared, tmp_path / "ws", "print(1);")


def test_scripts_are_kept_by_default_and_removed_on_request(prepared, tmp_path, monkeypatch):
    _fake(monkeypatch, stdout=bridge.OK_MARKER)
    ws = tmp_path / "ws"
    kept = bridge.run_script(prepared, ws, "print(1);")
    assert kept.script_path.name.startswith("agent_")
    assert kept.script_path.suffix == bridge.SCRIPT_SUFFIX
    assert kept.script_path.exists()

    prepared.settings = replace(prepared.settings, keep_scripts=False)
    removed = bridge.run_script(prepared, ws, "print(1);")
    assert not removed.script_path.exists()


def test_run_script_or_raise(prepared, tmp_path, monkeypatch):
    _fake(monkeypatch, stdout="no marker here")
    with pytest.raises(ScriptError, match="OpenToonz script failed"):
        bridge.run_script_or_raise(prepared, tmp_path / "ws", "print(1);")


def test_summary_mentions_the_failure_and_tails_the_output(prepared, tmp_path, monkeypatch):
    _fake(monkeypatch, stdout="x" * 50, stderr="boom", returncode=2)
    result = bridge.run_script(prepared, tmp_path / "ws", "print(1);")
    summary = result.summary(out_tail=10)
    assert "exit=2" in summary and "--- stderr ---" in summary and "boom" in summary
