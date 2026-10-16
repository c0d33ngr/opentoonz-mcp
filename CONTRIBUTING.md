# Contributing

Thanks for helping improve `opentoonz-mcp`! This is a small, focused project —
clean, tested changes are very welcome.

## Development setup

```bash
git clone <your-fork> opentoonz-mcp
cd opentoonz-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

End-to-end tests need a real OpenToonz runtime:

```bash
export OPENTOONZ_RUNTIME=/path/to/squashfs-root   # or put OpenToonz/tcomposer on PATH
```

## Running checks

```bash
ruff check .            # lint
ruff format --check .   # formatting
pytest -m "not e2e"     # fast unit tests (no runtime needed)
pytest -m e2e           # end-to-end tests (needs a runtime)
python -m build         # packaging check
```

Please make sure both test groups pass before opening a PR — these are exactly
the gates CI runs.

The push/PR gate covers lint, formatting, the unit tests and the packaging check.
The `e2e` suite needs a real OpenToonz runtime, which CI cannot fetch anonymously
(OpenToonz publishes its Linux AppImage only as a login-gated workflow artifact,
and it is deliberately not redistributed here), so it runs separately, on demand
via **Actions → e2e → Run workflow** — pass an `appimage_url` if you have one —
and weekly when a runtime can be found. See
[`.github/workflows/e2e.yml`](.github/workflows/e2e.yml).

## Guidelines

- **Keep `server.py` thin.** Logic belongs in the library modules
  (`bridge`, `workspace`, `scenes`, `render`, `draw`); `server.py` only formats
  results and handles errors.
- **No hard-coded paths.** All machine-specific locations go through
  `config.py` / `runtime.py` and are overridable by `OPENTOONZ_*` env vars.
- **Batch over chatty.** Each tool call spawns a process; prefer doing more per
  call over adding many small tools.
- **Success is a marker, not an exit code** (OpenToonz exits non-zero on
  success). Generated scripts should print `__OTMCP_OK__`.
- **Add a test** for every new tool or bug fix, and add the tool name to
  `tests/test_server.py`.
- **E2E stays gated** behind the `e2e` marker so CI without OpenToonz still runs.

## Adding a tool

1. Implement the behaviour in a library module and unit-test it.
2. Add a thin wrapper to `src/opentoonz_mcp/server.py` with a clear docstring
   (the docstring is what the agent sees).
3. Add the tool name to `EXPECTED_TOOLS` in `tests/test_server.py`.
4. Document it in `docs/tools.md` and the README table.

## Reporting bugs

Open an issue with the output of `opentoonz_doctor`, your OpenToonz version, and
the exact tool call + returned text. GUI-mode hangs and black renders are almost
always covered in `docs/troubleshooting.md` — please check there first.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
