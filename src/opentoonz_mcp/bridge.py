"""Execute OpenToonz ``.toonzscript`` files headlessly and capture output.

OpenToonz's CLI script mode prints to stdout but may exit non-zero even on
success (harmless icon warnings), so success is decided by a printed sentinel
marker, never by the exit code.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .context import Context
from .errors import ScriptError

SCRIPT_SUFFIX = ".toonzscript"

#: Printed by generated scripts on success; parsed instead of the exit code.
OK_MARKER = "__OTMCP_OK__"

#: Available for scripts that want to signal a handled failure.
ERR_MARKER = "__OTMCP_ERR__"


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


#: Public alias — callers outside this module may need it too.
as_text = _as_text


@dataclass
class ScriptResult:
    """Outcome of one headless OpenToonz script run."""

    ok: bool
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    duration: float
    script_path: Path
    marker: str = OK_MARKER

    @property
    def failure(self) -> str | None:
        if self.ok:
            return None
        if self.timed_out:
            return "timed out (OpenToonz did not exit — this usually means it fell into GUI mode)"
        if self.marker not in self.stdout:
            return "missing success marker (the script did not complete)"
        return "unknown failure"

    def summary(self, out_tail: int = 3000, err_tail: int = 1500) -> str:
        parts = [f"exit={self.exit_code} ok={self.ok} ({self.duration:.1f}s)"]
        if self.timed_out:
            parts.append("TIMED OUT")
        tail = self.stdout[-out_tail:] if out_tail else self.stdout
        parts.append("--- stdout ---\n" + tail)
        if self.stderr.strip():
            parts.append("--- stderr ---\n" + (self.stderr[-err_tail:] if err_tail else self.stderr))
        return "\n".join(parts)


def build_env(context: Context) -> dict[str, str]:
    """Process environment with an isolated HOME so OpenToonz stays contained."""
    env = os.environ.copy()
    home = context.settings.home
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    return env


def run_script(
    context: Context,
    workspace_dir: str | Path,
    code: str,
    *,
    timeout: int | None = None,
    marker: str = OK_MARKER,
) -> ScriptResult:
    """Write ``code`` to a ``.toonzscript`` file and run it headlessly."""
    context.prepare()
    workspace_dir = Path(workspace_dir)
    scripts_dir = workspace_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / f"agent_{uuid.uuid4().hex[:12]}{SCRIPT_SUFFIX}"
    script_path.write_text(code, encoding="utf-8")

    cmd = [
        str(context.runtime.ot_bin),
        "-TOONZROOT",
        str(context.stuff_root),
        str(script_path),
    ]
    limit = timeout or context.settings.script_timeout

    started = time.monotonic()
    timed_out = False
    out = err = ""
    rc: int | None = None
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace_dir),
            env=build_env(context),
            capture_output=True,
            text=True,
            timeout=limit,
            errors="replace",
        )
        out, err, rc = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out = _as_text(exc.stdout)
        err = _as_text(exc.stderr)

    duration = time.monotonic() - started
    ok = (not timed_out) and (marker in out)
    if not context.settings.keep_scripts:
        script_path.unlink(missing_ok=True)

    return ScriptResult(
        ok=ok,
        stdout=out,
        stderr=err,
        exit_code=rc,
        timed_out=timed_out,
        duration=duration,
        script_path=script_path,
        marker=marker,
    )


def run_script_or_raise(
    context: Context,
    workspace_dir: str | Path,
    code: str,
    *,
    timeout: int | None = None,
    marker: str = OK_MARKER,
) -> ScriptResult:
    """Like :func:`run_script` but raises :class:`ScriptError` on failure."""
    result = run_script(context, workspace_dir, code, timeout=timeout, marker=marker)
    if not result.ok:
        raise ScriptError(f"OpenToonz script failed: {result.failure}\n{result.summary()}")
    return result
