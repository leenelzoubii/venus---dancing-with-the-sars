"""Step 5 - export the static web assets the app loads (no backend, no API keys, no live processing).

Reads the cached AOI windows and the Hour 1 statistics, and writes into ``web/data/``:

* PNG layers, EPSG:3857 (Web Mercator), RGBA, one set per date:
    backscatter_<HH|HV>_<date>.png   grey dB, pooled 2nd-98th percentile limits (same for every date)
    change_<HH|HV>_<date>.png        dB change versus the first date, offset removed, symmetric limits
    water_HV_<date>.png              primary water method (B), translucent cyan
    water_band_<date>.png            pixels that flip inside the +/-1.5 dB band (detection limit)
* data files, each as .json (humans) AND .js (file:// works): manifest, water_stats, offsets, patches,
  license_and_attribution.

    python scripts/05_export_web_assets.py --aoi dead_sea_east
    python scripts/05_export_web_assets.py --aoi dead_sea_east --patch-log docs/patch_log.csv

Then validate: python scripts/06_validate_web_assets.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from affine import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change, stack, water, webexport as wx  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

INTERIM = REPO_ROOT / "data" / "interim"
WEB_DATA = REPO_ROOT / "web" / "data"
DOCS = REPO_ROOT / "docs"
MULTILOOK = 3            # display and change layers: 60 m
SPECKLE = ("median", 5)
PRIMARY_METHOD = "B"     # Leen's decision, Hour 1
BAND_DB = 1.5
CHANGE_LIMIT_CAP_DB = 6.0
HUMAN_COLUMNS = ["behaviour", "on_the_ground", "hypothesis", "evidence", "confidence", "use_in_pitch"]


def db_layer(scene, pol: str, factor: int) -> np.ndarray:
    power = scene.power(pol)
    if factor > 1:
        power = change.multilook_power(power, factor)
    return change.speckle_filter(change.power_to_db(power), *SPECKLE)


def load_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing {path.relative_to(REPO_ROOT)}. Run the Hour 1 scripts first.")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    ap.add_argument("--patch-log", type=Path, default=None,
                    help="CSV with Leyan's human columns to merge into patches (optional).")
    ap.add_argument("--outdir", type=Path, default=WEB_DATA)
    ap.add_argument("--patches-tag", default="", help="Use patches<TAG>.geojson, e.g. _sensitive (labelled in the output).")
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    scenes = stack.load_scenes(area.name)
    grid = stack.verify_grid(scenes)
    if grid["problems"]:
        raise SystemExit("REFUSING TO EXPORT: " + "; ".join(grid["problems"]))

    water_stats = load_json(INTERIM / "water_stats.json")
    offsets_doc = load_json(INTERIM / "offsets.json")
    offsets = {(r["date"], r["pol"]): float(r["offset_dB"] or 0.0) for r in offsets_doc["offsets"]}
    thresholds = {d["date"]: d["methods"][PRIMARY_METHOD] for d in water_stats["dates"]}

    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    png_dir = outdir / "layers"
    png_dir.mkdir(exist_ok=True)
    for stale in png_dir.glob("*.png"):
        stale.unlink()

    meta = scenes[0].meta
    x = np.asarray(meta["x"], dtype="float64")
    y = np.asarray(meta["y"], dtype="float64")
    t20 = wx.grid_transform(x, y, 20.0)
    t60 = Affine(t20.a * MULTILOOK, 0.0, t20.c, 0.0, t20.e * MULTILOOK, t20.f)
    reference = scenes[0].date
    dates = [s.date for s in scenes]
    print(f"AOI {area.name}: {len(scenes)} dates, reference {reference}, display 60 m, analysis 20 m")

    # ---- 60 m dB stacks ------------------------------------------------------------------------
    db60 = {(s.date, p): db_layer(s, p, MULTILOOK) for s in scenes for p in ("HH", "HV")}

    # ---- fixed scales ---------------------------------------------------------------------------
    backscatter_limits = {}
    for pol in ("HH", "HV"):
        pooled = np.concatenate([db60[(d, pol)][np.isfinite(db60[(d, pol)])].ravel() for d in dates])
        backscatter_limits[pol] = tuple(float(v) for v in np.percentile(pooled, [2, 98]))

    change_limits = {}
    deltas = {}
    for pol in ("HH", "HV"):
        for d in dates[1:]:
            deltas[(d, pol)] = (db60[(d, pol)] - offsets.get((d, pol), 0.0)) - db60[(reference, pol)]
        pooled = np.concatenate([np.abs(deltas[(d, pol)][np.isfinite(deltas[(d, pol)])]).ravel() for d in dates[1:]])
        p99 = float(np.percentile(pooled, 99))
        change_limits[pol] = round(min(CHANGE_LIMIT_CAP_DB, p99), 2)
    print("Scales: backscatter " + ", ".join(
        f"{p} {v[0]:.2f}..{v[1]:.2f} dB" for p, v in backscatter_limits.items()))
    print("Scales: change " + ", ".join(f"{p} +/-{v:.2f} dB" for p, v in change_limits.items()))

    layers: list[dict] = []
    sizes: dict[str, int] = {}

    def add_layer(image, filename, **fields):
        size = wx.save_png(image, png_dir / filename)
        sizes[filename] = size
        layers.append({"file": f"layers/{filename}", "crid": meta.get("crid"), **fields})

    product_steps = [
        "gamma-0 power -> 10*log10 (product's own formula)",
        f"{MULTILOOK}x{MULTILOOK} multilook in power (60 m)",
        f"{SPECKLE[0]} speckle filter {SPECKLE[1]}x{SPECKLE[1]}",
        "reprojected EPSG:32636 -> EPSG:3857 (bilinear for dB, nearest for masks)",
    ]
    base = {
        "product": "NISAR L2 GCOV",
        "crid": meta.get("crid"),
        "maturity": meta.get("maturity"),
        "track": meta.get("track"),
        "frame": meta.get("frame"),
        "direction": meta.get("direction"),
        "native_crs": wx.CRS_NATIVE,
        "display_crs": wx.CRS_WEB,
    }

    # ---- backscatter ----------------------------------------------------------------------------
    bounds_60 = None
    for d in dates:
        for pol in ("HH", "HV"):
            dst, dst_t = wx.reproject_to_web(db60[(d, pol)], t60)
            bounds_60 = bounds_60 or wx.web_bounds_lonlat(dst_t, *dst.shape)
            vmin, vmax = backscatter_limits[pol]
            name = f"backscatter_{pol}_{d}.png"
            add_layer(
                wx.grey_rgba(dst, vmin, vmax), name, id=f"backscatter_{pol}_{d}", kind="backscatter",
                label=f"Backscatter {pol} {d}", polarization=pol, date=d,
                bounds=wx.web_bounds_lonlat(dst_t, *dst.shape), vmin=vmin, vmax=vmax,
                colormap="grey: black = low dB, white = high dB; NaN transparent",
                description=f"Gamma-0 backscatter, {pol}, on {d}. Dark = smooth (water), bright = rough.",
                offset_applied_db=0.0, display_multilook=MULTILOOK, processing=product_steps,
                **base,
            )

    # ---- change ----------------------------------------------------------------------------------
    for d in dates[1:]:
        for pol in ("HH", "HV"):
            dst, dst_t = wx.reproject_to_web(deltas[(d, pol)], t60)
            limit = change_limits[pol]
            name = f"change_{pol}_{d}.png"
            add_layer(
                wx.change_rgba(dst, limit), name, id=f"change_{pol}_{d}", kind="change",
                label=f"Change {pol} {d} minus {reference}", polarization=pol, date=d, reference=reference,
                bounds=wx.web_bounds_lonlat(dst_t, *dst.shape), vmin=-limit, vmax=limit,
                colormap="diverging #3B82F6 (blue, less echo later) - #D9DEE8 - #F59E0B (orange, more echo later); "
                         "|change| < 0.25 dB transparent; NaN transparent",
                description=f"{pol} change on {d} relative to {reference}, scene offset removed. "
                            f"Blue = less echo later, orange = more.",
                offset_applied_db=round(offsets.get((d, pol), 0.0), 3), display_multilook=MULTILOOK,
                processing=product_steps + ["scene offset removed (land median, offsets.json)"],
                **base,
            )

    # ---- water and detection-limit band, analysis 20 m --------------------------------------------
    water_dates = []
    for d in dates:
        scene = next(s for s in scenes if s.date == d)
        db20 = db_layer(scene, "HV", 1) - offsets.get((d, "HV"), 0.0)
        thr = thresholds[d]["threshold_db"]
        low = water.clean_mask(np.isfinite(db20) & (db20 < thr - BAND_DB))
        centre = water.clean_mask(np.isfinite(db20) & (db20 < thr))
        high = water.clean_mask(np.isfinite(db20) & (db20 < thr + BAND_DB))
        flip = low ^ high

        dst_w, dst_t20 = wx.reproject_to_web(centre, t20, mask=True)
        dst_b, _ = wx.reproject_to_web(flip, t20, mask=True)
        bounds_20 = wx.web_bounds_lonlat(dst_t20, *dst_w.shape)
        stats = thresholds[d]
        add_layer(
            wx.mask_palette(dst_w, wx.WATER_RGB, wx.WATER_ALPHA), f"water_HV_{d}.png",
            id=f"water_HV_{d}", kind="water", label=f"Open water HV {d}", polarization="HV", date=d,
            bounds=bounds_20, colormap="cyan translucent = open water (method B)",
            description=f"Open water on {d}, primary method B: HV below {thr:.2f} dB after land removal. "
                        f"Area {stats['area_km2']:.1f} km2 (band {stats['low_km2']:.1f} to {stats['high_km2']:.1f}).",
            threshold_db=round(thr, 2), area_km2=stats["area_km2"],
            band_low_km2=stats["low_km2"], band_high_km2=stats["high_km2"],
            offset_applied_db=round(offsets.get((d, "HV"), 0.0), 3), display_multilook=1,
            processing=["10*log10 gamma-0", f"median {SPECKLE[1]}x{SPECKLE[1]}", "scene offset removed",
                        "method B: HV > -15 dB dropped, Otsu threshold", "blobs < 10 px removed, holes < 10 px filled",
                        "reprojected to EPSG:3857 nearest"],
            **base,
        )
        add_layer(
            wx.mask_palette(dst_b, wx.BAND_RGB, wx.BAND_ALPHA), f"water_band_{d}.png",
            id=f"water_band_{d}", kind="band", label=f"Detection-limit band {d}", polarization="HV", date=d,
            bounds=bounds_20, colormap="amber = pixels that flip water/land within +/-1.5 dB of the threshold",
            description=f"Pixels on {d} whose water status changes if the threshold moves by 1.5 dB. "
                        f"This is the absolute-area uncertainty made visible.",
            threshold_db=round(thr, 2), band_db=BAND_DB, offset_applied_db=round(offsets.get((d, "HV"), 0.0), 3),
            display_multilook=1,
            processing=["as water_HV", f"band: threshold +/-{BAND_DB} dB; flipped pixels = low XOR high"],
            **base,
        )
        water_dates.append(d)

    # ---- the data files -----------------------------------------------------------------------
    sweep_summary = {}
    sweep_path = INTERIM / "threshold_sweep.csv"
    if sweep_path.exists():
        with open(sweep_path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                sweep_summary.setdefault(row["date"], []).append((float(row["threshold_db"]), float(row["area_km2"])))
    sweep_out = {
        d: {
            "threshold_range_db": [min(t for t, _ in v), max(t for t, _ in v)],
            "area_at_min_threshold_km2": round(v[0][1], 2),
            "area_at_max_threshold_km2": round(v[-1][1], 2),
            "monotonic_nondecreasing_in_threshold": bool(all(b[1] >= a[1] for a, b in zip(v, v[1:]))),
        }
        for d, v in sweep_summary.items()
    }
    water_out = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "primary_method": PRIMARY_METHOD,
        "primary_polarization": "HV",
        "primary_verdict": water_stats["primary_verdict"],
        "primary_caption": water_stats["primary_caption"],
        "band_definition": water_stats["band_definition"],
        "change_detection_definition": water_stats["change_detection_definition"],
        "methods": water_stats["methods"],
        "summary": water_stats["summary"],
        "change_detection": water_stats["change_detection"],
        "dates": water_stats["dates"],
        "threshold_sweep_summary": sweep_out,
        "crid": meta.get("crid"),
    }

    patches_out = export_patches(DOCS, INTERIM, args.patch_log, args.patches_tag, float(area.patches.get("threshold_db", 3.0)))

    manifest = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "study_area": {
            "name": area.name,
            "title": area.title,
            "wkt": area.wkt,
            "story": area.story,
        },
        "product": "NISAR L2 GCOV",
        "crid": meta.get("crid"),
        "maturity": meta.get("maturity"),
        "track": meta.get("track"),
        "frame": meta.get("frame"),
        "direction": meta.get("direction"),
        "native_crs": wx.CRS_NATIVE,
        "display_crs": wx.CRS_WEB,
        "reference_date": reference,
        "dates": dates,
        "polarizations": ["HH", "HV"],
        "primary_water": {"method": PRIMARY_METHOD, "polarization": "HV"},
        "scales": {
            "backscatter_db": {p: list(v) for p, v in backscatter_limits.items()},
            "change_db_symmetric": change_limits,
        },
        "layers": layers,
        "bounds": bounds_60,
        "notes": [
            "Every layer is PROVISIONAL (CRID P05023). No VALIDATED product is mixed in.",
            "The NISAR instrument gap 2026-07-27T22:03Z to 2026-08-10T00:55Z falls between 07-18 and 08-11.",
            "Change layers have the scene offset removed; the value is in each layer's offset_applied_db.",
            "Display resolution is 60 m for backscatter and change; water and band layers are 20 m.",
        ],
    }
    wx.assert_provisional(layers + [{"id": "manifest", "crid": manifest["crid"]}])

    license_doc = {
        "data_credit": "NISAR data courtesy of NASA/JPL-Caltech and ISRO, distributed by the Alaska Satellite "
                       "Facility (ASF DAAC) and NASA Earthdata.",
        "product": "NISAR L2 GCOV, geocoded polarimetric covariance (gamma-0 backscatter)",
        "product_versions": {"crid": meta.get("crid"), "maturity": "PROVISIONAL"},
        "all_data_provisional": True,
        "statement": "All data shown are PROVISIONAL. Validated products are not mixed into this series. "
                     "Reprocessing may change the numbers.",
        "non_endorsement": "NASA does not endorse any non-U.S. Government entity or this project.",
        "app_licence": "See LICENSE in the repository.",
    }

    write_pair(outdir, "manifest", "manifest", manifest)
    write_pair(outdir, "water_stats", "water_stats", water_out)
    write_pair(outdir, "offsets", "offsets", offsets_doc)
    write_pair(outdir, "patches", "patches", patches_out)
    write_pair(outdir, "license_and_attribution", "license", license_doc)

    total = sum(f.stat().st_size for f in outdir.rglob("*") if f.is_file())
    largest = max(sizes.items(), key=lambda kv: kv[1])
    print(f"\nLayers written: {len(sizes)} PNG ({sum(sizes.values()) / 1e6:.2f} MB), largest {largest[0]} "
          f"{largest[1] / 1e3:.0f} KB")
    print(f"Total web/data: {total / 1e6:.2f} MB (budget 30 MB)")
    print(f"Bounds (display, WGS84 [south, west], [north, east]): {bounds_60}")
    print(f"Water/band bounds (20 m grid): {bounds_20}")
    print(f"Wrote {outdir.relative_to(REPO_ROOT)}")
    return 0


def write_pair(outdir: Path, stem: str, key: str, payload) -> None:
    wx.write_json(outdir / f"{stem}.json", payload)
    wx.write_js(outdir / f"{stem}.js", key, payload)


ALLOWED_VALUES = {
    "confidence": {"", "low", "medium", "high"},
    "use_in_pitch": {"", "yes", "no"},
}
BEHAVIOUR_HINTS = {"", "gradual", "step", "flicker"}


def validate_patch_log(path: Path) -> tuple[list[str], list[str]]:
    """Check the analyst's CSV before trusting any cell of it. Returns (errors, warnings).

    Rules are enforced rather than guessed: a wrong confidence word is reported, never coerced.
    ``behaviour`` is free text on purpose (Leyan may write a phrase), so an unexpected word is a
    warning, not an error.
    """
    errors: list[str] = []
    warnings: list[str] = []
    try:
        raw = path.read_bytes()
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"{path.name} is not valid UTF-8: {exc}"], warnings

    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in ["patch_id", *HUMAN_COLUMNS] if c not in (reader.fieldnames or [])]
        if missing:
            return [f"{path.name} is missing columns: {', '.join(missing)}"], warnings
        seen = set()
        for number, row in enumerate(reader, start=2):
            pid = (row.get("patch_id") or "").strip()
            if not pid:
                errors.append(f"row {number}: empty patch_id")
                continue
            if pid in seen:
                errors.append(f"row {number}: duplicate patch_id {pid}")
            seen.add(pid)
            for column, allowed in ALLOWED_VALUES.items():
                value = (row.get(column) or "").strip().lower()
                if value not in allowed:
                    errors.append(f"row {number} ({pid}): {column}={value!r} not one of {sorted(allowed)}")
            behaviour = (row.get("behaviour") or "").strip().lower()
            if behaviour and behaviour not in BEHAVIOUR_HINTS:
                warnings.append(f"row {number} ({pid}): behaviour={behaviour!r} is unusual (expected gradual/step/flicker)")
            if (row.get("hypothesis") or "").strip() and not (row.get("confidence") or "").strip():
                warnings.append(f"row {number} ({pid}): hypothesis given without a confidence word")
    return errors, warnings


def export_patches(docs: Path, interim: Path, patch_log: Path | None, tag: str = "", threshold_db: float = 3.0) -> dict:
    geo_path = interim / f"patches{tag}.geojson"
    if not geo_path.exists():
        raise SystemExit("Run scripts/04b_find_patches.py first.")
    geojson = json.loads(geo_path.read_text(encoding="utf-8"))
    rounded = wx.round_geojson(geojson, decimals=6)

    human: dict[str, dict[str, str]] = {}
    log_status = {"merged": False, "errors": [], "warnings": [], "filled_rows": 0}
    if patch_log is not None:
        if not patch_log.exists():
            raise SystemExit(f"--patch-log not found: {patch_log}")
        errors, warnings = validate_patch_log(patch_log)
        log_status["errors"] = errors
        log_status["warnings"] = warnings
        if errors:
            print(f"\nPATCH LOG ERRORS in {patch_log.name} - refusing to merge that file:")
            for message in errors:
                print(f"  ERROR {message}")
            raise SystemExit("Fix the patch log and re-run. Nothing was guessed.")
        for message in warnings:
            print(f"  WARNING {message}")
        with open(patch_log, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                values = {c: (row.get(c) or "").strip() for c in HUMAN_COLUMNS}
                human[row["patch_id"].strip()] = values
                if any(values.values()):
                    log_status["filled_rows"] += 1
        log_status["merged"] = True
        print(f"Patch log merged: {log_status['filled_rows']} row(s) carry human input "
              f"out of {len(human)} listed.")

    series_path = interim / f"patch_timeseries{tag}.csv"
    series: dict[str, list] = {}
    if series_path.exists():
        with open(series_path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                series.setdefault(row["patch_id"], []).append({k: row[k] for k in row if k != "patch_id"})

    for feature in rounded["features"]:
        props = feature["properties"]
        pid = props["id"]
        props["timeseries"] = series.get(pid, [])
        for column in HUMAN_COLUMNS:
            props[column] = human.get(pid, {}).get(column, "")
        # "yes" is the only value that features a patch; anything else stays out of the spotlight.
        props["use_in_pitch"] = "yes" if props["use_in_pitch"].strip().lower() == "yes" else ""
    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "patch_log_merged": log_status["merged"],
        "patch_log_status": log_status,
        "featured": [f["properties"]["id"] for f in rounded["features"] if f["properties"]["use_in_pitch"] == "yes"],
        "threshold_db": threshold_db,
        "detection_rule": "configured rule (config/study_area.yaml patches:)" if not tag else "SENSITIVITY RUN " + tag + " - not the configured rule",
        "count": len(rounded["features"]),
        "geojson": rounded,
    }


if __name__ == "__main__":
    raise SystemExit(main())
