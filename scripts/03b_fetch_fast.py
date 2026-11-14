"""Step 3b - fast window fetch through GDAL /vsicurl/ streaming.

Same output as scripts/03_fetch_subset.py (the .npy arrays and JSON sidecars the rest of the pipeline
reads), but it reads the remote product with GDAL instead of h5py/fsspec.

Why it is much faster: measured on the same 1231x505 window, h5py over fsspec took about 300 s per
date, while GDAL with merged consecutive ranges and multiplexed connections took 21 s for HHHH and 12 s
for HVHV. The bytes transferred are similar; the number of round trips is not. ASF's own NISAR guide
recommends exactly these GDAL options for this job.

    python scripts/03b_fetch_fast.py --aoi potash_city --all
    python scripts/03b_fetch_fast.py --aoi wadi_rum --first 2026-07-01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.env import Env
from shapely import wkt as shapely_wkt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

GCOV = "/science/LSAR/GCOV/grids/frequencyA"
SCENES_CSV = REPO_ROOT / "data" / "interim" / "nisar_gcov_scenes.csv"
FALLBACK_EPSG = 32636  # verified from the product's projection dataset in Hour 1


def gdal_env() -> Env:
    """The options ASF's guide recommends for streaming NISAR HDF5 with GDAL."""
    cookie = os.path.join(os.environ.get("TEMP", "."), "gdal_cookies.txt")
    return Env(
        GDAL_DISABLE_READDIR_ON_OPEN="TRUE",
        GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
        GDAL_HTTP_MULTIPLEX="YES",
        GDAL_NUM_THREADS="ALL_CPUS",
        CPL_VSIL_CURL_CHUNK_SIZE="2097152",
        CPL_VSIL_CURL_CACHE_SIZE="134217728",
        GDAL_HTTP_NETRC="YES",
        GDAL_HTTP_COOKIEFILE=cookie,
        GDAL_HTTP_COOKIEJAR=cookie,
    )


def sub(url: str, name: str) -> str:
    return 'HDF5:"/vsicurl/' + url + '"://' + GCOV.strip("/") + "/" + name


def sub_grid(url: str, name: str) -> str:
    """Datasets that live at the grids level, not inside frequencyA (e.g. projection)."""
    return 'HDF5:"/vsicurl/' + url + '"://science/LSAR/GCOV/grids/' + name


def window_indices(xs: np.ndarray, ys: np.ndarray, bounds) -> tuple[int, int, int, int]:
    """Row and column bounds of an AOI, handling either y ordering. Half-open: [row0, row1)."""
    west, south, east, north = bounds
    col0 = int(np.searchsorted(xs, west, side="left"))
    col1 = int(np.searchsorted(xs, east, side="right"))
    if ys[0] > ys[-1]:  # descending (north at the top), the NISAR convention
        row0 = int(np.searchsorted(-ys, -north, side="left"))
        row1 = int(np.searchsorted(-ys, -south, side="right"))
    else:
        row0 = int(np.searchsorted(ys, south, side="left"))
        row1 = int(np.searchsorted(ys, north, side="right"))
    return row0, row1, col0, col1


def resolve_epsg(xs: np.ndarray, ys: np.ndarray, bounds) -> int | None:
    """Which UTM zone does this product's grid live in?

    NISAR geocodes each frame into a UTM zone chosen for that frame, not for our AOI: the Dead Sea
    frame is 32636 while a Wadi Rum frame is a neighbouring zone. GDAL will not expose the product's
    scalar ``projection`` dataset, so the zone is found by testing the candidates and keeping the one
    whose transformed AOI actually overlaps the product's own coordinate range. If none fits, the
    caller stops rather than guessing.
    """
    west, south, east, north = bounds
    for zone in (36, 37, 35, 38):
        epsg = 32600 + zone
        transformer = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(epsg), always_xy=True)
        minx, miny = transformer.transform(west, south)
        maxx, maxy = transformer.transform(east, north)
        if minx < xs.max() and maxx > xs.min() and miny < ys.max() and maxy > ys.min():
            return epsg
    return None


