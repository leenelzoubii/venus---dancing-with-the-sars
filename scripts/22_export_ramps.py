"""Step 22 - export the colour ramps to the web app (single source of truth)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import ramps, webexport as wx  # noqa: E402
from venus.config import REPO_ROOT  # noqa: E402


def main() -> int:
    payload = ramps.payload()
    out = REPO_ROOT / "web" / "data"
    wx.write_json(out / "ramps.json", payload)
    wx.write_js(out / "ramps.js", "ramps", payload)
    print("wrote ramps.json/js", payload["kinds"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
