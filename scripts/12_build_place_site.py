"""Step 12 - build the web bundle for every place that has cached data.

One place in, one folder out: ``web/data/<place>/`` with its layers plus manifest, water stats and
offsets. The app then loads only the place the user selects.

This is deliberately a single builder rather than a chain of scripts, because the per-place
intermediate files would otherwise collide: two places both want an ``offsets.json``, and each must
have its own.

    python scripts/12_build_place_site.py --aoi potash_city
    python scripts/12_build_place_site.py --all

Rules kept from the earlier hours: one geometry per place, offsets estimated on land only and applied
explicitly, water by method B with a +/-1.5 dB band, PROVISIONAL only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from affine import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change, water, webexport as wx  # noqa: E402
from venus.config import REPO_ROOT, load_config, load_study_area  # noqa: E402

SUBSETS = REPO_ROOT / "data" / "raw" / "subsets"
WEB_DATA = REPO_ROOT / "web" / "data"
MULTILOOK = 3
SPECKLE = ("median", 5)
BAND_DB = 1.5
PRIMARY = "B"


def load_place(place: str) -> list[dict]:
    """Every cached acquisition for a place, oldest first, with the arrays that exist."""
    folder = SUBSETS / place
    cards = []
    for sidecar in sorted(folder.glob("*.json")):
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        stem = sidecar.stem
        arrays = {}
        for pol in ("HH", "HV"):
            path = folder / f"{stem}_{pol}.npy"
            if path.exists():
                arr = np.load(path)
                if arr.size == 0:
                    print(f"  {stem}: {pol} window is empty, skipping this date")
                    arrays = {}
                    break
                arrays[pol] = arr
        if not arrays:
            continue
        looks_path = folder / f"{stem}_looks.npy"
        cards.append({
            "meta": meta,
            "stem": stem,
            "arrays": arrays,
            "looks": np.load(looks_path) if looks_path.exists() else None,
        })
    return sorted(cards, key=lambda c: c["meta"]["acquisition_date"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", help="One place name.")
    ap.add_argument("--all", action="store_true", help="Every place in the config that has cached data.")
    args = ap.parse_args()

    config = load_config(REPO_ROOT / "config" / "study_area.yaml")
    names = [args.aoi] if args.aoi else [a["name"] for a in config["aois"]]
    built = []

    for name in names:
        cards = load_place(name)
        if len(cards) < 2:
            print(f"{name:18s} skipped: {len(cards)} cached date(s), need at least 2 for a change product")
            continue
        area = load_study_area(name)

        # One grid or nothing: dates fetched by a different reader can have a different window size,
        # and comparing them would draw change that is only a misalignment. Keep the largest group of
        # dates sharing a shape and say what was dropped.
        shapes = {}
        for card in cards:
            first_pol = sorted(card["arrays"])[0]
            shapes.setdefault(card["arrays"][first_pol].shape, []).append(card)
        main_shape = max(shapes, key=lambda s: len(shapes[s]))
        if len(shapes) > 1:
            dropped = [c["meta"]["acquisition_date"] for s, group in shapes.items() if s != main_shape for c in group]
            print(f"{name:18s} dropped {len(dropped)} date(s) on a different grid: {', '.join(dropped)}")
        cards = shapes[main_shape]
        if len(cards) < 2:
            print(f"{name:18s} skipped: fewer than 2 dates share one grid")
            continue

        outdir = WEB_DATA / name
        (outdir / "layers").mkdir(parents=True, exist_ok=True)
        for stale in (outdir / "layers").glob("*.png"):
            stale.unlink()

        meta0 = cards[0]["meta"]
        x = np.asarray(meta0["x"], dtype="float64")
        y = np.asarray(meta0["y"], dtype="float64")
        t20 = wx.grid_transform(x, y, float(meta0["pixel_spacing_m"]))
        t60 = Affine(t20.a * MULTILOOK, 0.0, t20.c, 0.0, t20.e * MULTILOOK, t20.f)
        dates = [c["meta"]["acquisition_date"] for c in cards]
        reference = dates[0]
        # Only a polarization present on every date can be compared across the series.
        pols = sorted(set.intersection(*[set(c["arrays"]) for c in cards]))
        missing = sorted({p for c in cards for p in c["arrays"]} - set(pols))
        if missing:
            print(f"{name:18s} not on every date, excluded: {', '.join(missing)}")
        if not pols:
            print(f"{name:18s} skipped: no polarization shared by all dates")
            continue

        # ---- dB at 60 m for every date and polarization --------------------------------
        db = {}
        for card in cards:
            for pol in pols:
                power = change.multilook_power(card["arrays"][pol], MULTILOOK)
                db[(card["meta"]["acquisition_date"], pol)] = change.speckle_filter(
                    change.power_to_db(power), *SPECKLE
                )

        # Drop any polarization with no finite data at all (an edge-of-swath window can be all NaN).
        pols = [p for p in pols if any(np.isfinite(db[(d, p)]).any() for d in dates)]
        if not pols:
            print(f"{name:18s} skipped: no finite data in any polarization")
            continue

        # ---- offsets on land only, estimated against the reference date ----------------
        if "HV" in pols:
            land = change.land_mask(db[(reference, "HV")], hv_land_cut_db=-15.0)
            land_basis = "HV > -15 dB"
            if int(land.sum()) < 50:
                # A mostly-water AOI can have almost no land above the cut. Falling back keeps the
                # offset measurable, but it is then estimated over water too, which is weaker and
                # is recorded as such.
                land = np.isfinite(db[(reference, "HV")])
                land_basis = "all finite pixels (too little land above -15 dB)"
                print(f"{name:18s} little land in the window: offset estimated on all finite pixels")
        else:
            # Single-polarization granule: no HV water channel exists, so the offset is estimated on
            # every finite pixel and the water layers are skipped. Recorded in the manifest notes.
            land = np.isfinite(db[(reference, pols[0])])
            land_basis = "all finite pixels (no HV in this place)"
        offsets = []
        for day in dates:
            for pol in pols:
                if day == reference:
                    offsets.append({"date": day, "pol": pol, "offset_dB": 0.0, "n_pixels": int(land.sum()), "MAD_dB": 0.0})
                    continue
                value, n, mad = change.robust_offset_db(db[(day, pol)], db[(reference, pol)], land)
                offsets.append({"date": day, "pol": pol, "offset_dB": round(float(value), 3),
                                "n_pixels": n, "MAD_dB": round(float(mad), 3)})
        offset_of = {(o["date"], o["pol"]): o["offset_dB"] for o in offsets}

        # ---- fixed scales across all dates of this place -------------------------------
        back_limits = {}
        for pol in pols:
            pooled = np.concatenate([db[(d, pol)][np.isfinite(db[(d, pol)])].ravel() for d in dates])
            back_limits[pol] = tuple(float(v) for v in np.percentile(pooled, [2, 98]))
        change_limits = {}
        deltas = {}
        for pol in pols:
            for day in dates[1:]:
                deltas[(day, pol)] = (db[(day, pol)] - offset_of.get((day, pol), 0.0)) - db[(reference, pol)]
            pooled = np.concatenate([np.abs(deltas[(d, pol)][np.isfinite(deltas[(d, pol)])]).ravel() for d in dates[1:]])
            if pooled.size == 0:
                print(f"{name:18s} {pol}: no finite change values, skipping change layers")
                change_limits[pol] = 1.0
                continue
            change_limits[pol] = round(min(6.0, float(np.percentile(pooled, 99))), 2)

        layers = []
        base = {
            "product": "NISAR L2 GCOV", "crid": meta0.get("crid"), "maturity": meta0.get("maturity"),
            "track": meta0.get("track"), "frame": meta0.get("frame"), "direction": meta0.get("direction"),
            "native_crs": f"EPSG:{meta0.get('epsg', 32636)}", "display_crs": wx.CRS_WEB,
        }
        steps = ["10*log10(gamma-0)", f"{MULTILOOK}x{MULTILOOK} multilook in power (60 m)",
                 f"{SPECKLE[0]} {SPECKLE[1]}x{SPECKLE[1]}", "reprojected to EPSG:3857"]

        def save(image, filename, **fields):
            size = wx.save_png(image, outdir / "layers" / filename)
            layers.append({"file": f"layers/{filename}", **base, **fields})
            return size

        bounds = None
        for day in dates:
            for pol in pols:
                dst, dst_t = wx.reproject_to_web(db[(day, pol)], t60)
                bounds = bounds or wx.web_bounds_lonlat(dst_t, *dst.shape)
                vmin, vmax = back_limits[pol]
                save(wx.grey_rgba(dst, vmin, vmax), f"backscatter_{pol}_{day}.png",
                     id=f"backscatter_{pol}_{day}", kind="backscatter", label=f"Backscatter {pol} {day}",
                     polarization=pol, date=day, bounds=wx.web_bounds_lonlat(dst_t, *dst.shape),
                     vmin=vmin, vmax=vmax, colormap="grey: dark = smooth (water), bright = rough",
                     description=f"Gamma-0 backscatter {pol} on {day}.",
                     offset_applied_db=0.0, display_multilook=MULTILOOK, processing=steps)

        for day in dates[1:]:
            for pol in pols:
                dst, dst_t = wx.reproject_to_web(deltas[(day, pol)], t60)
                limit = change_limits[pol]
                save(wx.change_rgba(dst, limit), f"change_{pol}_{day}.png",
                     id=f"change_{pol}_{day}", kind="change", label=f"Change {pol} {day} minus {reference}",
                     polarization=pol, date=day, reference=reference,
                     bounds=wx.web_bounds_lonlat(dst_t, *dst.shape), vmin=-limit, vmax=limit,
                     colormap="diverging: blue = weaker echo, orange = stronger echo",
                     description=f"{pol} change on {day} relative to {reference}, scene offset removed.",
                     offset_applied_db=round(offset_of.get((day, pol), 0.0), 3),
                     display_multilook=MULTILOOK,
                     processing=steps + ["scene offset removed (land median)"])

        # ---- water where HV exists -----------------------------------------------------
        water_rows = []
        if "HV" in pols:
            for card in cards:
                day = card["meta"]["acquisition_date"]
                hv_db = change.speckle_filter(change.power_to_db(card["arrays"]["HV"]), *SPECKLE) - offset_of.get((day, "HV"), 0.0)
                threshold = water.two_step_threshold(hv_db)
                if not np.isfinite(threshold):
                    continue
                centre = water.clean_mask(np.isfinite(hv_db) & (hv_db < threshold))
                low = water.clean_mask(np.isfinite(hv_db) & (hv_db < threshold - BAND_DB))
                high = water.clean_mask(np.isfinite(hv_db) & (hv_db < threshold + BAND_DB))
                flip = low ^ high
                dst_w, dst_t20 = wx.reproject_to_web(centre, t20, mask=True)
                dst_b, _ = wx.reproject_to_web(flip, t20, mask=True)
                water_km2 = water.water_area_km2(centre, 20.0, clean=False)
                low_area = water.water_area_km2(low, 20.0, clean=False)
                high_area = water.water_area_km2(high, 20.0, clean=False)
                save(wx.mask_palette(dst_w, wx.WATER_RGB, wx.WATER_ALPHA), f"water_HV_{day}.png",
                     id=f"water_HV_{day}", kind="water", label=f"Open water HV {day}", polarization="HV",
                     date=day, bounds=wx.web_bounds_lonlat(dst_t20, *dst_w.shape),
                     colormap="cyan = open water (method B)", threshold_db=round(float(threshold), 2),
                     area_km2=round(water_km2, 2), band_low_km2=round(low_area, 2), band_high_km2=round(high_area, 2),
                     description=f"Open water on {day}: HV below {threshold:.2f} dB after land removal.",
                     offset_applied_db=offset_of.get((day, "HV"), 0.0), display_multilook=1,
                     processing=["10*log10", f"median {SPECKLE[1]}x{SPECKLE[1]}", "offset removed",
                                 "method B threshold", "blobs < 10 px removed"])
                save(wx.mask_palette(dst_b, wx.BAND_RGB, wx.BAND_ALPHA), f"water_band_{day}.png",
                     id=f"water_band_{day}", kind="band", label=f"Detection-limit band {day}",
                     polarization="HV", date=day, bounds=wx.web_bounds_lonlat(dst_t20, *dst_w.shape),
                     colormap="amber = pixels that flip within +/-1.5 dB", band_db=BAND_DB,
                     threshold_db=round(float(threshold), 2),
                     description=f"Pixels that change water status within +/-{BAND_DB} dB of the threshold.",
                     offset_applied_db=offset_of.get((day, "HV"), 0.0), display_multilook=1,
                     processing=["as water", f"band = threshold +/-{BAND_DB} dB"])
                water_rows.append({
                    "date": day,
                    "methods": {PRIMARY: {"threshold_db": round(float(threshold), 2), "area_km2": round(water_km2, 2),
                                          "low_km2": round(low_area, 2), "high_km2": round(high_area, 2)}},
                })

        areas = [r["methods"][PRIMARY]["area_km2"] for r in water_rows]
        verdict = ("No date-to-date change is larger than the measurement spread for this place."
                   if areas and (max(areas) - min(areas)) < 2.0 * BAND_DB * 10
                   else "Differences exist; check the band before calling any of them change.")
        manifest = {
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "place": {"name": name, "title": area.title, "wkt": area.wkt},
            "study_area": {"name": name, "title": area.title, "wkt": area.wkt, "story": area.story},
            "product": "NISAR L2 GCOV", "crid": meta0.get("crid"), "maturity": meta0.get("maturity"),
            "track": meta0.get("track"), "frame": meta0.get("frame"), "direction": meta0.get("direction"),
            "native_crs": f"EPSG:{meta0.get('epsg', 32636)}", "display_crs": wx.CRS_WEB,
            "reference_date": reference, "dates": dates, "polarizations": pols,
            "primary_water": {"method": PRIMARY, "polarization": "HV"},
            "scales": {"backscatter_db": {p: list(v) for p, v in back_limits.items()},
                       "change_db_symmetric": change_limits},
            "layers": layers, "bounds": bounds,
            "notes": [f"{len(dates)} PROVISIONAL dates on track {meta0.get('track')} frame {meta0.get('frame')}."],
        }
        wx.assert_provisional([{"id": "manifest", "crid": manifest["crid"]}])
        wx.write_json(outdir / "manifest.json", manifest)
        wx.write_js(outdir / "manifest.js", "place_manifest", manifest)

        stats = {
            "generated_utc": manifest["generated_utc"], "primary_method": PRIMARY, "primary_polarization": "HV",
            "band_db": BAND_DB, "primary_verdict": verdict, "primary_caption": "",
            "dates": water_rows, "summary": {}, "change_detection": {},
        }
        wx.write_json(outdir / "water_stats.json", stats)
        wx.write_js(outdir / "water_stats.js", "place_water_stats", stats)
        wx.write_json(outdir / "offsets.json", {"aoi": name, "reference_date": reference, "offsets": offsets})
        wx.write_js(outdir / "offsets.js", "place_offsets", {"aoi": name, "reference_date": reference, "offsets": offsets})
        built.append({"name": name, "dates": len(dates), "layers": len(layers), "pols": pols})
        print(f"{name:18s} {len(dates)} dates  {len(layers)} layers  pols {','.join(pols)}")

    print("\nBuilt:", len(built))
    for item in built:
        print(f"  {item['name']:18s} {item['dates']} dates {item['layers']} layers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
