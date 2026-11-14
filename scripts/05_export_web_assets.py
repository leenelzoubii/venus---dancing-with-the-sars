"""Step 5 - export the static web assets the app loads (no backend, no API keys).

Reads the cached AOI windows from step 3 and writes, into ``web/assets/``:

* one greyscale dB overlay per date and polarization;
* one diverging change overlay per date relative to the first date;
* a manifest with bounds, stretches, water areas and provenance for every layer.

    python scripts/05_export_web_assets.py --aoi dead_sea_east
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from shapely import wkt as shapely_wkt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change, webexport  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

ASSETS = REPO_ROOT / "web" / "assets"


def load_sidecars(indir: Path, pols: list[str]) -> list[dict]:
    cards = []
    for path in sorted(indir.glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        if not all(p in card.get("layers", {}) for p in pols):
            continue
        card["_json"] = path
        cards.append(card)
    return sorted(cards, key=lambda c: c["acquisition_date"])


def load_layer(card: dict, pol: str) -> np.ndarray:
    stem = card["_json"].stem
    return np.load(card["_json"].with_name(f"{stem}_{pol}.npy"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    ap.add_argument("--indir", type=Path, default=None)
    ap.add_argument("--outdir", type=Path, default=ASSETS)
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    indir = args.indir or (REPO_ROOT / "data" / "raw" / "subsets" / area.name)
    if not indir.exists():
        raise SystemExit(f"No subsets in {indir}. Run scripts/03_fetch_subset.py first.")

    pols = [p.upper() for p in area.processing.get("comparison_polarizations", ["HH", "HV"])]
    filt = area.processing.get("speckle_filter", "median")
    win = int(area.processing.get("speckle_window", 5))
    factor = max(1, int(area.processing.get("multilook", 1)))
    pixel_m = float(area.processing.get("pixel_spacing_m", 20)) * factor
    band = float(area.processing.get("water_band_db", 1.5))

    cards = load_sidecars(indir, pols)
    if not cards:
        raise SystemExit(f"No subsets with all of {pols} in {indir}.")

    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    for stale in outdir.glob("*.png"):
        stale.unlink()

    print(f"AOI {area.name}: {len(cards)} date(s) x {len(pols)} polarization(s)")
    print(f"Grid: {factor}x{factor} multilook -> {pixel_m:.0f} m, {filt} {win}x{win}\n")

    # --- every date, every polarization ------------------------------------------------
    db_cache: dict[tuple[str, str], np.ndarray] = {}
    dates_payload: list[dict] = []

    for card in cards:
        day = card["acquisition_date"]
        entry = {
            "date": day,
            "granule": card["granule"],
            "url": card["url"],
            "maturity": card.get("maturity"),
            "crid": card.get("crid"),
            "rows": card["rows"],
            "cols": card["cols"],
            "bounds": webexport.lon_lat_bounds(card, pixel_m),
            "layers": {},
        }
        for pol in pols:
            power = load_layer(card, pol)
            if factor > 1:
                power = change.multilook_power(power, factor)
            db = change.speckle_filter(change.power_to_db(power), filt, win)
            db_cache[(day, pol)] = db

            finite = db[np.isfinite(db)]
            vmin, vmax = (float(v) for v in np.percentile(finite, [2, 98]))
            threshold = change.otsu_threshold(db)
            water = change.area_km2(change.water_mask(db, threshold), pixel_m)
            sensitivity = change.threshold_sensitivity(db, threshold, half_width_db=band, pixel_size_m=pixel_m)
            layer = webexport.Layer(
                png=f"{day}_{pol}.png",
                vmin=round(vmin, 2),
                vmax=round(vmax, 2),
                water_km2=round(water, 1),
                water_threshold_db=round(float(threshold), 2),
                water_low_km2=round(min(a for _, a in sensitivity), 1),
                water_high_km2=round(max(a for _, a in sensitivity), 1),
            )
            webexport.render_grey(db, vmin, vmax).save(outdir / layer.png)
            entry["layers"][pol] = layer.as_dict()
        dates_payload.append(entry)
        print(f"  {day}: " + "  ".join(
            f"{pol} {entry['layers'][pol]['water_km2']:.0f} km2" for pol in pols
        ))

    # --- change layers, each date relative to the first --------------------------------
    first = dates_payload[0]["date"]
    changes = []
    for entry in dates_payload[1:]:
        day = entry["date"]
        change_entry = {"date": day, "first": first, "layers": {}}
        for pol in pols:
            diff = change.difference_db(db_cache[(day, pol)], db_cache[(first, pol)])
            finite = diff[np.isfinite(diff)]
            offset = float(np.median(finite))
            corrected = diff - offset
            limit = max(float(np.percentile(np.abs(corrected[np.isfinite(corrected)]), 98)), 0.5)
            png = f"change_{first}_{day}_{pol}.png"
            webexport.render_change(corrected, limit).save(outdir / png)
            change_entry["layers"][pol] = {
                "png": png,
                "limit_db": round(limit, 2),
                "offset_dB_removed": round(offset, 2),
                "median_dB": round(offset, 2),
                "frac_darker_3db": round(float(np.nanmean(diff < -3)), 4),
                "frac_brighter_3db": round(float(np.nanmean(diff > 3)), 4),
            }
        changes.append(change_entry)
        print(f"  change {first} -> {day}: offset {change_entry['layers'][pols[0]]['offset_dB_removed']:+.2f} dB, "
              f"scale +/-{change_entry['layers'][pols[0]]['limit_db']:.2f} dB")

    # --- manifest ----------------------------------------------------------------------
    aoi_shape = shapely_wkt.loads(area.wkt)
    west, south, east, north = aoi_shape.bounds
    all_bounds = np.array([d["bounds"] for d in dates_payload])
    rows, cols = dates_payload[0]["rows"][1] - dates_payload[0]["rows"][0], dates_payload[0]["cols"][1] - dates_payload[0]["cols"][0]

    manifest = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aoi": {
            "name": area.name,
            "title": area.title,
            "story": area.story,
            "wkt": area.wkt,
            "bbox_wgs84": [round(south, 5), round(west, 5), round(north, 5), round(east, 5)],
        },
        "mission": {
            "sensor": "NISAR L-band SAR (NASA / ISRO)",
            "product": "L2 GCOV - Geocoded Polarimetric Covariance",
            "quantity": "gamma-0 normalised radar backscatter (NRB)",
            "maturity": "PROVISIONAL",
            "crid": dates_payload[0].get("crid"),
            "track": cards[0]["track"],
            "frame": cards[0]["frame"],
            "direction": cards[0]["direction"],
            "epsg": 32636,
        },
        "processing": {
            "db": "10*log10(power) - as stated by the product itself",
            "multilook": factor,
            "pixel_spacing_m": pixel_m,
            "speckle_filter": f"{filt} {win}x{win}",
            "stretch": "2-98 percentile per image",
            "water_threshold": "Otsu per image",
            "water_band_db": band,
            "scene_offset_removed": True,
        },
        "grid": {
            "rows": int(rows),
            "cols": int(cols),
            "bounds": [
                round(float(all_bounds[:, 0].min()), 5),
                round(float(all_bounds[:, 1].min()), 5),
                round(float(all_bounds[:, 2].max()), 5),
                round(float(all_bounds[:, 3].max()), 5),
            ],
        },
        "polarizations": pols,
        "dates": dates_payload,
        "changes": changes,
        "notes": [
            "One geometry only: descending track 151 / frame 073. Ascending products exist but are never mixed in.",
            "NISAR instrument data gap 2026-07-27T22:03Z to 2026-08-10T00:55Z, so the series jumps 07-18 to 08-11.",
            "PROVISIONAL products: fully calibrated, partially validated. Reprocessing expected in 2027.",
            "Wind roughens open water and brightens it; wet salt crust can be bright too. Water masks are thresholded and quoted with a band.",
        ],
    }
    webexport.write_manifest(outdir / "manifest.json", manifest)

    # A JSON file cannot be fetched from file:// (browser CORS), so ship the same payload as a
    # script too. That is what lets the app run by double-clicking web/index.html, offline.
    (outdir / "manifest.js").write_text(
        "window.VENUS_MANIFEST = " + json.dumps(manifest, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    total = sum(f.stat().st_size for f in outdir.glob("*"))
    print(f"\nWrote {len(list(outdir.glob('*.png')))} PNG(s) + manifest.json to {outdir.relative_to(REPO_ROOT)}")
    print(f"Total asset size: {total / 1e6:.1f} MB")
    print("Next: open web/index.html (or run a local server) to see the app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
