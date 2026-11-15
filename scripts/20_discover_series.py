"""Step 20 - discover every maturity for every processed place (v4 tier 1).

One search per place over the full archive date range with NO maturity filter. Writes
data/interim/scenes_<place>_all.csv and prints one compact block per place: the primary geometry
(the track/direction the place was built on) and how many dates exist in each maturity, plus any
secondary geometries found.

    python scripts/20_discover_series.py

Reads places.json at runtime; never hard-codes the place list.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT, load_study_area  # noqa: E402

INTERIM = REPO_ROOT / "data" / "interim"
PLACES = json.loads((REPO_ROOT / "web" / "data" / "places.json").read_text(encoding="utf-8"))
START = "2025-10-01"


def search_module():
    path = REPO_ROOT / "scripts" / "01_search_nisar.py"
    spec = importlib.util.spec_from_file_location("search_nisar", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = search_module()
    names = [place["name"] for place in PLACES["places"] if place.get("processed")]
    for name in names:
        area = load_study_area(name)
        kwargs = area.as_search_kwargs()
        kwargs.pop("dataMaturity", None)
        kwargs["start"] = START
        try:
            frame = module.search_asf(kwargs)
        except Exception as exc:  # noqa: BLE001
            print(f"{name:16s} SEARCH FAILED {exc.__class__.__name__}")
            continue
        if frame.empty:
            print(f"{name:16s} no products in the archive for this window")
            continue
        frame["acq_day"] = pd.to_datetime(frame["acquisition_date"]).dt.strftime("%Y-%m-%d")
        out = INTERIM / f"scenes_{name}_all.csv"
        frame.to_csv(out, index=False)

        track = int(area.search.get("track", 0))
        direction = str(area.search.get("flight_direction", "")).upper()[:4]
        primary = frame[(frame["track"] == track) & (frame["direction"].str.upper().str[:4] == direction)]
        print(f"{name:16s} {len(frame)} products  primary {track}/{direction}  "
              f"{len(primary)} dates")
        for maturity, group in primary.groupby("maturity"):
            days = sorted(group["acq_day"].unique())
            print(f"    {maturity:12s} {len(days):2d} dates  {days[0]} .. {days[-1]}  "
                  f"CRID {','.join(sorted(group['crid'].dropna().unique()))}")
        others = frame[~frame.index.isin(primary.index)]
        if not others.empty:
            for (t, d), group in others.groupby(["track", "direction"]):
                print(f"    other geometry {t}/{d} {len(group['acq_day'].unique())} dates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
