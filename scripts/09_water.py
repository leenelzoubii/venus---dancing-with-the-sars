"""Step 9 - water area per date, four ways, with the uncertainty stated.

The question this script answers is not "how much water is there" but "is any change in water larger
than our own uncertainty". It computes each method, quotes a +/- band, sweeps the threshold, and only
then compares dates.

    python scripts/09_water.py --aoi dead_sea_east

Outputs (data/interim/): water_stats.json, threshold_sweep.csv, threshold_sweep.png,
water_area_vs_date.png.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change, stack, water  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

INTERIM = REPO_ROOT / "data" / "interim"
POL = "HV"                 # the water channel: HH's water mode overlaps the land tail
SPECKLE = ("median", 5)
BAND_DB = 1.5
MIN_BLOB_PX = 10
MAX_HOLE_PX = 10
GMM_SAMPLE = 120_000


def method_d_threshold(db: np.ndarray) -> float:
    """The previous approach: Otsu on the whole window, land included."""
    return change.otsu_threshold(db)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    scenes = stack.load_scenes(area.name)
    grid = stack.verify_grid(scenes)
    if grid["problems"]:
        raise SystemExit("Grid problems: " + "; ".join(grid["problems"]))

    offsets_path = INTERIM / "offsets.json"
    if not offsets_path.exists():
        raise SystemExit("Run scripts/08_offsets.py first: offsets must be explicit, never implicit.")
    offsets = json.loads(offsets_path.read_text(encoding="utf-8"))
    hv_offsets = {row["date"]: float(row["offset_dB"]) for row in offsets["offsets"] if row["pol"] == POL}

    print(f"AOI {area.name}: {len(scenes)} dates, polarization {POL}, 20 m pixels (400 m2)")
    print(f"Offset correction: explicit, from offsets.json (land median, reference {offsets['reference_date']})")

    # ---- offset-corrected HV dB per date -----------------------------------------------------
    db = {}
    for scene in scenes:
        raw = change.speckle_filter(change.power_to_db(scene.power(POL)), *SPECKLE)
        applied = hv_offsets.get(scene.date, 0.0)
        db[scene.date] = raw - applied
        print(f"  {scene.date}: offset applied {-applied:+.2f} dB")

    # ---- Method A: one pooled threshold for the series ---------------------------------------
    pooled = np.concatenate([db[s.date][np.isfinite(db[s.date])].ravel() for s in scenes])
    threshold_a = water.histogram_valley(pooled)
    print(f"\nMethod A pooled histogram valley: {threshold_a:.2f} dB")

    # ---- Method B and C and D: per date -------------------------------------------------------
    results = {"A": {}, "B": {}, "C": {}, "D": {}}
    rng = np.random.default_rng(42)
    for scene in scenes:
        day = scene.date
        values = db[day]
        threshold_b = water.two_step_threshold(values)
        finite = values[np.isfinite(values)]
        sample = finite if finite.size <= GMM_SAMPLE else rng.choice(finite, GMM_SAMPLE, replace=False)
        threshold_c = water.gmm_threshold(sample)
        threshold_d = method_d_threshold(values)

        for key, threshold in (("A", threshold_a), ("B", threshold_b), ("C", threshold_c), ("D", threshold_d)):
            if not np.isfinite(threshold):
                results[key][day] = {"threshold_db": None, "area_km2": None, "low_km2": None, "high_km2": None}
                continue
            centre, low, high = water.area_band(
                values, threshold, half_width_db=BAND_DB, pixel_size_m=20.0
            )
            results[key][day] = {
                "threshold_db": round(float(threshold), 2),
                "area_km2": round(centre, 2),
                "low_km2": round(low, 2),
                "high_km2": round(high, 2),
            }

    # ---- threshold sweep ---------------------------------------------------------------------
    sweep_rows = []
    for scene in scenes:
        for threshold, value in water.sweep(db[scene.date], -22.0, -15.0, 0.25, 20.0):
            sweep_rows.append({"date": scene.date, "threshold_db": threshold, "area_km2": round(value, 3)})
    sweep = pd.DataFrame(sweep_rows)
    sweep.to_csv(INTERIM / "threshold_sweep.csv", index=False, encoding="utf-8")

    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    for day, group in sweep.groupby("date"):
        ax.plot(group["threshold_db"], group["area_km2"], marker=".", linewidth=0.9, label=day)
    ax.set_xlabel("HV threshold (dB)")
    ax.set_ylabel("water area (km2)")
    ax.set_title("Threshold sweep: how much the answer depends on the cut", fontsize=11)
    ax.legend(fontsize=6.5, ncol=2)
    ax.text(0.01, -0.22,
            f"NISAR L2 GCOV CRID {scenes[0].meta.get('crid')} | track {scenes[0].meta.get('track')} frame "
            f"{scenes[0].meta.get('frame')} | HV | 10*log10, median 5x5, offset removed, "
            f"blobs < {MIN_BLOB_PX} px removed, holes < {MAX_HOLE_PX} px filled",
            transform=ax.transAxes, fontsize=6, color="#444444", va="top")
    fig.savefig(INTERIM / "threshold_sweep.png", dpi=140, bbox_inches="tight")
    plt.close(fig)

    # ---- stability comparison ----------------------------------------------------------------
    dates = [s.date for s in scenes]
    summary = {}
    for key in results:
        series = np.array([results[key][d]["area_km2"] for d in dates], dtype="float64")
        thresholds = np.array([results[key][d]["threshold_db"] for d in dates], dtype="float64")
        lows = np.array([results[key][d]["low_km2"] for d in dates], dtype="float64")
        highs = np.array([results[key][d]["high_km2"] for d in dates], dtype="float64")
        band = float(np.nanmedian((highs - lows) / 2.0))
        sensitivity = float(np.nanmedian(highs - series))  # km2 per +1 dB (band is +/-1.5 dB)
        area_range = float(np.nanmax(series) - np.nanmin(series))
        summary[key] = {
            "area_mean_km2": round(float(np.nanmean(series)), 2),
            "area_std_km2": round(float(np.nanstd(series, ddof=1)), 2),
            "area_range_km2": round(area_range, 2),
            "band_km2": round(band, 2),
            "km2_per_dB": round(sensitivity / BAND_DB, 2),
            "threshold_std_db": round(float(np.nanstd(thresholds, ddof=1)), 2),
            "change_exceeds_band": bool(area_range > band),
        }

    # ---- outputs -----------------------------------------------------------------------------
    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aoi": area.name,
        "product": "NISAR L2 GCOV",
        "crid": scenes[0].meta.get("crid"),
        "maturity": scenes[0].meta.get("maturity"),
        "geometry": f"track {scenes[0].meta.get('track')} frame {scenes[0].meta.get('frame')} "
                    f"{scenes[0].meta.get('direction')}",
        "crs": "EPSG:32636",
        "polarization": POL,
        "pixel_m": 20,
        "pixel_area_m2": 400,
        "processing": [
            "power -> dB: 10*log10(gamma-0)",
            f"speckle: median {SPECKLE[1]}x{SPECKLE[1]}",
            "explicit scene offset removed per date (offsets.json, land median)",
            f"clean-up: water blobs < {MIN_BLOB_PX} px removed, holes < {MAX_HOLE_PX} px filled",
            f"uncertainty band: threshold +/-{BAND_DB} dB",
        ],
        "methods": {
            "A": "fixed HV threshold from the pooled histogram valley (all dates share it)",
            "B": f"two-step: drop HV > {water.DEFAULT_LAND_CUT_DB} dB, then Otsu on the remainder, per date",
            "C": f"two-component Gaussian mixture on a stratified sample of {GMM_SAMPLE} px, per date",
            "D": "per-image Otsu on the whole window (previous approach, comparison only)",
        },
        "offset_subtracted_dB": {d: round(hv_offsets.get(d, 0.0), 3) for d in dates},
        "summary": summary,
        "dates": [
            {
                "date": d,
                "methods": {key: results[key][d] for key in results},
            }
            for d in dates
        ],
    }
    (INTERIM / "water_stats.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")

    table = pd.DataFrame(
        {key: [results[key][d]["area_km2"] for d in dates] for key in results}, index=dates
    )
    print("\nWater area by method (km2):")
    print(table.to_string())
    print("\nStability:")
    for key in ("A", "B", "C", "D"):
        s = summary[key]
        print(f"  {key}: mean {s['area_mean_km2']:.2f}  sd {s['area_std_km2']:.2f}  "
              f"range {s['area_range_km2']:.2f}  band +/-{s['band_km2']:.2f}  "
              f"{s['km2_per_dB']:.1f} km2/dB  threshold sd {s['threshold_std_db']:.2f} dB  "
              f"change>band: {s['change_exceeds_band']}")

    fig, ax = plt.subplots(figsize=(8.5, 4.6), constrained_layout=True)
    x = np.arange(len(dates))
    for key, colour in (("A", "#1b7837"), ("B", "#762a83"), ("C", "#2166ac"), ("D", "#999999")):
        series = np.array([results[key][d]["area_km2"] for d in dates], dtype="float64")
        lows = np.array([results[key][d]["low_km2"] for d in dates], dtype="float64")
        highs = np.array([results[key][d]["high_km2"] for d in dates], dtype="float64")
        ax.plot(x, series, marker="o", markersize=4, color=colour, label=f"method {key}")
        ax.fill_between(x, lows, highs, color=colour, alpha=0.10)
    ax.set_xticks(x)
    ax.set_xticklabels(dates, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("water area (km2)")
    ax.set_title("Water area per date and method, with the +/-1.5 dB band", fontsize=11)
    ax.legend(fontsize=8)
    ax.text(0.01, -0.30,
            f"NISAR L2 GCOV CRID {scenes[0].meta.get('crid')} | HV | EPSG:32636 | offset removed | "
            f"band = area at threshold +/-{BAND_DB} dB",
            transform=ax.transAxes, fontsize=6, color="#444444", va="top")
    fig.savefig(INTERIM / "water_area_vs_date.png", dpi=140, bbox_inches="tight")
    plt.close(fig)

    print(f"\nWrote water_stats.json, threshold_sweep.csv/.png, water_area_vs_date.png to "
          f"{INTERIM.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
