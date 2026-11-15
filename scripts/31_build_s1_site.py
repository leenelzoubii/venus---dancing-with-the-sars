"""Step 31 - build the web bundle for S1 OPERA RTC-S1 places.

One place in, one folder out: ``web/data/<place>/`` with its layers plus manifest, water stats and
offsets. The app then loads only the place the user selects.

    python scripts/31_build_s1_site.py --place potash_city
    python scripts/31_build_s1_site.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from affine import Affine
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change, display as dx, water, webexport as wx  # noqa: E402
from venus.config import REPO_ROOT, load_config, load_study_area  # noqa: E402

S1_RAW = REPO_ROOT / "data" / "raw" / "s1"
WEB_DATA = REPO_ROOT / "web" / "data"
MULTILOOK = 3          # 30 m -> 90 m for analysis
SPECKLE = ("median", 5)
BAND_DB = 1.5
PRIMARY = "B"
# S1 target display resolution: 30 m native -> ~17 m in Web Mercator (at 31.5 deg)
# Allow 15-20 m band for S1
S1_TARGET_PX_M = (17.0, 20.0)
# Per-layer size budget
LAYER_BUDGET = 700_000
WHOLE_LAKE_BUDGET = 900_000


def load_s1_place(place: str) -> list[dict]:
    """Every cached S1 acquisition for a place, oldest first."""
    folder = S1_RAW / place
    cards = []
    for npz_path in sorted(folder.glob("*.npz")):
        data = np.load(npz_path)
        # Convert numpy arrays to plain Python types for metadata
        meta = {
            "acquisition_date": str(data["day"]),
            "crs": str(data["crs"]),
            "transform": data["transform"].tolist(),
            "bursts": int(data["bursts"]),
            "burst_ids": data["burst_ids"].tolist(),
            "pixel_spacing_m": 30.0,
        }
        arrays = {}
        for pol in ("VV", "VH"):
            key = pol.lower()
            if key in data:
                arr = data[key]
                if arr.size == 0:
                    print(f"  {meta['acquisition_date']}: {pol} window is empty, skipping this date")
                    arrays = {}
                    break
                arrays[pol] = arr
        if not arrays:
            continue
        cards.append({
            "meta": meta,
            "stem": npz_path.stem,
            "arrays": arrays,
            "mask": data["mask"],
        })
    return sorted(cards, key=lambda c: c["meta"]["acquisition_date"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--place", help="One place name.")
    ap.add_argument("--all", action="store_true", help="Every place in the config that has cached data.")
    args = ap.parse_args()

    config = load_config(REPO_ROOT / "config" / "study_area.yaml")
    names = [args.place] if args.place else [a["name"] for a in config["aois"]]
    built = []

    for name in names:
        cards = load_s1_place(name)
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
        for pattern in ("*.png", "*.webp"):
            for stale in (outdir / "layers").glob(pattern):
                for attempt in range(3):
                    try:
                        stale.unlink()
                        break
                    except PermissionError:
                        import time
                        time.sleep(0.5)

        meta0 = cards[0]["meta"]
        # The source CRS is the cached subset's recorded projection.
        src_crs = meta0["crs"]
        native_px = float(meta0["pixel_spacing_m"])
        t30 = wx.grid_transform(
            np.arange(cards[0]["arrays"]["VV"].shape[1]),
            np.arange(cards[0]["arrays"]["VV"].shape[0]),
            native_px
        )
        # Actually, we need the x/y coordinates from the transform
        transform = Affine(*meta0["transform"])
        rows, cols = cards[0]["arrays"]["VV"].shape
        x = np.arange(cols) * transform.a + transform.c
        y = np.arange(rows) * transform.e + transform.f
        t30 = wx.grid_transform(x, y, native_px)
        t90 = Affine(t30.a * MULTILOOK, 0.0, t30.c, 0.0, t30.e * MULTILOOK, t30.f)

        def to_web90(array, **kwargs):
            return wx.reproject_to_grid(array, t90, src_crs, g90_t, g90_h, g90_w, **kwargs)

        def to_web30(array, **kwargs):
            return wx.reproject_to_grid(array, t30, src_crs, g30_t, g30_h, g30_w, **kwargs)

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

        # ---- dB at 90 m for every date and polarization --------------------------------
        db = {}
        for card in cards:
            for pol in pols:
                power = change.multilook_power(card["arrays"][pol], MULTILOOK)
                db[(card["meta"]["acquisition_date"], pol)] = change.speckle_filter(
                    change.power_to_db(power), *SPECKLE
                )

        # Drop any polarization with no finite data at all.
        pols = [p for p in pols if any(np.isfinite(db[(d, p)]).any() for d in dates)]
        if not pols:
            print(f"{name:18s} skipped: no finite data in any polarization")
            continue

        # ---- display chain: one crop rectangle and one set of grids for every layer ------------
        import shapely.wkt as _wkt

        valid_pol = {}
        for card in cards:
            day = card["meta"]["acquisition_date"]
            for pol in pols:
                valid_pol[(day, pol)] = dx.valid_native(card["arrays"][pol], card["mask"])
        pooled_valid = np.ones(next(iter(valid_pol.values())).shape, dtype=bool)
        for valid in valid_pol.values():
            pooled_valid &= valid
        centre_lat = _wkt.loads(area.wkt).centroid.y
        # Use S1 target display resolution band
        crop, display_res, crop_fraction = dx.choose_crop(
            pooled_valid, t30, src_crs, area.wkt, centre_lat, native_px, target_px_m=S1_TARGET_PX_M
        )
        disp_t, disp_w, disp_h = dx.grid_for_rect(crop, display_res)
        resolution_fallback = ""
        if disp_w * disp_h > 4_500_000:
            display_res *= 1.5
            disp_t, disp_w, disp_h = dx.grid_for_rect(crop, display_res)
            resolution_fallback = "1.5x native instead of 2x, for the per-layer size budget"
            print(f"{name:18s} size fallback: display res {display_res:.1f} m")
        g90_t, g90_w, g90_h = dx.grid_for_rect(crop, 90.0)
        g30_t, g30_w, g30_h = dx.grid_for_rect(crop, 30.0)
        bounds = wx.web_bounds_lonlat(disp_t, disp_h, disp_w)
        display_limits = {}
        for pol in pols:
            display_limits[pol] = dx.pooled_db_limits(
                {d: card["arrays"][pol] for card, d in zip(cards, dates)},
                {d: valid_pol[(d, pol)] for d in dates},
            )
        print(f"{name:18s} crop {crop_fraction:.3f} valid  res {display_res:.1f} m  "
              f"grid {disp_w}x{disp_h}  {crop[2] - crop[0]:.0f}x{crop[3] - crop[1]:.0f} m")
        layer_sizes = []

        # ---- offsets on land only, estimated against the reference date ----------------
        if "VH" in pols:
            land = change.land_mask(db[(reference, "VH")], hv_land_cut_db=-15.0)
            land_basis = "VH > -15 dB"
            if int(land.sum()) < 50:
                land = np.isfinite(db[(reference, "VH")])
                land_basis = "all finite pixels (too little land above -15 dB)"
                print(f"{name:18s} little land in the window: offset estimated on all finite pixels")
        else:
            land = np.isfinite(db[(reference, pols[0])])
            land_basis = "all finite pixels (no VH in this place)"
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
        by_day = {c["meta"]["acquisition_date"]: c for c in cards}
        pol_token = "".join(sorted(pols))
        this_series = f"S1-RTC-21-DESC-{pol_token}"
        budget = WHOLE_LAKE_BUDGET if name == "dead_sea_full" else LAYER_BUDGET
        base = {
            "series": this_series,
            "product": "OPERA RTC-S1", "crid": "OPERA", "maturity": "OPERATIONAL",
            "track": 21, "frame": "N/A", "direction": "DESCENDING",
            "native_crs": src_crs,
            "display_crs": wx.CRS_WEB,
            "coverage": "full",
        }
        if resolution_fallback:
            base["resolution_fallback"] = resolution_fallback
        analysis_steps = ["10*log10(gamma-0)", f"{MULTILOOK}x{MULTILOOK} multilook in power (90 m)",
                          f"{SPECKLE[0]} {SPECKLE[1]}x{SPECKLE[1]}", "reprojected to EPSG:3857"]
        display_chain = [
            "native 30 m linear gamma-0 power (OPERA RTC-S1, no extra multilook, no speckle filter)",
            "invalid -> NaN (product mask 0/255 or non-finite)",
            f"reprojected once to EPSG:3857, bilinear on linear power, at {display_res:.1f} m",
            "dB stretch clipped at the pooled 2nd/98th percentile of all dates",
            "6 px inward edge feather (display only)",
            "WebP q82 with alpha",
        ]

        def save(rgba, filename, px_size, chain, **fields):
            image = Image.fromarray(np.ascontiguousarray(rgba), mode="RGBA")
            size, quality = dx.save_layer(image, outdir / "layers" / filename, budget=budget)
            layer_sizes.append(size)
            layers.append({
                "file": f"layers/{filename}", "format": "webp",
                "preview": f"layers/{Path(filename).stem}_preview.webp",
                "native_px_m": native_px, "px_size_m_3857": round(float(px_size), 2),
                "bounds": bounds, "crop_bounds_3857": [round(float(v), 1) for v in crop],
                "display_chain": chain, "webp_quality": quality,
                **base, **fields,
            })

        def display_power(day, pol):
            power, weight = dx.warp_nansafe(
                by_day[day]["arrays"][pol], valid_pol[(day, pol)], t30, src_crs, disp_t, disp_w, disp_h
            )
            return power, weight >= 0.5

        for day in dates:
            for pol in pols:
                power, valid = display_power(day, pol)
                vmin, vmax = display_limits[pol]
                db_img = dx.single_pol_db(power, vmin, vmax, valid)
                rgba = np.array(wx.grey_rgba(db_img, vmin, vmax))
                save(dx.feather_alpha(rgba), f"backscatter_{pol}_{day}.webp", abs(disp_t.a), display_chain,
                     id=f"backscatter_{pol}_{day}", kind="backscatter", label=f"Backscatter {pol} {day}",
                     polarization=pol, date=day,
                     vmin=round(vmin, 2), vmax=round(vmax, 2),
                     colormap="grey: dark = smooth (water), bright = rough",
                     description=f"Gamma-0 backscatter {pol} on {day}.",
                     offset_applied_db=0.0, display_multilook=1,
                     processing=display_chain)

        for day in dates[1:]:
            for pol in pols:
                dst = to_web90(deltas[(day, pol)])[0]
                limit = change_limits[pol]
                rgba = np.array(wx.change_rgba(dst, limit))
                save(dx.feather_alpha(rgba), f"change_{pol}_{day}.webp", abs(g90_t.a),
                     display_chain[:2] + ["change computed on the 90 m analysis chain"] +
                     ["reprojected to EPSG:3857 nearest neighbour"],
                     id=f"change_{pol}_{day}", kind="change", label=f"Change {pol} {day} minus {reference}",
                     polarization=pol, date=day, reference=reference,
                     vmin=-limit, vmax=limit,
                     colormap="diverging: blue = weaker echo, orange = stronger echo",
                     description=f"{pol} change on {day} relative to {reference}, scene offset removed.",
                     offset_applied_db=round(offset_of.get((day, pol), 0.0), 3),
                     display_multilook=MULTILOOK,
                     processing=analysis_steps + ["scene offset removed (land median)"])

        # ---- false-colour RGB (display chain) --------------------------------------------------
        # Dual-pol places use VV (co-pol) as red, VH (cross-pol) as green, blue = ratio.
        if "VV" in pols and "VH" in pols:
            for day in dates:
                vv, vv_valid = display_power(day, "VV")
                vh, vh_valid = display_power(day, "VH")
                valid = vv_valid & vh_valid
                vv_lo, vv_hi = display_limits["VV"]
                vh_lo, vh_hi = display_limits["VH"]
                vv_s = dx.stretched_linear(vv, vv_lo, vv_hi, valid)
                vh_s = dx.stretched_linear(vh, vh_lo, vh_hi, valid)
                # Use the NISAR RGB decomposition but with VV/VH instead of HH/HV
                rgb = wx.rgb_decomposition(vv_s, vh_s, ~valid)
                rgba = dx.rgba_from_rgb(rgb, valid)
                save(dx.feather_alpha(rgba), f"rgb_VVVH_{day}.webp", abs(disp_t.a), display_chain,
                     id=f"rgb_VVVH_{day}", kind="rgb", label=f"False colour VV/VH {day}",
                     polarization="VV+VH", date=day,
                     vmin=round(min(vv_lo, vh_lo), 2), vmax=round(max(vv_hi, vh_hi), 2),
                     colormap="red = VV co-pol, green = VH cross-pol, blue = ratio; pooled dB limits",
                     description=f"S1 false-colour decomposition (VV/VH) on {day}. Green: volume scattering. "
                                 f"Yellow and orange: rough or built surfaces.",
                     offset_applied_db=0.0, display_multilook=1,
                     processing=display_chain + ["S1 RTC-S1 RGB decomposition "
                                                 "(adapted from NISAR GCOV RGB / ASF nisar-py gcov_rgb)"])
        else:
            pol = pols[0]
            for day in dates:
                power, valid = display_power(day, pol)
                vmin, vmax = display_limits[pol]
                db_img = dx.single_pol_db(power, vmin, vmax, valid)
                rgb = dx.single_pol_ramp(db_img, vmin, vmax)
                rgba = dx.rgba_from_rgb(rgb, valid)
                save(dx.feather_alpha(rgba), f"rgb_{pol}_{day}.webp", abs(disp_t.a), display_chain,
                     id=f"rgb_{pol}_{day}", kind="rgb", label=f"False colour {pol} {day}",
                     polarization=pol, date=day,
                     vmin=round(vmin, 2), vmax=round(vmax, 2),
                     colormap="single-polarization ramp: blue (low) to green to orange to yellow (high); pooled dB limits",
                     description=f"Single-polarization false colour ({pol}) on {day}. Our approximation of the "
                                 f"NASA single-pol ramp; exact breakpoints are not published.",
                     offset_applied_db=0.0, display_multilook=1,
                     processing=display_chain + ["fixed blue-green-orange-yellow ramp "
                                                 "(approximation of NASA single-pol)"])

        # ---- water where VH exists -----------------------------------------------------
        water_rows = []
        if "VH" in pols:
            for card in cards:
                day = card["meta"]["acquisition_date"]
                hv_db = change.speckle_filter(change.power_to_db(card["arrays"]["VH"]), *SPECKLE) - offset_of.get((day, "VH"), 0.0)
                threshold = water.two_step_threshold(hv_db)
                if not np.isfinite(threshold):
                    continue
                centre = water.clean_mask(np.isfinite(hv_db) & (hv_db < threshold))
                low = water.clean_mask(np.isfinite(hv_db) & (hv_db < threshold - BAND_DB))
                high = water.clean_mask(np.isfinite(hv_db) & (hv_db < threshold + BAND_DB))
                flip = low ^ high
                dst_w = to_web30(centre, mask=True)[0]
                dst_b = to_web30(flip, mask=True)[0]
                water_km2 = water.water_area_km2(centre, 30.0, clean=False)
                low_area = water.water_area_km2(low, 30.0, clean=False)
                high_area = water.water_area_km2(high, 30.0, clean=False)
                rgba_w = dx.feather_alpha(dx.rgba_from_mask(dst_w, wx.WATER_RGB, wx.WATER_ALPHA))
                save(rgba_w, f"water_VH_{day}.webp", abs(g30_t.a),
                     ["native 30 m VH power", "10*log10", f"median {SPECKLE[1]}x{SPECKLE[1]}",
                      "offset removed", "method B threshold", "blobs < 10 px removed",
                      "reprojected to EPSG:3857 nearest neighbour", "6 px inward edge feather (display only)"],
                     id=f"water_VH_{day}", kind="water", label=f"Open water VH {day}", polarization="VH",
                     date=day,
                     colormap="cyan = open water (method B)", threshold_db=round(float(threshold), 2),
                     area_km2=round(water_km2, 2), band_low_km2=round(low_area, 2), band_high_km2=round(high_area, 2),
                     description=f"Open water on {day}: VH below {threshold:.2f} dB after land removal.",
                     offset_applied_db=offset_of.get((day, "VH"), 0.0), display_multilook=1,
                     processing=["10*log10", f"median {SPECKLE[1]}x{SPECKLE[1]}", "offset removed",
                                 "method B threshold", "blobs < 10 px removed"])
                rgba_b = dx.feather_alpha(dx.rgba_from_mask(dst_b, wx.BAND_RGB, wx.BAND_ALPHA))
                save(rgba_b, f"water_band_{day}.webp", abs(g30_t.a),
                     ["as water", f"band = threshold +/-{BAND_DB} dB",
                      "reprojected to EPSG:3857 nearest neighbour", "6 px inward edge feather (display only)"],
                     id=f"water_band_{day}", kind="band", label=f"Detection-limit band {day}",
                     polarization="VH", date=day,
                     colormap="amber = pixels that flip within +/-1.5 dB", band_db=BAND_DB,
                     threshold_db=round(float(threshold), 2),
                     description=f"Pixels that change water status within +/-{BAND_DB} dB of the threshold.",
                     offset_applied_db=offset_of.get((day, "VH"), 0.0), display_multilook=1,
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
        series_entry = {
            "id": this_series,
            "label": f"OPERA RTC-S1 - track 21 descending",
            "maturity": "OPERATIONAL", "crid": "OPERA",
            "track": 21, "direction": "DESCENDING",
            "polarizations": pols, "dates": dates,
            "analysis": len(dates) >= 5,
            "source": "ASF DAAC OPERA RTC-S1; path 21 descending",
        }
        manifest = {
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "series": [series_entry], "primary_series": this_series,
            "place": {"name": name, "title": area.title, "wkt": area.wkt},
            "study_area": {"name": name, "title": area.title, "wkt": area.wkt, "story": area.story},
            "product": "OPERA RTC-S1", "crid": "OPERA", "maturity": "OPERATIONAL",
            "track": 21, "frame": None, "direction": "DESCENDING",
            "native_crs": src_crs,
            "display_crs": wx.CRS_WEB,
            "reference_date": reference, "dates": dates, "polarizations": pols,
            "primary_water": {"method": PRIMARY, "polarization": "VH"},
            "scales": {"backscatter_db": {p: list(v) for p, v in back_limits.items()},
                       "change_db_symmetric": change_limits},
            "layers": layers, "bounds": bounds,
            "notes": [f"{len(dates)} OPERA RTC-S1 dates on track 21 descending."],
        }
        wx.write_json(outdir / "manifest.json", manifest)
        wx.write_js(outdir / "manifest.js", "place_manifest", manifest)

        stats = {
            "generated_utc": manifest["generated_utc"], "primary_method": PRIMARY, "primary_polarization": "VH",
            "band_db": BAND_DB, "primary_verdict": verdict, "primary_caption": "",
            "series": this_series,
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