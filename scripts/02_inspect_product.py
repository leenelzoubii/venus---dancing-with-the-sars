"""Step 2 — inspect one real GCOV product and report what is *actually* inside it.

Never assume layer names, units or projections. This script streams the file's metadata
(a few MB, not 1.9 GB), prints the HDF5 tree, the CRS and grid, and computes statistics on a
window so we can confirm the values really are gamma-0 *power*.

    python scripts/02_inspect_product.py                    # newest PROVISIONAL scene from step 1
    python scripts/02_inspect_product.py --date 2026-06-24  # a specific acquisition
    python scripts/02_inspect_product.py --url https://...  # an explicit product

Findings get copied into docs/DATA_SOURCES.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import auth, nisar  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

SCENES_CSV = REPO_ROOT / "data" / "interim" / "nisar_gcov_scenes.csv"


def choose_product(args) -> tuple[str, str]:
    """Return (url, label) for the product to inspect."""
    if args.url:
        return args.url, "explicit --url"
    if not SCENES_CSV.exists():
        raise SystemExit(
            f"{SCENES_CSV.relative_to(REPO_ROOT)} not found — run scripts/01_search_nisar.py first."
        )
    df = pd.read_csv(SCENES_CSV, parse_dates=["acquisition_date"])
    if args.date:
        df = df[df["acquisition_date"].dt.strftime("%Y-%m-%d") == args.date]
        if df.empty:
            raise SystemExit(f"No scene on {args.date} in {SCENES_CSV.name}.")
    if args.stack:
        track, frame, direction = args.stack.split("/")
        df = df[
            (df["track"] == int(track))
            & (df["frame"] == int(frame))
            & (df["direction"].str.upper().str.startswith(direction.upper()[0]))
        ]
    if df.empty:
        raise SystemExit("No matching product.")
    row = df.sort_values("acquisition_date").iloc[-1]
    return row["url"], f"{row['granule']}  ({pd.Timestamp(row['acquisition_date']).date()})"


def describe(h5file, max_lines: int = 120) -> None:
    print("\n" + "=" * 78)
    print("HDF5 TREE (datasets only)")
    print("=" * 78)
    for i, ds in enumerate(nisar.walk(h5file)):
        if i >= max_lines:
            print("  ... (truncated)")
            break
        attrs = ""
        for key in ("units", "long_name", "_FillValue"):
            if key in ds.attrs:
                value = ds.attrs[key]
                if isinstance(value, bytes):
                    value = value.decode()
                attrs += f"  {key}={value!r}"
        print(f"  {ds.path:<62} {str(ds.shape):<16} {ds.dtype}{attrs}")


def stats(arr: np.ndarray, label: str) -> None:
    flat = np.asarray(arr, dtype="float64").ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        print(f"  {label}: no finite values")
        return
    pct = np.percentile(finite, [1, 5, 50, 95, 99])
    zeros = float(np.count_nonzero(finite == 0)) / finite.size
    negatives = float(np.count_nonzero(finite < 0)) / finite.size
    with np.errstate(divide="ignore", invalid="ignore"):
        db = 10 * np.log10(finite[finite > 0])
    print(
        f"  {label}: n={finite.size}  min={finite.min():.4g}  p1={pct[0]:.4g}  median={pct[2]:.4g}  "
        f"mean={finite.mean():.4g}  p99={pct[4]:.4g}  max={finite.max():.4g}"
    )
    print(
        f"      zeros={zeros:.1%}  negatives={negatives:.1%}  "
        f"dB(median)={10 * np.log10(pct[2]):.2f}  dB(p99)={10 * np.log10(pct[4]):.2f}"
        if pct[2] > 0
        else f"      zeros={zeros:.1%}  negatives={negatives:.1%}  (non-positive median: not power?)"
    )
    _ = db  # kept for clarity; the numbers above are the ones we quote


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    ap.add_argument("--url", help="Explicit product URL (skips the scene table).")
    ap.add_argument("--date", help="Acquisition date YYYY-MM-DD to inspect.")
    ap.add_argument("--stack", help="Geometry filter, e.g. 151/73/DESC.")
    ap.add_argument("--window", type=int, default=512, help="Window size in pixels (default 512).")
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    url, label = choose_product(args)

    print("=" * 78)
    print(f"AOI     : {area.name} ({area.title})")
    print(f"Product : {label}")
    print(f"Stream  : {url.split('/')[-1]}")
    print("=" * 78)

    auth.login()
    h5file = nisar.open_h5(url)

    try:
        describe(h5file)

        print("\n" + "=" * 78)
        print("GRID, CRS AND POLARIZATIONS")
        print("=" * 78)
        try:
            print(f"  polarizations: {nisar.polarizations(h5file)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  polarizations: unavailable ({exc})")
        for key, value in nisar.projection(h5file).items():
            print(f"  {key}: {value}")

        identification = h5file.get("/science/LSAR/identification")
        if identification is not None:
            print("\n  identification (selection):")
            for key in (
                "productType", "productVersion", "radarBand", "missionId", "instrumentName",
                "trackNumber", "frameNumber", "orbitPassDirection", "absoluteOrbitNumber",
                "zeroDopplerStartTime", "zeroDopplerEndTime", "listOfPolarizations",
                "productSpecificationVersion", "isDithered", "rangeBandwidth",
            ):
                if key in identification.attrs:
                    value = identification.attrs[key]
                    print(f"    {key} = {value}")

        grid = nisar.grid_group(h5file)
        nrows, ncols = grid["HHHH"].shape if "HHHH" in grid else (None, None)
        print(f"\n  grid shape: {nrows} x {ncols}")
        if nrows:
            half = args.window // 2
            r0, c0 = max(0, nrows // 2 - half), max(0, ncols // 2 - half)
            rs = slice(r0, min(nrows, r0 + args.window))
            cs = slice(c0, min(ncols, c0 + args.window))
            print(f"  centre window rows {rs.start}:{rs.stop} cols {cs.start}:{cs.stop} (no full download)")
            print("\n" + "=" * 78)
            print("VALUE STATISTICS (confirming power vs amplitude)")
            print("=" * 78)
            for pol_ds in ("HHHH", "HVHV"):
                if pol_ds in grid:
                    stats(nisar.read_window(h5file, pol_ds, rs, cs), pol_ds)
            for extra in ("numberOfLooks", "mask"):
                if extra in grid:
                    arr = np.asarray(grid[extra][rs, cs])
                    uniq = np.unique(arr)
                    print(f"  {extra}: dtype={arr.dtype} unique={uniq[:10]}{'...' if uniq.size > 10 else ''}")
    finally:
        h5file.close()

    print("\nRecord these findings in docs/DATA_SOURCES.md (replace any 'TO VERIFY').")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
