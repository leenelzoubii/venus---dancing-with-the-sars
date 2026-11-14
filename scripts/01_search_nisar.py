"""Step 1 - find NISAR scenes over the AOI and tell us what we can actually use.

What it answers: *which acquisitions exist over our study area, which of them share a viewing
geometry, and therefore which dates may be compared with each other?*

    python scripts/01_search_nisar.py --aoi dead_sea_east
    python scripts/01_search_nisar.py --aoi-wkt "POLYGON((...))"
    python scripts/01_search_nisar.py --aoi dead_sea_east --maturity BETA   # look further back

Outputs
    data/interim/nisar_gcov_scenes.csv   one row per product file (URL, date, track, frame, ...)
    data/interim/nisar_gcov_dates.csv    one row per usable acquisition date
A printed summary of dates per (track, frame, direction).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402
from venus.search import (  # noqa: E402
    dedupe_latest,
    pick_stack,
    results_to_frame,
    summarise_stacks,
)

ASF_REST = "https://api.daac.asf.alaska.edu/services/search/param"

# Documented permanent NISAR instrument data gap (NISAR Data User Guide, "Available Data").
MISSION_GAP_START = pd.Timestamp("2026-07-27T22:03:25Z")
MISSION_GAP_END = pd.Timestamp("2026-08-10T00:55:27Z")


def search_asf(kwargs: dict, max_results: int | None = None) -> pd.DataFrame:
    """Search with ``asf_search``; fall back to the ASF REST API if it cannot handle NISAR."""
    try:
        import asf_search as asf

        results = asf.search(**kwargs)
        print(f"asf_search {getattr(asf, '__version__', '?')}: {len(results)} product(s)")
        return results_to_frame(results)
    except Exception as exc:  # noqa: BLE001 - fall back rather than fail
        print(f"asf_search could not complete this search ({exc.__class__.__name__}: {exc})")
        print("Falling back to the ASF REST API ...")
        params = {
            "platform": kwargs.get("dataset", "NISAR"),
            "processingLevel": kwargs.get("processingLevel", "GCOV"),
            "intersectsWith": kwargs["intersectsWith"],
            "output": "csv",
        }
        if kwargs.get("dataMaturity"):
            params["dataMaturity"] = kwargs["dataMaturity"]
        if kwargs.get("start"):
            params["start"] = str(kwargs["start"])
        if kwargs.get("end"):
            params["end"] = str(kwargs["end"])

        import requests

        resp = requests.get(ASF_REST, params=params, timeout=120)
        resp.raise_for_status()
        from io import StringIO

        raw = pd.read_csv(StringIO(resp.text))
        print(f"ASF REST: {len(raw)} product(s)")
        df = pd.DataFrame(
            {
                "granule": raw["Granule Name"],
                "acquisition_date": pd.to_datetime(raw["Start Time"], utc=True),
                "track": raw["Path Number"].astype(int),
                "frame": raw["Frame Number"].astype(int),
                "direction": raw["Ascending or Descending?"],
                "size_mb": raw["Size (MB)"].astype(float),
                "processing_date": pd.to_datetime(raw["Processing Date"], utc=True, errors="coerce"),
                "url": raw["URL"],
                "product_type": raw["Processing Level"],
            }
        )
        from venus.search import maturity_from_url, parse_granule_name

        parsed = df["granule"].map(parse_granule_name)
        df["polarizations"] = [p.get("polarizations") for p in parsed]
        df["crid"] = [p.get("crid") for p in parsed]
        df["maturity"] = df["url"].map(maturity_from_url)
        df["acq_day"] = df["acquisition_date"].dt.strftime("%Y-%m-%d")
        if max_results:
            df = df.head(max_results)
        return df


def print_summary(df: pd.DataFrame, stacks) -> None:
    print("\n" + "=" * 78)
    print("USABLE DATES PER STACK  (only same track + frame + direction may be compared)")
    print("=" * 78)
    if not stacks:
        print("No products found. Try a larger AOI, a different maturity, or a wider date range.")
        return
    for stack in stacks:
        dates = "  ".join(pd.Timestamp(d).strftime("%Y-%m-%d") for d in stack.dates)
        gaps = [
            (b - a).days for a, b in zip(stack.dates, stack.dates[1:])
        ]
        typical = f"{pd.Series(gaps).mode().iloc[0]}d" if gaps else "-"
        print(f"{stack.key:<18} {len(stack.dates):>2} date(s)   cadence {typical:>4}")
        print(f"    {dates}")
        if gaps:
            for a, b, g in zip(stack.dates, stack.dates[1:], gaps):
                if g <= 13:
                    continue
                first, second = pd.Timestamp(a), pd.Timestamp(b)
                overlaps_mission_gap = first < MISSION_GAP_END and second > MISSION_GAP_START
                why = " (crosses the documented NISAR instrument gap)" if overlaps_mission_gap else ""
                print(f"    note: {g}-day gap {first.date()} -> {second.date()}{why}")
        print()

    best = stacks[0]
    print("-" * 78)
    print(f"Most usable stack: {best.key} with {len(best.dates)} date(s).")
    print("Gate 2 needs >= 3 usable dates, or a clearly strong 2-date story.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    ap.add_argument("--maturity", help="Override data maturity: PROVISIONAL | VALIDATED | BETA.")
    ap.add_argument("--processing-level", default=None, help="GCOV (default), GSLC, GUNW ...")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "interim" / "nisar_gcov_scenes.csv")
    ap.add_argument("--stack", help="Restrict the date table to one geometry, e.g. 151/73/DESC.")
    ap.add_argument("--max-results", type=int, default=None)
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    kwargs = area.as_search_kwargs()
    if args.maturity:
        kwargs["dataMaturity"] = args.maturity.upper()
    if args.processing_level:
        kwargs["processingLevel"] = args.processing_level.upper()

    print("=" * 78)
    print(f"AOI      : {area.name} - {area.title}")
    print(f"Search   : {kwargs}")
    print("=" * 78)

    df = search_asf(kwargs, args.max_results)
    if df.empty:
        print("No products returned.")
        return 1

    if args.maturity:
        df = df[df["maturity"] == args.maturity.upper()]
    if args.processing_level:
        df = df[df["product_type"] == args.processing_level.upper()]
    if args.max_results:
        df = df.head(args.max_results)

    before = len(df)
    df = dedupe_latest(df)
    if before != len(df):
        print(f"Deduped {before - len(df)} reprocessed duplicate(s) - kept the latest processing date.")

    stacks = summarise_stacks(df)
    print_summary(df, stacks)

    if args.stack:
        track, frame, direction = args.stack.split("/")
        df = pick_stack(df, int(track), int(frame), direction)
        print(f"\nRestricted to stack {args.stack}: {len(df)} date(s).")
        stacks = summarise_stacks(df)

    args.out = args.out if args.out.is_absolute() else (REPO_ROOT / args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "granule", "acquisition_date", "track", "frame", "direction",
        "polarizations", "product_type", "maturity", "crid", "size_mb", "url",
    ]
    df[[c for c in cols if c in df.columns]].to_csv(args.out, index=False)
    print(f"\nWrote {len(df)} product row(s) -> {args.out.relative_to(REPO_ROOT)}")

    dates_out = args.out.with_name("nisar_gcov_dates.csv")
    date_rows = []
    for stack in stacks:
        for d in stack.dates:
            date_rows.append({"track": stack.track, "frame": stack.frame, "direction": stack.direction, "date": pd.Timestamp(d).date()})
    pd.DataFrame(date_rows).to_csv(dates_out, index=False)
    print(f"Wrote {len(date_rows)} usable date row(s) -> {dates_out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
