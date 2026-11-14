"""Step 10 - build the places list the site shows, from the config plus the coverage survey.

Every study area in config/study_area.yaml becomes a place the app can display. A place carries its
polygon bounds and what the archive actually holds for it (product count, best stack, date range).

Crucially, a place is only marked ``processed: true`` when a manifest for it exists in web/data/.
For every other place the app draws the outline and reports the archive coverage, and says plainly that
the imagery has not been processed yet. It never shows imagery from a different place.

    python scripts/10_build_places.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from shapely import wkt as shapely_wkt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import webexport as wx  # noqa: E402
from venus.config import REPO_ROOT, load_config  # noqa: E402

INTERIM = REPO_ROOT / "data" / "interim"
WEB_DATA = REPO_ROOT / "web" / "data"
PROCESSED_AOI = "dead_sea_east"   # the only area with a full processed series so far


def main() -> int:
    config = load_config(REPO_ROOT / "config" / "study_area.yaml")
    survey_path = INTERIM / "coverage_survey.csv"
    survey = pd.read_csv(survey_path).set_index("aoi") if survey_path.exists() else pd.DataFrame()

    places = []
    for entry in config["aois"]:
        name = entry["name"]
        shape = shapely_wkt.loads(entry["wkt"])
        west, south, east, north = shape.bounds
        row = survey.loc[name] if (not survey.empty and name in survey.index) else None
        places.append({
            "name": name,
            "title": entry.get("title", name),
            "story": " ".join((entry.get("story") or "").split()),
            "coord_note": entry.get("coord_note", ""),
            "bounds": [[round(south, 6), round(west, 6)], [round(north, 6), round(east, 6)]],
            "wkt": entry["wkt"],
            "processed": name == PROCESSED_AOI and (WEB_DATA / "manifest.json").exists(),
            "coverage": {
                "products": int(row["products"]) if row is not None and pd.notna(row.get("products")) else 0,
                "stack": str(row["stack"]) if row is not None and pd.notna(row.get("stack", None)) else "",
                "dates": int(row["dates"]) if row is not None and pd.notna(row.get("dates", None)) else 0,
                "first": str(row["first"]) if row is not None and pd.notna(row.get("first", None)) else "",
                "last": str(row["last"]) if row is not None and pd.notna(row.get("last", None)) else "",
                "note": str(row["note"]) if row is not None and pd.notna(row.get("note", None)) else "",
            },
        })

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active": PROCESSED_AOI,
        "processing_note": (
            "Only the Dead Sea east shore has processed imagery. Other places have confirmed NISAR "
            "coverage in the archive but their subsets have not been downloaded and processed yet."
        ),
        "default_wkt": wkt_of(config, PROCESSED_AOI),
        "places": places,
    }
    wx.write_json(WEB_DATA / "places.json", payload)
    wx.write_js(WEB_DATA / "places.js", "places", payload)

    total = len(places)
    processed = sum(1 for p in places if p["processed"])
    print(f"{total} places; {processed} processed; {total - processed} with archive coverage only")
    for place in places:
        c = place["coverage"]
        flag = "PROCESSED" if place["processed"] else ("covered" if c["products"] else "no coverage")
        print(f"  {place['name']:20s} {flag:10s} {c['dates']:2d} dates  {c['stack']:16s} {c['first']} .. {c['last']}")
    print(f"\nWrote {(WEB_DATA / 'places.json').relative_to(REPO_ROOT)} and places.js")
    return 0


def wkt_of(config: dict, name: str) -> str:
    for entry in config["aois"]:
        if entry["name"] == name:
            return entry["wkt"]
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
