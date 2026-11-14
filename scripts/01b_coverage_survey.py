"""Step 1b - which study areas does NISAR actually cover, and with which geometry?

Adding an AOI to the config does not create data. Before promising coverage for a new place we ask the
archive, once per AOI, and write a short answer: how many PROVISIONAL GCOV products intersect it, which
track/frame carries the most dates, and what date range that stack spans.

    python scripts/01b_coverage_survey.py

Outputs data/interim/coverage_survey.csv and prints a table. Nothing is downloaded.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import auth, search  # noqa: E402
from venus.config import REPO_ROOT, load_config, load_study_area  # noqa: E402

INTERIM = REPO_ROOT / "data" / "interim"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", help="Restrict to these AOI names.")
    args = ap.parse_args()

    config = load_config(REPO_ROOT / "config" / "study_area.yaml")
    names = [a["name"] for a in config["aois"]]
    if args.only:
        names = [n for n in names if n in args.only]

    auth.login()
    rows = []
    for name in names:
        area = load_study_area(name)
        kwargs = area.as_search_kwargs()
        # Geometry filters would hide coverage: search the AOI without a fixed track or frame.
        kwargs.pop("relativeOrbit", None)
        kwargs.pop("frame", None)
        kwargs.pop("flightDirection", None)
        try:
            import asf_search as asf
            results = asf.search(**kwargs)
            frame = search.dedupe_latest(search.results_to_frame(results))
        except Exception as exc:  # noqa: BLE001 - a network hiccup must not kill the survey
            rows.append({"aoi": name, "products": 0, "note": f"search failed: {type(exc).__name__}"})
            print(f"{name:22s} search failed: {exc}")
            continue

        if frame.empty:
            rows.append({"aoi": name, "products": 0, "note": "no PROVISIONAL GCOV products intersect this AOI"})
            print(f"{name:22s} 0 products")
            continue

        stacks = search.summarise_stacks(frame)
        best = stacks[0]
        rows.append({
            "aoi": name,
            "products": int(len(frame)),
            "stack": f"{best.track}/{best.frame}/{best.direction}",
            "dates": len(best.dates),
            "first": str(best.dates[0].date()) if best.dates else "",
            "last": str(best.dates[-1].date()) if best.dates else "",
            "note": "",
        })
        print(f"{name:22s} {len(frame):3d} products   best stack {best.track}/{best.frame}/{best.direction} "
              f"{len(best.dates)} dates {best.dates[0].date()} .. {best.dates[-1].date()}")

    table = pd.DataFrame(rows)
    table.to_csv(INTERIM / "coverage_survey.csv", index=False, encoding="utf-8")
    print(f"\nWrote {INTERIM.relative_to(REPO_ROOT) / 'coverage_survey.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
