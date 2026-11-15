"""Step 30 - quarterly OPERA RTC-S1 series for the two focus places (v5).

For each place and each quarter from 2016 to today, pick one acquisition date, read the RTC bursts
that cover the place (VV, VH and mask) through GDAL /vsicurl (small, no bulk download), mosaic them on
one 30 m UTM grid and cache the result as a compressed .npz. Resumable: an existing .npz is skipped.

    python scripts/30_s1_fetch.py --place dead_sea_full --start 2016-01-01
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
import shapely.wkt
from asf_search import ASFSession, search
from pyproj import Transformer
from rasterio.env import Env

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT, load_study_area  # noqa: E402

OUT = REPO_ROOT / "data" / "raw" / "s1"
ENV = dict(GDAL_HTTP_NETRC="YES", GDAL_HTTP_COOKIEFILE="gdal_cookies.txt",
           GDAL_HTTP_COOKIEJAR="gdal_cookies.txt", GDAL_DISABLE_READDIR_ON_OPEN="TRUE")
RES = 30.0


def quarter_starts(start_year: int, end: date) -> list[date]:
    out = []
    for year in range(start_year, end.year + 1):
        for month in (1, 4, 7, 10):
            if date(year, month, 1) <= end:
                out.append(date(year, month, 1))
    return out


def next_quarter(day: date) -> date:
    month = day.month + 3
    year = day.year + (month - 1) // 12
    return date(year, (month - 1) % 12 + 1, 1)


def search_quarter(wkt: str, start: date, end: date):
    # Filter for Sentinel-1 RTC: path 21 descending (OPERA RTC-S1 burst collection)
    # asf_search doesn't support pathNumber/flightDirection as direct kwargs; filter post-search.
    results = search(platform="SENTINEL-1", processingLevel="RTC", intersectsWith=wkt,
                     start=start.isoformat(), end=end.isoformat())
    by_day = {}
    for scene in results:
        if "S1D" in scene.properties.get("fileID", ""):
            continue
        props = scene.properties
        if props.get("pathNumber") != 21:
            continue
        if props.get("flightDirection") != "DESCENDING":
            continue
        by_day.setdefault(scene.properties["startTime"][:10], []).append(scene)
    if not by_day:
        return None, []
    # Prefer the date with the most bursts covering the AOI, then the middle of the quarter.
    mid = start + (end - start) / 2
    day = sorted(by_day, key=lambda d: (-len(by_day[d]), abs((date.fromisoformat(d) - mid).days)))[0]
    return day, by_day[day]


def read_bursts(place: str, day: str, scenes: list, aoi_wkt: str) -> dict | None:
    from rasterio.merge import merge
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling

    aoi = shapely.wkt.loads(aoi_wkt)
    zone = int((aoi.centroid.x + 180.0) // 6.0) + 1
    dst_crs = f"EPSG:326{zone:02d}"
    minx, miny, maxx, maxy = aoi.bounds
    transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    xs, ys = transformer.transform([minx, maxx], [miny, maxy])
    margin = 1500.0
    bounds = (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
    used = 0
    vv = vh = None
    with Env(**ENV):
        for key in ("VV", "VH"):
            datasets = []
            for scene in scenes:
                urls = scene.properties.get("additionalUrls", [])
                tif = next((u for u in urls if u.endswith(f"_{key}.tif")), None)
                if not tif:
                    continue
                try:
                    source = rasterio.open("/vsicurl/" + tif)
                    # Bursts near a zone edge can be 32636 or 32637; warp them to one CRS first.
                    datasets.append(WarpedVRT(source, crs=dst_crs, resampling=Resampling.bilinear,
                                              nodata=np.nan))
                except Exception as exc:  # noqa: BLE001
                    print(f"    {key} burst unavailable: {exc.__class__.__name__}")
            if not datasets:
                continue
            try:
                array, transform = merge([d for d in datasets], bounds=bounds, res=RES,
                                         nodata=np.nan, dtype="float32")
            finally:
                for dataset in datasets:
                    dataset.close()
            band = array[0]
            band[~np.isfinite(band)] = np.nan
            band[band <= 0] = np.nan
            if key == "VV":
                vv = band
                used = len(datasets)
            else:
                vh = band
    if vv is None or not np.isfinite(vv).any():
        return None
    valid = (np.isfinite(vv) & (vh > 0)) if vh is not None else np.isfinite(vv)
    vh_out = np.where(valid, vh, np.nan).astype("float32") if vh is not None else np.full_like(vv, np.nan)
    return {"vv": np.where(valid, vv, np.nan).astype("float32"), "vh": vh_out,
            "mask": valid.astype("uint8"), "transform": list(transform)[:6],
            "crs": dst_crs, "day": day, "bursts": used,
            "burst_ids": [s.properties["fileID"].split("_")[3] for s in scenes]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--place", required=True)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--quarters", type=int, default=0)
    args = ap.parse_args()
    area = load_study_area(args.place)
    outdir = OUT / args.place
    outdir.mkdir(parents=True, exist_ok=True)
    end = date.fromisoformat(args.end) if args.end else date.today()
    starts = quarter_starts(int(args.start[:4]), end)
    if args.quarters:
        starts = starts[-args.quarters:]
    done = 0
    for i, start in enumerate(starts):
        finish = min(next_quarter(start), end)
        existing = sorted(outdir.glob("*.npz"))
        already = [p for p in existing if start.isoformat() <= p.stem < finish.isoformat()]
        if already:
            continue
        try:
            day, scenes = search_quarter(area.wkt, start, finish)
            if not day:
                print(f"  {start}: no RTC scene")
                continue
            payload = read_bursts(args.place, day, scenes, area.wkt)
            if not payload:
                continue
            np.savez_compressed(outdir / f"{day}.npz", **payload)
            done += 1
            print(f"  {day}: {payload['bursts']} burst(s), valid {float(np.mean(payload['mask'])):.2f}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {start}: FAILED {exc.__class__.__name__} {str(exc)[:80]}")
        if i == len(starts) - 1:
            break
    print(f"{args.place}: fetched {done} quarter(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
