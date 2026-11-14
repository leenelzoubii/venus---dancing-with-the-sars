"""Step 3 - stream only the AOI window from NISAR GCOV, for the dates we chose.

The file is ~1.9 GB; our window is a few hundred thousand pixels. We open the remote HDF5 by
byte-range access, read the window, and save it locally as ``.npy`` plus a JSON sidecar holding the
exact grid coordinates, CRS and provenance. Nothing is downloaded twice.

    python scripts/03_fetch_subset.py --aoi dead_sea_east --first 2026-06-24 --last 2026-10-10
    python scripts/03_fetch_subset.py --aoi dead_sea_east --dates 2026-06-24 2026-07-18
    python scripts/03_fetch_subset.py --aoi dead_sea_east --all     # every date in the stack

Output: data/raw/subsets/<aoi>/<date>_<stack>_{HH,HV,looks}.npy + <date>_<stack>.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from shapely import wkt as shapely_wkt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import auth, nisar  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

SCENES_CSV = REPO_ROOT / "data" / "interim" / "nisar_gcov_scenes.csv"


def select_scenes(args, area) -> pd.DataFrame:
    scenes_csv = Path(args.scenes) if getattr(args, "scenes", None) else SCENES_CSV
    if not scenes_csv.exists():
        raise SystemExit(f"{scenes_csv} not found - run 01_search_nisar.py first.")
    df = pd.read_csv(scenes_csv, parse_dates=["acquisition_date"])
    track, frame, direction = args.stack.split("/")
    df = df[
        (df["track"] == int(track))
        & (df["frame"] == int(frame))
        & (df["direction"].str.upper().str.startswith(direction.upper()[0]))
    ]
    df = df.assign(day=df["acquisition_date"].dt.strftime("%Y-%m-%d")).sort_values("acquisition_date")

    if args.dates:
        df = df[df["day"].isin(args.dates)]
    elif args.first or args.last:
        if args.first:
            df = df[df["day"] >= args.first]
        if args.last:
            df = df[df["day"] <= args.last]
    elif not args.all:
        raise SystemExit("Choose dates: --first/--last, --dates, or --all.")

    if df.empty:
        raise SystemExit("No scenes matched that selection; check the date table from step 1.")
    return df


def atomic_save_npy(path: Path, array) -> None:
    """Write an array so a crash can never leave a half-written ``.npy`` in the cache.

    The cache is the only copy of a slice that took two minutes of network to fetch, so a truncated
    file is expensive and silent: it loads fine and simply has the wrong numbers.
    """
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        np.save(handle, array)
    tmp.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def save_subset(df_row, area, outdir: Path, bbox, polarizations, force: bool) -> Path:
    day = pd.Timestamp(df_row["acquisition_date"]).strftime("%Y-%m-%d")
    stack_tag = f"{int(df_row['track'])}-{int(df_row['frame']):03d}-{df_row['direction'][:4]}"
    stem = f"{day}_{stack_tag}"
    sidecar = outdir / f"{stem}.json"
    # Cache hit requires the sidecar AND every array it promises: an interrupted run can leave the
    # sidecar-less half of a date, and trusting the sidecar alone would silently skip that gap.
    if sidecar.exists() and not force:
        promised = [sidecar, outdir / f"{stem}_looks.npy", outdir / f"{stem}_mask.npy"]
        promised += [outdir / f"{stem}_{p}.npy" for p in polarizations]
        missing = [p.name for p in promised if not p.exists()]
        if not missing:
            print(f"  {day}: cached ({sidecar.name})")
            return sidecar
        print(f"  {day}: incomplete cache, refetching ({', '.join(missing)})")

    t0 = time.time()
    h5file = nisar.open_h5(df_row["url"])
    try:
        rows, cols = nisar.window_to_indices(h5file, bbox)
        grid = nisar.grid_group(h5file)
        proj_attrs = dict(grid["projection"].attrs) if "projection" in grid else {}
        crs_wkt_value = proj_attrs.get("crs_wkt") or proj_attrs.get("spatial_ref")
        if isinstance(crs_wkt_value, bytes):
            crs_wkt_value = crs_wkt_value.decode()

        x = np.asarray(grid["xCoordinates"][cols.start : cols.stop], dtype="float64")
        y = np.asarray(grid["yCoordinates"][rows.start : rows.stop], dtype="float64")

        payload = {
            "granule": df_row["granule"],
            "url": df_row["url"],
            "acquisition_date": day,
            "track": int(df_row["track"]),
            "frame": int(df_row["frame"]),
            "direction": df_row["direction"],
            "polarizations": df_row.get("polarizations"),
            "maturity": df_row.get("maturity"),
            "crid": df_row.get("crid"),
            "stack": stack_tag,
            "aoi_name": area.name,
            "aoi_wkt": area.wkt,
            "crs_wkt": crs_wkt_value,
            "rows": [rows.start, rows.stop],
            "cols": [cols.start, cols.stop],
            "x": x.tolist(),
            "y": y.tolist(),
            "pixel_spacing_m": float(np.median(np.diff(x))) if x.size > 1 else None,
            "layers": {},
        }

        for pol in polarizations:
            dataset = nisar.POL_TO_DATASET[pol]
            if dataset not in grid:
                print(f"  {day}: {pol} not present, skipping that layer")
                continue
            arr = nisar.read_window(h5file, dataset, rows, cols)
            atomic_save_npy(outdir / f"{stem}_{pol}.npy", arr.astype("float32"))
            payload["layers"][pol] = {
                "dataset": f"{nisar.GCOV_BASE}/frequencyA/{dataset}",
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
                "finite_fraction": float(np.isfinite(arr).mean()),
            }

        for extra, suffix in (("numberOfLooks", "looks"), ("mask", "mask")):
            if extra in grid:
                arr = np.asarray(grid[extra][rows, cols])
                atomic_save_npy(outdir / f"{stem}_{suffix}.npy", arr)
                payload["layers"][extra] = {"shape": list(arr.shape), "dtype": str(arr.dtype)}

        atomic_write_text(sidecar, json.dumps(payload, indent=1))
    finally:
        h5file.close()

    print(f"  {day}: window {rows.stop - rows.start} x {cols.stop - cols.start} px in {time.time() - t0:.1f}s")
    return sidecar


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    ap.add_argument("--stack", default=None, help="Geometry as track/frame/DESC, default from config.")
    ap.add_argument("--dates", nargs="+", help="Explicit acquisition dates (YYYY-MM-DD).")
    ap.add_argument("--first", help="Earliest date to fetch (YYYY-MM-DD).")
    ap.add_argument("--last", help="Latest date to fetch (YYYY-MM-DD).")
    ap.add_argument("--all", action="store_true", help="Fetch every date in the stack.")
    ap.add_argument("--polarizations", nargs="+", default=None, help="HH HV (default from config).")
    ap.add_argument("--outdir", type=Path, default=None)
    ap.add_argument("--force", action="store_true", help="Re-download cached dates.")
    ap.add_argument("--scenes", default=None, help="Scene CSV from step 1 (default: the shared one).")
    ap.add_argument("--retries", type=int, default=3, help="Attempts per date before giving up.")
    ap.add_argument("--retry-wait", type=float, default=15.0, help="Backoff base in seconds (x attempt).")
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    s = area.search
    args.stack = args.stack or f"{s.get('track', 151)}/{s.get('frame', 73)}/{str(s.get('flight_direction', 'DESCENDING'))[:4]}"
    pols = [p.upper() for p in (args.polarizations or area.processing.get("comparison_polarizations", ["HH"]))]

    bbox = shapely_wkt.loads(area.wkt).bounds  # (west, south, east, north)
    outdir = args.outdir or (REPO_ROOT / "data" / "raw" / "subsets" / area.name)
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print(f"AOI   : {area.name} ({area.title})")
    print(f"Stack : {args.stack}   polarizations: {', '.join(pols)}")
    print(f"Box   : W{bbox[0]:.3f} S{bbox[1]:.3f} E{bbox[2]:.3f} N{bbox[3]:.3f}")
    print(f"Out   : {outdir.relative_to(REPO_ROOT)}")
    print("=" * 78)

    df = select_scenes(args, area)
    print(f"{len(df)} date(s) selected: {', '.join(df['day'])}")
    print("\nNOTE: only the AOI window is streamed; the rest of the ~1.9 GB file is never downloaded.\n")

    auth.login()
    for _, row in df.iterrows():
        day = pd.Timestamp(row["acquisition_date"]).strftime("%Y-%m-%d")
        for attempt in range(1, args.retries + 1):
            try:
                save_subset(row, area, outdir, bbox, pols, args.force)
                break
            except Exception as exc:  # noqa: BLE001 - network flakiness is expected, log and retry
                print(f"  {day}: attempt {attempt}/{args.retries} failed: {type(exc).__name__}: {exc}")
                if attempt == args.retries:
                    raise
                time.sleep(args.retry_wait * attempt)  # linear backoff, ASCII log

    print(f"\nDone. Subsets in {outdir.relative_to(REPO_ROOT)}")
    print("Next: python scripts/04_make_change_products.py --aoi", area.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
