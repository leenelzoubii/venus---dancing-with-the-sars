"""Step 18 - G6: does the open-water mask touch the edge of the displayed rectangle?

Loads every water layer of a place and counts water pixels on the outermost row and column. Any
contact means the lake may be clipped by the rectangle the viewer sees, which is exactly what G6
forbids. One line per date; exit code 1 if any date touches.

    python scripts/18_check_lake_edge.py --aoi dead_sea_full
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", default="dead_sea_full")
    args = ap.parse_args()
    outdir = REPO_ROOT / "web" / "data" / args.aoi
    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    touched = []
    for layer in manifest["layers"]:
        if layer["kind"] != "water":
            continue
        with Image.open(outdir / layer["file"]) as image:
            alpha = np.array(image.convert("RGBA"))[..., 3]
        border = np.concatenate([alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]])
        if int((border > 0).sum()) > 0:
            touched.append(layer["date"])
    if touched:
        print(f"G6 FAIL {args.aoi}: water touches the display edge on {len(touched)} date(s): "
              f"{', '.join(touched[:6])}")
        return 1
    print(f"G6 PASS {args.aoi}: no water pixel touches the display edge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
