"""Step 17 - build a multi-series place (the whole Dead Sea) from cached subsets.

One place, several calibration SERIES. A series is (maturity, CRID, track, direction, polarizations)
and is never mixed: each series has its own dates, its own pooled display limits and its own
analysis. The primary PROVISIONAL series (>= 5 dates) is analysed with the same method as every other
place; BETA and short VALIDATED series are browse-only, exactly as their maturity allows.

Two adjacent frames of one acquisition (151/072 and 151/073) are mosaicked in native UTM coordinates
first, so the whole lake fits and no corner is clipped.

    python scripts/17_build_series_site.py --aoi dead_sea_full
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from affine import Affine
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change, display as dx, water, webexport as wx  # noqa: E402
from venus.config import REPO_ROOT, load_study_area  # noqa: E402
from venus.mosaic import mosaic_items  # noqa: E402

SUBSETS = REPO_ROOT / "data" / "raw" / "subsets"
WEB_DATA = REPO_ROOT / "web" / "data"
MULTILOOK = 3
SPECKLE = ("median", 5)
BAND_DB = 1.5
PRIMARY = "B"
MAX_SIDE_PX = 3600
LAYER_BUDGET = 900_000
MATURITY_LABEL = {"BETA": "BETA (pre-calibration)", "PROVISIONAL": "PROVISIONAL",
                  "VALIDATED": "VALIDATED"}


def load_items(place: str) -> list[dict]:
    folder = SUBSETS / place
    items = []
    for sidecar in sorted(folder.glob("*.json")):
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        base = sidecar.with_suffix("")
        arrays = {}
        for pol in ("HH", "HV"):
            path = Path(f"{base}_{pol}.npy")
            if path.exists():
                arr = np.load(path)
                if arr.size:
                    arrays[pol] = arr
        if not arrays:
            continue
        mask_path = Path(f"{base}_mask.npy")
        items.append({
            "meta": meta, "stem": sidecar.stem, "arrays": arrays,
            "mask": np.load(mask_path) if mask_path.exists() else None,
            "x": np.array(meta["x"], dtype="float64"), "y": np.array(meta["y"], dtype="float64"),
        })
    return items


def group_dates(items: list[dict]) -> list[dict]:
    by_key = defaultdict(list)
    for item in items:
        meta = item["meta"]
        pol_token = "".join(sorted(set(str(meta.get("polarizations", "")).split("+"))))
        key = (meta["acquisition_date"], meta.get("maturity"), meta.get("crid"),
               int(meta.get("track", 0)), str(meta.get("direction", "")), pol_token)
        by_key[key].append(item)
    cards = []
    dropped = []
    for key, group in sorted(by_key.items()):
        card = mosaic_items(group)
        card["series_key"] = key[1:]
        valid = None
        for pol, array in card["arrays"].items():
            v = dx.valid_native(array, card["mask"])
            valid = v if valid is None else (valid & v)
        fraction = float(valid.mean()) if valid is not None else 0.0
        if fraction < 0.90:
            # A date whose second frame is not cached yet covers only part of the lake. Never draw it:
            # a half-swath image would look like a shoreline that is not there.
            dropped.append(f"{key[0]}({fraction:.2f})")
            continue
        card["valid_fraction"] = fraction
        cards.append(card)
    if dropped:
        print(f"  dropped {len(dropped)} incomplete date(s): {', '.join(dropped[:8])}")
    return cards


def series_id(key) -> str:
    maturity, crid, track, direction, pols = key
    return f"{track}-{str(direction)[:4].upper()}-{crid}-{pols}"


def make_display_grid(card: dict, crop_margin: float, centre_lat: float):
    x = np.asarray(card["x"], dtype="float64")
    y = np.asarray(card["y"], dtype="float64")
    px = float(card["meta"]["pixel_spacing_m"])
    src_transform = wx.grid_transform(x, y, px)
    valid = None
    for pol in card["arrays"]:
        v = dx.valid_native(card["arrays"][pol], card["mask"])
        valid = v if valid is None else (valid & v)
    return src_transform, valid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", default="dead_sea_full")
    args = ap.parse_args()
    name = args.aoi
    area = load_study_area(name)
    cards = group_dates(load_items(name))
    if not cards:
        raise SystemExit(f"no cached subsets for {name}")

    series: dict[str, list[dict]] = defaultdict(list)
    for card in cards:
        series[series_id(card["series_key"])].append(card)
    for group in series.values():
        group.sort(key=lambda c: c["meta"]["acquisition_date"])

    # The primary series: PROVISIONAL, then the most dates. Analysis is allowed only here, and only
    # with >= 5 dates (the same rule the app shows to the reader).
    def rank(sid):
        group = series[sid]
        maturity = group[0]["series_key"][0]
        return (maturity != "PROVISIONAL", -len(group), sid)

    primary = sorted(series, key=rank)[0]
    primary_group = series[primary]
    primary_maturity = primary_group[0]["series_key"][0]
    primary_analysis = primary_maturity == "PROVISIONAL" and len(primary_group) >= 5

    # One display rectangle per place, from the primary series' pooled validity. The whole-lake place
    # uses no extra buffer: its AOI polygon already includes a margin around the water.
    src_transform, pooled_valid = make_display_grid(primary_group[0], 0.0, 31.5)
    for card in primary_group[1:]:
        for pol in card["arrays"]:
            pooled_valid &= dx.valid_native(card["arrays"][pol], card["mask"])
    import shapely.wkt as _wkt
    centre_lat = float(_wkt.loads(area.wkt).centroid.y)
    crop, display_res, crop_fraction = dx.choose_crop(
        pooled_valid, src_transform, primary_group[0]["meta"].get("crs_wkt") or f"EPSG:{primary_group[0]['meta']['epsg']}",
        area.wkt, centre_lat, float(primary_group[0]["meta"]["pixel_spacing_m"]),
    )
    # Longest side cap: a whole-lake image may not need 2x native everywhere.
    left, bottom, right, top = crop
    longest = max(right - left, top - bottom)
    if longest / display_res > MAX_SIDE_PX:
        display_res = longest / MAX_SIDE_PX
    disp_t, disp_w, disp_h = dx.grid_for_rect(crop, display_res)
    while disp_w * disp_h > 4_500_000:
        display_res *= 1.15
        disp_t, disp_w, disp_h = dx.grid_for_rect(crop, display_res)
    analysis_crop = dx.aoi_rect_3857(area.wkt, 0.0)
    g60_t, g60_w, g60_h = dx.grid_for_rect(analysis_crop, 60.0)
    g20_t, g20_w, g20_h = dx.grid_for_rect(analysis_crop, 20.0)
    bounds = wx.web_bounds_lonlat(disp_t, disp_h, disp_w)
    print(f"{name:16s} series {len(series)}  crop {crop_fraction:.3f}  res {display_res:.1f} m  "
          f"grid {disp_w}x{disp_h}")

    outdir = WEB_DATA / name
    (outdir / "layers").mkdir(parents=True, exist_ok=True)
    for pattern in ("*.png", "*.webp"):
        for stale in (outdir / "layers").glob(pattern):
            stale.unlink()

    layers: list[dict] = []
    series_meta: list[dict] = []
    stats_payload = None
    offsets_payload = None

    for sid in sorted(series, key=rank):
        group = series[sid]
        maturity, crid, track, direction, pol_token = group[0]["series_key"]
        dates = [c["meta"]["acquisition_date"] for c in group]
        pols = sorted(set.intersection(*[set(c["arrays"]) for c in group]))
        src_crs = group[0]["meta"].get("crs_wkt") or f"EPSG:{group[0]['meta']['epsg']}"
        native_px = float(group[0]["meta"]["pixel_spacing_m"])
        analysis = sid == primary and primary_analysis
        base = {
            "series": sid, "product": "NISAR L2 GCOV", "crid": crid, "maturity": maturity,
            "track": track, "frame": group[0]["meta"].get("frame"), "direction": direction,
            "native_crs": f"EPSG:{group[0]['meta']['epsg']}", "display_crs": wx.CRS_WEB,
        }
        display_chain = [
            "native 20 m linear gamma-0 power (GCOV, no extra multilook, no speckle filter)",
            "invalid -> NaN (product mask 0/255 or non-finite)",
            "adjacent frames of the same acquisition mosaicked in native UTM (mean where both valid)",
            f"reprojected once to EPSG:3857, bilinear on linear power, at {display_res:.1f} m",
            "dB stretch clipped at the series' pooled 2nd/98th percentile over all its dates",
            "8 px inward edge feather (display only)",
            "WebP lossy with alpha",
        ]
        sizes = []

        def save(rgba, filename, px_size, **fields):
            image = Image.fromarray(np.ascontiguousarray(rgba), mode="RGBA")
            quality_used = 60
            size = 0
            for quality in (82, 75, 68, 60):
                size = dx.save_webp(image, outdir / "layers" / filename, quality=quality)
                quality_used = quality
                if size <= LAYER_BUDGET:
                    break
            dx.save_preview(image, outdir / "layers" / (Path(filename).stem + "_preview.webp"))
            sizes.append(size)
            layers.append({
                "file": f"layers/{filename}", "format": "webp",
                "preview": f"layers/{Path(filename).stem}_preview.webp",
                "native_px_m": native_px, "px_size_m_3857": round(abs(disp_t.a), 2),
                "bounds": bounds, "crop_bounds_3857": [round(float(v), 1) for v in crop],
                "display_chain": display_chain, "webp_quality": quality_used,
                **base, **fields,
            })

        valid_pol = {}
        for card in group:
            day = card["meta"]["acquisition_date"]
            for pol in pols:
                valid_pol[(day, pol)] = dx.valid_native(card["arrays"][pol], card["mask"])
        limits = {pol: dx.pooled_db_limits(
            {c["meta"]["acquisition_date"]: c["arrays"][pol] for c in group},
            {c["meta"]["acquisition_date"]: valid_pol[(c["meta"]["acquisition_date"], pol)] for c in group})
            for pol in pols}

        def display_power(card, pol):
            power, weight = dx.warp_nansafe(
                card["arrays"][pol], valid_pol[(card["meta"]["acquisition_date"], pol)],
                wx.grid_transform(np.asarray(card["x"], dtype="float64"),
                                  np.asarray(card["y"], dtype="float64"), native_px),
                src_crs, disp_t, disp_w, disp_h,
            )
            return power, weight >= 0.5

        for card in group:
            day = card["meta"]["acquisition_date"]
            for pol in pols:
                power, valid = display_power(card, pol)
                vmin, vmax = limits[pol]
                db = dx.single_pol_db(power, vmin, vmax, valid)
                rgba = np.array(wx.grey_rgba(db, vmin, vmax))
                save(dx.feather_alpha(rgba, 8), f"backscatter_{pol}_{day}.webp", abs(disp_t.a),
                     id=f"{sid}_backscatter_{pol}_{day}", kind="backscatter",
                     label=f"Backscatter {pol} {day}", polarization=pol, date=day,
                     vmin=round(vmin, 2), vmax=round(vmax, 2),
                     colormap="grey: dark = smooth (water), bright = rough",
                     description=f"Gamma-0 backscatter {pol} on {day} ({maturity} series).",
                     offset_applied_db=0.0, display_multilook=1, processing=display_chain)

        if "HH" in pols and "HV" in pols:
            for card in group:
                day = card["meta"]["acquisition_date"]
                hh, hh_ok = display_power(card, "HH")
                hv, hv_ok = display_power(card, "HV")
                valid = hh_ok & hv_ok
                hh_s = dx.stretched_linear(hh, *limits["HH"], valid)
                hv_s = dx.stretched_linear(hv, *limits["HV"], valid)
                rgb = wx.rgb_decomposition(hh_s, hv_s, ~valid)
                rgba = dx.rgba_from_rgb(rgb, valid)
                save(dx.feather_alpha(rgba, 8), f"rgb_HHHV_{day}.webp", abs(disp_t.a),
                     id=f"{sid}_rgb_HHHV_{day}", kind="rgb", label=f"False colour HH/HV {day}",
                     polarization="HH+HV", date=day,
                     vmin=round(min(limits["HH"][0], limits["HV"][0]), 2),
                     vmax=round(max(limits["HH"][1], limits["HV"][1]), 2),
                     colormap="red = HH co-pol, green = HV cross-pol, blue = ratio; pooled dB limits",
                     description=f"NISAR false-colour decomposition on {day} ({maturity} series).",
                     offset_applied_db=0.0, display_multilook=1,
                     processing=display_chain + ["NISAR GCOV RGB decomposition "
                                                 "(as ASF nisar-py gcov_rgb / hyp3-lib rtc2color)"])

        if analysis:
            stats_payload, offsets_payload = build_analysis(
                name, sid, group, pols, src_crs, native_px, outdir, layers, bounds,
                g60_t, g60_w, g60_h, g20_t, g20_w, g20_h, save,
            )

        series_meta.append({
            "id": sid, "label": f"{MATURITY_LABEL.get(maturity, maturity)} - track {track} "
                                f"{str(direction).lower()}",
            "maturity": maturity, "crid": crid, "track": track, "direction": direction,
            "polarizations": pols, "dates": dates, "analysis": bool(analysis),
            "source": "ASF DAAC NISAR L2 GCOV; maturity rules from the NISAR Data User Guide",
        })

    manifest = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "place": {"name": name, "title": area.title, "wkt": area.wkt},
        "study_area": {"name": name, "title": area.title, "wkt": area.wkt, "story": area.story},
        "product": "NISAR L2 GCOV", "crid": primary_group[0]["series_key"][1],
        "maturity": primary_maturity,
        "track": primary_group[0]["series_key"][2], "direction": primary_group[0]["series_key"][3],
        "native_crs": f"EPSG:{primary_group[0]['meta']['epsg']}", "display_crs": wx.CRS_WEB,
        "reference_date": series[primary][0]["meta"]["acquisition_date"],
        "dates": [c["meta"]["acquisition_date"] for c in primary_group],
        "polarizations": sorted(set.intersection(*[set(c["arrays"]) for c in primary_group])),
        "series": series_meta, "primary_series": primary,
        "scales": {"change_db_symmetric": (stats_payload or {}).get("change_limits", {})},
        "layers": layers, "bounds": bounds,
        "notes": [f"{len(series)} calibration series; dates are never mixed across series.",
                  "BETA is browse-only; no statistics are computed from it."],
    }
    wx.assert_provisional([{"id": "manifest", "crid": manifest["crid"]}])
    wx.write_json(outdir / "manifest.json", manifest)
    wx.write_js(outdir / "manifest.js", "place_manifest", manifest)

    if stats_payload is None:
        stats_payload = {"generated_utc": manifest["generated_utc"], "series": primary,
                         "primary_method": PRIMARY, "dates": [], "summary": {}}
        offsets_payload = {"aoi": name, "series": primary, "reference_date": manifest["reference_date"],
                           "offsets": []}
    wx.write_json(outdir / "water_stats.json", stats_payload)
    wx.write_js(outdir / "water_stats.js", "place_water_stats", stats_payload)
    wx.write_json(outdir / "offsets.json", offsets_payload)
    wx.write_js(outdir / "offsets.js", "place_offsets", offsets_payload)

    total_mb = sum(s for s in sizes) / 1e6
    print(f"{name:16s} {len(layers)} layers  {total_mb:.1f} MB  classes: "
          + ", ".join(f"{s['maturity']}={len(s['dates'])}" for s in series_meta))
    return 0


def build_analysis(name, sid, group, pols, src_crs, native_px, outdir, layers, bounds,
                   g60_t, g60_w, g60_h, g20_t, g20_w, g20_h, save):
    """The unchanged analysis method, run for one series only."""
    dates = [c["meta"]["acquisition_date"] for c in group]
    reference = dates[0]
    t20 = wx.grid_transform(np.asarray(group[0]["x"], dtype="float64"),
                            np.asarray(group[0]["y"], dtype="float64"), native_px)
    t60 = Affine(t20.a * MULTILOOK, 0.0, t20.c, 0.0, t20.e * MULTILOOK, t20.f)

    def to_web60(array, **kwargs):
        return wx.reproject_to_grid(array, t60, src_crs, g60_t, g60_h, g60_w, **kwargs)

    def to_web20(array, **kwargs):
        return wx.reproject_to_grid(array, t20, src_crs, g20_t, g20_h, g20_w, **kwargs)

    db = {}
    for card in group:
        for pol in pols:
            power = change.multilook_power(card["arrays"][pol], MULTILOOK)
            db[(card["meta"]["acquisition_date"], pol)] = change.speckle_filter(
                change.power_to_db(power), *SPECKLE)

    if "HV" in pols:
        land = change.land_mask(db[(reference, "HV")], hv_land_cut_db=-15.0)
        if int(land.sum()) < 50:
            land = np.isfinite(db[(reference, "HV")])
    else:
        land = np.isfinite(db[(reference, pols[0])])
    offsets = []
    for day in dates:
        for pol in pols:
            if day == reference:
                offsets.append({"date": day, "pol": pol, "offset_dB": 0.0,
                                "n_pixels": int(land.sum()), "MAD_dB": 0.0})
                continue
            value, n, mad = change.robust_offset_db(db[(day, pol)], db[(reference, pol)], land)
            offsets.append({"date": day, "pol": pol, "offset_dB": round(float(value), 3),
                            "n_pixels": n, "MAD_dB": round(float(mad), 3)})
    offset_of = {(o["date"], o["pol"]): o["offset_dB"] for o in offsets}

    deltas = {}
    change_limits = {}
    for pol in pols:
        for day in dates[1:]:
            deltas[(day, pol)] = (db[(day, pol)] - offset_of.get((day, pol), 0.0)) - db[(reference, pol)]
        pooled = np.concatenate([np.abs(deltas[(d, pol)][np.isfinite(deltas[(d, pol)])]).ravel()
                                 for d in dates[1:]])
        change_limits[pol] = round(min(6.0, float(np.percentile(pooled, 99))), 2) if pooled.size else 1.0
        limit = change_limits[pol]
        for day in dates[1:]:
            dst = to_web60(deltas[(day, pol)])[0]
            rgba = np.array(wx.change_rgba(dst, limit))
            save(dx.feather_alpha(rgba, 8), f"change_{pol}_{day}.webp", abs(g60_t.a),
                 id=f"{sid}_change_{pol}_{day}", kind="change",
                 label=f"Change {pol} {day} minus {reference}", polarization=pol, date=day,
                 reference=reference, vmin=-limit, vmax=limit,
                 colormap="diverging: blue = weaker echo, orange = stronger echo",
                 description=f"{pol} change on {day} relative to {reference}, scene offset removed.",
                 offset_applied_db=round(offset_of.get((day, pol), 0.0), 3), display_multilook=MULTILOOK,
                 processing=["10*log10(gamma-0)", f"{MULTILOOK}x{MULTILOOK} multilook in power (60 m)",
                             f"{SPECKLE[0]} {SPECKLE[1]}x{SPECKLE[1]}", "scene offset removed",
                             "reprojected to EPSG:3857 nearest neighbour"])

    water_rows = []
    if "HV" in pols:
        for card in group:
            day = card["meta"]["acquisition_date"]
            hv_db = change.speckle_filter(change.power_to_db(card["arrays"]["HV"]), *SPECKLE) - offset_of.get((day, "HV"), 0.0)
            threshold = water.two_step_threshold(hv_db)
            if not np.isfinite(threshold):
                continue
            centre = water.clean_mask(np.isfinite(hv_db) & (hv_db < threshold))
            low = water.clean_mask(np.isfinite(hv_db) & (hv_db < threshold - BAND_DB))
            high = water.clean_mask(np.isfinite(hv_db) & (hv_db < threshold + BAND_DB))
            flip = low ^ high
            dst_w = to_web20(centre, mask=True)[0]
            dst_b = to_web20(flip, mask=True)[0]
            water_km2 = water.water_area_km2(centre, 20.0, clean=False)
            low_area = water.water_area_km2(low, 20.0, clean=False)
            high_area = water.water_area_km2(high, 20.0, clean=False)
            save(dx.feather_alpha(dx.rgba_from_mask(dst_w, wx.WATER_RGB, wx.WATER_ALPHA), 8),
                 f"water_HV_{day}.webp", abs(g20_t.a),
                 id=f"{sid}_water_HV_{day}", kind="water", label=f"Open water HV {day}",
                 polarization="HV", date=day, colormap="cyan = open water (method B)",
                 threshold_db=round(float(threshold), 2), area_km2=round(water_km2, 2),
                 band_low_km2=round(low_area, 2), band_high_km2=round(high_area, 2),
                 description=f"Open water on {day}: HV below {threshold:.2f} dB after land removal.",
                 offset_applied_db=offset_of.get((day, "HV"), 0.0), display_multilook=1,
                 processing=["10*log10", f"median {SPECKLE[1]}x{SPECKLE[1]}", "offset removed",
                             "method B threshold", "blobs < 10 px removed",
                             "reprojected to EPSG:3857 nearest neighbour"])
            save(dx.feather_alpha(dx.rgba_from_mask(dst_b, wx.BAND_RGB, wx.BAND_ALPHA), 8),
                 f"water_band_{day}.webp", abs(g20_t.a),
                 id=f"{sid}_water_band_{day}", kind="band", label=f"Detection-limit band {day}",
                 polarization="HV", date=day, colormap="amber = pixels that flip within +/-1.5 dB",
                 band_db=BAND_DB, threshold_db=round(float(threshold), 2),
                 description=f"Pixels that change water status within +/-{BAND_DB} dB of the threshold.",
                 offset_applied_db=offset_of.get((day, "HV"), 0.0), display_multilook=1,
                 processing=["as water", f"band = threshold +/-{BAND_DB} dB"])
            edge = np.zeros(centre.shape, dtype=bool)
            edge[0, :] = edge[-1, :] = True
            edge[:, 0] = edge[:, -1] = True
            if int((centre & edge).sum()) > 0:
                print(f"  G6 note {day}: open-water pixels touch the analysis rectangle edge")
            water_rows.append({"date": day, "methods": {PRIMARY: {
                "threshold_db": round(float(threshold), 2), "area_km2": round(water_km2, 2),
                "low_km2": round(low_area, 2), "high_km2": round(high_area, 2)}}})

    areas = [r["methods"][PRIMARY]["area_km2"] for r in water_rows]
    verdict = ("No date-to-date change is larger than the measurement spread for this place."
               if areas and (max(areas) - min(areas)) < 2.0 * BAND_DB * 10
               else "Differences exist; check the band before calling any of them change.")
    stats = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "series": sid, "primary_method": PRIMARY, "primary_polarization": "HV",
             "band_db": BAND_DB, "primary_verdict": verdict, "dates": water_rows,
             "summary": {}, "change_detection": {},
             "change_limits": change_limits,
             "scales": {"change_db_symmetric": change_limits}}
    offsets_payload = {"aoi": name, "series": sid, "reference_date": reference, "offsets": offsets}
    return stats, offsets_payload


if __name__ == "__main__":
    raise SystemExit(main())