def fetch_one(row, area, outdir: Path, pols: list[str]) -> None:
    day = pd.Timestamp(row["acquisition_date"]).strftime("%Y-%m-%d")
    stack_tag = f"{int(row['track'])}-{int(row['frame']):03d}-{row['direction'][:4]}"
    stem = f"{day}_{stack_tag}"
    sidecar = outdir / f"{stem}.json"
    needed = [sidecar, outdir / f"{stem}_looks.npy", outdir / f"{stem}_mask.npy"]
    needed += [outdir / f"{stem}_{p}.npy" for p in pols]
    if sidecar.exists():
        stored = json.loads(sidecar.read_text(encoding="utf-8"))
        needed = [sidecar, outdir / f"{stem}_looks.npy", outdir / f"{stem}_mask.npy"]
        needed += [outdir / f"{stem}_{p}.npy" for p in stored.get("layers", {}) if p in ("HH", "HV")]
        if all(p.exists() for p in needed):
            print(f"  {day}: cached")
            return

    url = row["url"]
    bounds = shapely_wkt.loads(area.wkt).bounds
    started = time.time()
    with gdal_env():
        with rasterio.open(sub(url, "xCoordinates")) as ds:
            xs = ds.read(1).ravel()
        with rasterio.open(sub(url, "yCoordinates")) as ds:
            ys = ds.read(1).ravel()
        epsg = resolve_epsg(xs, ys, bounds)
        if epsg is None:
            raise SystemExit(f"{day}: cannot place the AOI in any UTM zone shared with this product")
        transformer = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(epsg), always_xy=True)
        minx, miny = transformer.transform(bounds[0], bounds[1])
        maxx, maxy = transformer.transform(bounds[2], bounds[3])
        bounds_native = (min(minx, maxx), min(miny, maxy), max(minx, maxx), max(miny, maxy))
        row0, row1, col0, col1 = window_indices(xs, ys, bounds_native)
        if row1 <= row0 or col1 <= col0:
            raise SystemExit(f"{day}: the AOI does not overlap the product; check the stack for this place.")
        win = rasterio.windows.Window(col0, row0, col1 - col0, row1 - row0)

        def read(name: str, dtype):
            try:
                with rasterio.open(sub(url, name)) as ds:
                    return ds.read(1, window=win).astype(dtype)
            except Exception:  # noqa: BLE001 - a missing dataset means this product lacks that layer
                return None

        available = {}
        for pol in pols:
            arr = read({"HH": "HHHH", "HV": "HVHV"}[pol], "float32")
            if arr is not None:
                available[pol] = arr
            else:
                print(f"  {day}: {pol} not present in this product (single-polarization granule)")
        if not available:
            raise SystemExit(f"{day}: no requested polarization exists in this product")
        arrays = available
        looks = read("numberOfLooks", "float32")
        mask = read("mask", "uint8")

    payload = {
        "granule": row["granule"],
        "url": url,
        "acquisition_date": day,
        "track": int(row["track"]),
        "frame": int(row["frame"]),
        "direction": row["direction"],
        "polarizations": row.get("polarizations"),
        "maturity": row.get("maturity"),
        "crid": row.get("crid"),
        "stack": stack_tag,
        "aoi_name": area.name,
        "aoi_wkt": area.wkt,
        "crs_wkt": CRS.from_epsg(epsg).to_wkt(),
        "epsg": epsg,
        "rows": [row0, row1],
        "cols": [col0, col1],
        "x": xs[col0:col1].tolist(),
        "y": ys[row0:row1].tolist(),
        "pixel_spacing_m": float(abs(xs[1] - xs[0])) if xs.size > 1 else 20.0,
        "reader": "gdal_vsicurl",
        "layers": {},
    }
    for pol, arr in arrays.items():
        np.save(outdir / f"{stem}_{pol}.npy", arr)
        payload["layers"][pol] = {
            "dataset": f"{GCOV}/{ {'HH': 'HHHH', 'HV': 'HVHV'}[pol] }",
            "shape": list(arr.shape),
            "dtype": "float32",
            "finite_fraction": float(np.isfinite(arr).mean()),
        }
    np.save(outdir / f"{stem}_looks.npy", looks)
    np.save(outdir / f"{stem}_mask.npy", mask)
    payload["polarizations_present"] = sorted(arrays)
    if looks is not None:
        np.save(outdir / f"{stem}_looks.npy", looks)
        payload["layers"]["numberOfLooks"] = {"shape": list(looks.shape), "dtype": "float32"}
    if mask is not None:
        np.save(outdir / f"{stem}_mask.npy", mask)
        payload["layers"]["mask"] = {"shape": list(mask.shape), "dtype": "uint8"}
    sidecar.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    print(f"  {day}: {row1 - row0} x {col1 - col0} px in {time.time() - started:.1f}s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    ap.add_argument("--stack", default=None, help="Geometry as track/frame/DESC.")
    ap.add_argument("--scenes", default=None, help="Scene CSV from step 1.")
    ap.add_argument("--dates", nargs="+")
    ap.add_argument("--first")
    ap.add_argument("--last")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--polarizations", nargs="+", default=None)
    ap.add_argument("--outdir", type=Path, default=None)
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    s = area.search
    args.stack = args.stack or f"{s.get('track', 151)}/{s.get('frame', 73)}/{str(s.get('flight_direction', 'DESCENDING'))[:4]}"
    pols = [p.upper() for p in (args.polarizations or area.processing.get("comparison_polarizations", ["HH", "HV"]))]
    scenes_csv = Path(args.scenes) if args.scenes else SCENES_CSV
    if not scenes_csv.exists():
        raise SystemExit(f"{scenes_csv} not found - run 01_search_nisar.py first.")

    df = pd.read_csv(scenes_csv, parse_dates=["acquisition_date"])
    track, frame, direction = args.stack.split("/")
    df = df[(df["track"] == int(track)) & (df["frame"] == int(frame))
            & (df["direction"].str.upper().str.startswith(direction.upper()[0]))]
    df = df.assign(day=df["acquisition_date"].dt.strftime("%Y-%m-%d")).sort_values("acquisition_date")
    if args.dates:
        df = df[df["day"].isin(args.dates)]
    elif args.first or args.last:
        if args.first:
            df = df[df["day"] >= args.first]
        if args.last:
            df = df[df["day"] <= args.last]
    elif not args.all:
        raise SystemExit("Choose dates: --dates, --first/--last, or --all.")
    if df.empty:
        raise SystemExit("No scenes matched that selection.")

    outdir = args.outdir or (REPO_ROOT / "data" / "raw" / "subsets" / area.name)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"AOI {area.name}: {len(df)} date(s) on {args.stack}, polarizations {', '.join(pols)}")
    print(f"Out {outdir.relative_to(REPO_ROOT)}\n")

    for _, row in df.iterrows():
        fetch_one(row, area, outdir, pols)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
