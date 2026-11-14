"""Step 6 - QC the 9-date stack: one row per date, everything a reader needs to trust it.

Checks the boring things that quietly ruin a time series - shapes, CRS, empty pixels, low look
counts, masked pixels - and measures the two populations we care about (open water and land) in both
polarizations, so a threshold can be argued from numbers instead of folklore.

    python scripts/06_qc_table.py --aoi dead_sea_east
    python scripts/06_qc_table.py --aoi dead_sea_east --probe-mask   # also read mask attrs remotely
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import CRS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import nisar, stack  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

INTERIM = REPO_ROOT / "data" / "interim"
WATER_CUT_DB = -19.0   # provisional, HV only: the valley between water and land, to be confirmed
LAND_CUT_DB = -15.0    # obvious land: above the transition zone, used for the land median


def probe_mask_attrs(scene: stack.Scene) -> dict:
    """Read the mask dataset's own attributes from the archive (one small remote read)."""
    from venus import auth

    auth.login()
    handle = nisar.open_h5(scene.meta["url"])
    try:
        grid = nisar.grid_group(handle)
        attrs = {k: v for k, v in dict(grid["mask"].attrs).items()}
        attrs["_dtype"] = str(grid["mask"].dtype)
        return attrs
    finally:
        handle.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    ap.add_argument("--probe-mask", action="store_true", help="Read mask attributes from the archive.")
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    scenes = stack.load_scenes(area.name)
    grid = stack.verify_grid(scenes)

    print(f"AOI {area.name}: {grid['n_scenes']} dates {grid['first']} .. {grid['last']}")
    print(f"Window: rows {grid['rows'][0]}:{grid['rows'][1]}  cols {grid['cols'][0]}:{grid['cols'][1]}"
          f"  shape {grid['shape']}  spacing 20 m")
    if grid["problems"]:
        print("GRID PROBLEMS:")
        for problem in grid["problems"]:
            print(f"  - {problem}")
        raise SystemExit("Stopping: the dates are not on one grid, so no comparison is valid.")
    print("Grid check: identical shape, window, spacing, CRS, track/frame/direction, CRID P05023.\n")

    if args.probe_mask:
        attrs = probe_mask_attrs(scenes[0])
        print("mask dataset attributes:", json.dumps(attrs, default=str))
        print()

    rows = []
    for scene in scenes:
        hh = scene.power("HH")
        hv = scene.power("HV")
        looks = scene.looks.astype("float32")
        mask = scene.mask
        epsg = CRS.from_wkt(scene.meta["crs_wkt"]).to_epsg()

        db_hh = stack.change.power_to_db(hh)
        db_hv = stack.change.power_to_db(hv)
        finite_hv = np.isfinite(db_hv)
        water = finite_hv & (db_hv < WATER_CUT_DB)
        land = finite_hv & (db_hv > LAND_CUT_DB)

        valid_looks = looks[np.isfinite(looks)]
        rows.append({
            "date": scene.date,
            "crid": scene.meta.get("crid"),
            "maturity": scene.meta.get("maturity"),
            "shape": f"{hh.shape[0]}x{hh.shape[1]}",
            "pixel_m": scene.meta["pixel_spacing_m"],
            "epsg": epsg,
            "nan_pct_HH": round(100 * (1 - np.isfinite(db_hh).mean()), 3),
            "nan_pct_HV": round(100 * (1 - finite_hv.mean()), 3),
            "looks_mean": round(float(valid_looks.mean()), 2),
            "looks_min": round(float(valid_looks.min()), 2),
            "mask1_pct": round(100 * float((mask == 1).mean()), 3),
            "land_median_HH": round(float(np.nanmedian(db_hh[land])), 2),
            "water_median_HH": round(float(np.nanmedian(db_hh[water])), 2),
            "land_median_HV": round(float(np.nanmedian(db_hv[land])), 2),
            "water_median_HV": round(float(np.nanmedian(db_hv[water])), 2),
        })

    table = pd.DataFrame(rows)
    out = INTERIM / "qc_table.csv"
    table.to_csv(out, index=False, encoding="utf-8")

    pd.set_option("display.width", 200)
    print(table.to_string(index=False))
    print(f"\nWrote {out.relative_to(REPO_ROOT)}")
    print(f"Water definition used here: HV < {WATER_CUT_DB} dB (provisional); "
          f"land: HV > {LAND_CUT_DB} dB; both on finite pixels only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
