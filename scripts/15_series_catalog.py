"""Step 15 - group NISAR GCOV products into calibration SERIES per place.

A series is (maturity, CRID, track, direction, polarizations). Series are never mixed, so this
catalog is the single source of truth the builder and the app both follow. It reads every scenes CSV
that exists for the place (PROVISIONAL, BETA, VALIDATED).

    python scripts/15_series_catalog.py --aoi dead_sea_full
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT  # noqa: E402

INTERIM = REPO_ROOT / "data" / "interim"


def scenes_files(place: str) -> list[Path]:
    candidates = [
        INTERIM / f"scenes_{place}.csv",
        INTERIM / f"scenes_{place}_beta.csv",
        INTERIM / f"scenes_{place}_validated.csv",
    ]
    return [path for path in candidates if path.exists()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", required=True)
    args = ap.parse_args()

    frames = []
    for path in scenes_files(args.aoi):
        frame = pd.read_csv(path, parse_dates=["acquisition_date"])
        frame["source_csv"] = path.name
        frames.append(frame)
    if not frames:
        raise SystemExit(f"no scenes CSV for {args.aoi}; run scripts/01_search_nisar.py first")
    data = pd.concat(frames, ignore_index=True)
    data = data.drop_duplicates(subset=["granule"])
    data["day"] = data["acquisition_date"].dt.strftime("%Y-%m-%d")

    rows = []
    for (maturity, crid, track, direction, pols), group in data.groupby(
            ["maturity", "crid", "track", "direction", "polarizations"], dropna=False):
        frames_seen = Counter(group["frame"].tolist())
        frame = frames_seen.most_common(1)[0][0]
        days = sorted(group["day"].unique())
        pol_token = "".join(sorted(set(str(pols).split("+"))))
        rows.append({
            "series_id": f"{int(track)}-{str(direction)[:4].upper()}-{crid}-{pol_token}",
            "maturity": maturity, "crid": crid, "track": int(track), "frame": int(frame),
            "direction": direction, "polarizations": pols,
            "n_dates": len(days), "first_date": days[0], "last_date": days[-1],
            "dates": ";".join(days),
        })
    catalog = pd.DataFrame(rows).sort_values(["maturity", "n_dates"], ascending=[True, False])
    out = INTERIM / f"series_catalog_{args.aoi}.csv"
    catalog.to_csv(out, index=False)

    print(f"{args.aoi}: {len(catalog)} series -> {out.relative_to(REPO_ROOT)}")
    for _, row in catalog.iterrows():
        print(f"  {row.series_id:18s} {row.maturity:12s} track {row.track} {str(row.direction)[:4]:5s} "
              f"{row.n_dates:2d} dates  {row.first_date} .. {row.last_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
