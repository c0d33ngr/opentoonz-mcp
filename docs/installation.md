# Installation

`opentoonz-mcp` needs two things: the Python package, and an **OpenToonz runtime**
(the `OpenToonz` scripting binary plus `tcomposer`). It never downloads OpenToonz
for you and never bundles it.

## 1. Install the package

```bash
pipx install git+https://github.com/c0d33ngr/opentoonz-mcp.git   # from GitHub
# or, pinned to a release
pipx install "git+https://github.com/c0d33ngr/opentoonz-mcp.git@v0.5.0"
# or, from a checkout
pipx install .
# or
uv tool install .
# or, for development
pip install -e ".[dev]"
```

This provides the `opentoonz-mcp` console script, which speaks MCP over stdio.

## 2. Provide an OpenToonz runtime

The runtime is located in this order:

1. `OPENTOONZ_BIN` / `OPENTOONZ_TCOMPOSER_BIN` (explicit binaries), else
2. `OPENTOONZ_RUNTIME` (a directory), else
3. `OpenToonz` / `opentoonz` and `tcomposer` on `PATH`.

### Option A — extracted AppImage (Linux, recommended)

The AppImage's `AppRun` launcher mangles CLI arguments and makes OpenToonz fall
into GUI mode, so **always run the extracted binary**. Extract once:

```bash
opentoonz-mcp fetch-runtime --appimage /path/to/OpenToonz.AppImage
```

It extracts into `~/.local/share/opentoonz-mcp/runtime` (override with `--dest`),
verifies `usr/bin/OpenToonz` and `usr/bin/tcomposer`, and prints the exact
`OPENTOONZ_RUNTIME` value to use:

```bash
export OPENTOONZ_RUNTIME=~/.local/share/opentoonz-mcp/runtime/squashfs-root
```

From a clone, before the package is installed, the same helper is available as
`python scripts/bootstrap_runtime.py --appimage /path/to/OpenToonz.AppImage`.

### Option B — system install

If OpenToonz is installed normally (package manager, Windows, macOS) and both
`OpenToonz` and `tcomposer` are on `PATH`, no configuration is needed. Otherwise
set `OPENTOONZ_BIN` and `OPENTOONZ_TCOMPOSER_BIN` to their full paths.

> **Platform status:** v0.4 is developed and tested on **Linux**. The runtime
> layer is written to be platform-agnostic (no hard-coded paths or Linux-only
> assumptions in `config.py` / `runtime.py`), but Windows/macOS are untested —
> contributions welcome. One known gap: workspace locking uses `fcntl`, so on
> Windows it degrades to a no-op (and warns once) — see
> [architecture](architecture.md).

## 3. ffmpeg (optional)

`opentoonz_render_video` shells out to `ffmpeg`. Override with `OPENTOONZ_FFMPEG`.
Frame-only rendering (`opentoonz_render`) does not need it.

## 4. Verify

Start your MCP client and call `opentoonz_doctor`. It prints every resolved path,
the version, and the prepared state:

```
opentoonz-mcp 0.5.0
runtime root : /home/me/.local/share/opentoonz-mcp/runtime/squashfs-root
OpenToonz    : .../usr/bin/OpenToonz
tcomposer    : .../usr/bin/tcomposer
version      : OpenToonz  v1.8.0
stuff (TOONZROOT): /home/me/.local/share/opentoonz-mcp/stuff
isolated HOME: /home/me/.local/share/opentoonz-mcp/home
workspaces   : /home/me/.local/share/opentoonz-mcp/workspaces
ffmpeg       : /usr/bin/ffmpeg
timeouts     : script=90s render=600s
```

## Configuration reference

All settings are environment variables. Defaults are per-user and portable.

| Variable | Default | Meaning |
|---|---|---|
| `OPENTOONZ_RUNTIME` | — | Directory containing `usr/bin/OpenToonz` (or `bin/OpenToonz`) |
| `OPENTOONZ_BIN` | — | Explicit path to the `OpenToonz` binary |
| `OPENTOONZ_TCOMPOSER_BIN` | — | Explicit path to `tcomposer` |
| `OPENTOONZ_STUFF` | `<data_home>/stuff` | Shared OpenToonz `TOONZROOT` tree |
| `OPENTOONZ_MCP_HOME` | `~/.local/share/opentoonz-mcp` | Data home (stuff, isolated HOME, workspaces) |
| `OPENTOONZ_WORKSPACES` | `<data_home>/workspaces` | Where workspaces are created |
| `OPENTOONZ_FFMPEG` | `ffmpeg` | ffmpeg executable |
| `OPENTOONZ_SCRIPT_TIMEOUT` | `90` | Seconds per script run |
| `OPENTOONZ_RENDER_TIMEOUT` | `600` | Seconds per render |
| `OPENTOONZ_KEEP_SCRIPTS` | `true` | Keep generated `.toonzscript` files as an audit trail |

### What lives in the data home

```
~/.local/share/opentoonz-mcp/
├── stuff/        shared TOONZROOT (copied once from the runtime template)
├── home/         isolated HOME for OpenToonz subprocesses
└── workspaces/   one folder per project
```

The shared `stuff/` is why workspaces stay tiny (no ~30 MB copy each) and the
isolated `home/` is why OpenToonz never touches your real `~/.config/OpenToonz`.
