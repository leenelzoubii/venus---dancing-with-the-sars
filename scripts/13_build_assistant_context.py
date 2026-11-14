"""Step 13 - write the machine-readable context a future assistant/chatbot will need.

The chatbot is NOT implemented. This script only records what such a helper would have to know, so that
whoever builds it starts from verified facts instead of guessing: what each place contains, which
products are processed and which are only available in the archive, what the numbers mean, what the
known limitations are, and which questions the data cannot answer.

Outputs web/data/assistant_context.json and .js (loaded only if a chat feature is added later).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import webexport as wx  # noqa: E402
from venus.config import REPO_ROOT, load_config  # noqa: E402

WEB_DATA = REPO_ROOT / "web" / "data"
INTERIM = REPO_ROOT / "data" / "interim"


def main() -> int:
    config = load_config(REPO_ROOT / "config" / "study_area.yaml")
    places = json.loads((WEB_DATA / "places.json").read_text(encoding="utf-8"))
    survey = {}
    survey_path = INTERIM / "coverage_survey.csv"
    if survey_path.exists():
        import pandas as pd
        frame = pd.read_csv(survey_path)
        survey = {row["aoi"]: row.to_dict() for _, row in frame.iterrows()}

    entries = []
    for place in places["places"]:
        name = place["name"]
        bundle = WEB_DATA / name / "manifest.js"
        entry = {
            "name": name,
            "title": place["title"],
            "processed": bundle.exists(),
            "coord_note": place.get("coord_note", ""),
            "coverage": place.get("coverage", {}),
        }
        if bundle.exists():
            manifest = json.loads((WEB_DATA / name / "manifest.json").read_text(encoding="utf-8"))
            entry.update({
                "dates": manifest["dates"],
                "n_dates": len(manifest["dates"]),
                "polarizations": manifest["polarizations"],
                "track": manifest["track"],
                "frame": manifest["frame"],
                "direction": manifest["direction"],
                "crs": manifest["native_crs"],
                "crid": manifest["crid"],
                "maturity": manifest["maturity"],
                "reference_date": manifest["reference_date"],
                "kinds_available": sorted({layer["kind"] for layer in manifest["layers"]}),
                "has_water": any(layer["kind"] == "water" for layer in manifest["layers"]),
            })
        entries.append(entry)

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": "Ground truth for a future assistant that helps users navigate and interpret this app.",
        "status": "The assistant is not implemented. This file only records verified facts and limits.",
        "app_facts": {
            "app": "Team Venus - Seeing the Dead Sea through the clouds",
            "event": "NASA Space Apps Challenge 2026, challenge 'Dancing with the SARs'",
            "data": "NISAR L2 GCOV (geocoded polarimetric covariance), PROVISIONAL",
            "units": "gamma-0 backscatter in dB (10*log10 of power)",
            "how_layers_are_made": [
                "10*log10(gamma-0 power)",
                "3x3 multilook in power (60 m) for display and change",
                "median 5x5 speckle filter",
                "scene-wide offset removed (land median) before any comparison",
                "reprojected from the product's UTM zone to EPSG:3857",
            ],
            "definitions": {
                "change": "each date minus the first date of that place, after offset removal; blue = weaker echo, orange = stronger",
                "water_mask": "method B: drop HV above -15 dB, then Otsu on the remainder, cleaned of blobs smaller than 10 px",
                "detection_band": "pixels whose water/land status flips if the threshold moves +/-1.5 dB",
                "detection_limit": "offset MAD plus land-definition sensitivity, converted to km2 with the measured km2 per dB",
                "scene_offset": "median of (date minus reference) over land only; cause unresolved, calibration drift or seasonal change",
            },
        },
        "places": entries,
        "known_limits": [
            "All products are PROVISIONAL; reprocessing may change numbers.",
            "One geometry per place. Places on different tracks are separate series and must never be compared.",
            "Some granules are single-polarization (e.g. SHSH, HH only), so a place may have no HV and therefore no water series.",
            "Melehat Sdom is mostly water, so its offset is estimated on all finite pixels, which is weaker.",
            "About 7-8 percent of mapped water pixels at the Dead Sea lie outside the main lake body; hypothesis: dark terrain or radar shadow.",
            "The instrument outage 2026-07-27 to 2026-08-10 shows as a gap between consecutive dates.",
            "GSLC, RSLC and GUNW exist in the archive but are not processed by this pipeline; only GCOV is displayed.",
        ],
        "questions_the_data_cannot_answer": [
            "Why the scene offset exists.",
            "Whether the eastern-plain candidate patches are real ground change (no field check, no hypothesis entered yet).",
            "Any water-area change smaller than the detection limit.",
        ],
        "suggested_assistant_behaviour": [
            "Answer only from this file and the loaded manifest; say 'not available' otherwise.",
            "Never quote a water number without its band.",
            "Label causes as hypotheses, never as findings.",
            "Point users to the layer information panel for provenance.",
        ],
    }

    wx.write_json(WEB_DATA / "assistant_context.json", payload)
    wx.write_js(WEB_DATA / "assistant_context.js", "assistant_context", payload)
    print(f"places recorded: {len(entries)}  processed: {sum(1 for e in entries if e['processed'])}")
    print(f"wrote {(WEB_DATA / 'assistant_context.json').relative_to(REPO_ROOT)} and .js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
