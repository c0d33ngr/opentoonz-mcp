#!/usr/bin/env python3
"""Extract an OpenToonz AppImage into a reusable runtime directory.

Thin wrapper around :mod:`opentoonz_mcp.bootstrap`, for use straight from a
clone. An installed copy should use the console script instead::

    opentoonz-mcp fetch-runtime --appimage ~/Downloads/OpenToonz.AppImage

Example:
    python scripts/bootstrap_runtime.py --appimage ~/Downloads/OpenToonz.AppImage
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opentoonz_mcp.bootstrap import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
