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
    hh_offsets = {row["date"]: float(row["offset_dB"]) for row in offsets["offsets"] if row["pol"] == "HH"}

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
    # HH is kept for comparison only: per-image Otsu on HH (the earlier method), so the app can show
    # why HH is unreliable for water. The HV land-cut rule does not transfer to HH.
    hh_results = {}
    for scene in scenes:
        hh_db = change.speckle_filter(change.power_to_db(scene.power("HH")), *SPECKLE)
        hh_db = hh_db - float(hh_offsets.get(scene.date, 0.0))
        hh_thr = change.otsu_threshold(hh_db)
        if np.isfinite(hh_thr):
            hh_area, low, high = water.area_band(hh_db, hh_thr, half_width_db=BAND_DB, pixel_size_m=20.0)
            hh_results[scene.date] = {"threshold_db": round(float(hh_thr), 2), "area_km2": round(hh_area, 2),
                                      "low_km2": round(low, 2), "high_km2": round(high, 2)}
        else:
            hh_results[scene.date] = {"threshold_db": None, "area_km2": None, "low_km2": None, "high_km2": None}
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
    day_offsets = np.array([(np.datetime64(d) - np.datetime64(dates[0])).astype(int) for d in dates], dtype="float64")
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
            "trend_km2_per_30d": round(float(np.polyfit(day_offsets, series, 1)[0] * 30.0), 3),
        }

    # ---- change-detection limit, separate from the absolute-area band -------------------------
    # The +/-1.5 dB band answers "how well do we know the area of one date". It does NOT answer
    # "is the difference between two dates real". For that we ask a different question: across a
    # narrow range of thresholds around the chosen one, does the SIGN of the difference ever flip?
    # If it does, the ranking of the two dates is an artefact of the threshold, not a measurement.
    tau_range = np.arange(-0.5, 0.5 + 1e-9, 0.1)
    offset_mad = float(np.median([r["MAD_dB"] for r in offsets["offsets"] if r["pol"] == POL and r["MAD_dB"]]))
    land_sensitivity = float(offsets.get("land_definition_sensitivity_dB", {}).get(POL, 0.0))
    offset_uncertainty = offset_mad + land_sensitivity

    detection = {}
    for key in ("A", "B", "C", "D"):
        baseline = float(np.nanmedian([results[key][d]["threshold_db"] for d in dates]))
        if not np.isfinite(baseline):
            detection[key] = {}
            continue
        areas = {d: [water.area_at_threshold(db[d], baseline + t, 20.0) for t in tau_range] for d in dates}
        pairs = []
        for i in range(len(dates)):
            for j in range(i + 1, len(dates)):
                diffs = np.array(areas[dates[j]]) - np.array(areas[dates[i]])
                robust = bool(np.all(diffs > 0) or np.all(diffs < 0))
                pairs.append({
                    "from": dates[i],
                    "to": dates[j],
                    "delta_km2": round(float(np.median(diffs)), 2),
                    "min_km2": round(float(diffs.min()), 2),
                    "max_km2": round(float(diffs.max()), 2),
                    "sign_robust": robust,
                })
        slope = float(np.nanmedian(
            [(areas[d][-1] - areas[d][0]) / (tau_range[-1] - tau_range[0]) for d in dates]
        ))
        for index, d in enumerate(dates):
            results[key][d]["km2_per_0.1db"] = round(
                (areas[d][-1] - areas[d][0]) / (tau_range[-1] - tau_range[0]) * 0.1, 2
            )
        detection[key] = {
            "baseline_threshold_db": round(baseline, 2),
            "threshold_range_db": [round(float(tau_range[0]), 2), round(float(tau_range[-1]), 2)],
            "km2_per_0.1db": round(slope * 0.1, 2),
            "offset_uncertainty": {
                "mad_db": round(offset_mad, 3),
                "land_definition_db": round(land_sensitivity, 3),
                "total_db": round(offset_uncertainty, 3),
                "area_equivalent_km2": round(offset_uncertainty * slope, 2),
            },
            "n_pairs": len(pairs),
            "n_sign_robust": int(sum(p["sign_robust"] for p in pairs)),
            "largest_abs_delta_km2": round(float(max(abs(p["delta_km2"]) for p in pairs)), 2),
            "pairs": pairs,
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
        "primary_method": "B",
        "primary_polarization": POL,
        "band_definition": (
            "The +/-1.5 dB band is the ABSOLUTE AREA UNCERTAINTY for a single date: how much the area "
            "moves if the threshold is 1.5 dB too low or too high."
        ),
        "change_detection_definition": (
            "The CHANGE DETECTION LIMIT is separate: for each pair of dates, the area difference is "
            "recomputed across thresholds from the baseline -0.5 dB to +0.5 dB. If the sign of the "
            "difference never flips, the ranking of those two dates is robust to the threshold."
        ),
        "offset_subtracted_dB": {d: round(hv_offsets.get(d, 0.0), 3) for d in dates},
        "summary": summary,
        "change_detection": detection,
        "dates": [
            {
                "date": d,
                "methods": {key: results[key][d] for key in results},
                "hh_comparison": hh_results[d],
            }
            for d in dates
        ],
    }
    (INTERIM / "water_stats.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")

    # ---- honest verdict: a change counts only if its sign is robust AND it clears the limit -----
    verdicts = {}
    for key in ("A", "B", "C", "D"):
        det = detection.get(key) or {}
        if not det:
            verdicts[key] = "no finite threshold, no verdict"
            continue
        limit_km2 = det["offset_uncertainty"]["area_equivalent_km2"]
        cleared = [p for p in det["pairs"] if p["sign_robust"] and abs(p["delta_km2"]) > limit_km2]
        det["n_changes_above_limit"] = len(cleared)
        det["change_detection_limit_km2"] = limit_km2
        if cleared:
            worst = max(cleared, key=lambda p: abs(p["delta_km2"]))
            verdicts[key] = (
                f"{len(cleared)} of {det['n_pairs']} date pairs change by more than the detection limit "
                f"({limit_km2:.2f} km2) with a robust sign; largest {worst['from']} to {worst['to']}: "
                f"{worst['delta_km2']:+.2f} km2. Hypothesis only, not confirmed change."
            )
        else:
            verdicts[key] = (
                f"No date-to-date change is larger than the detection limit ({limit_km2:.2f} km2). "
                f"{det['n_sign_robust']} of {det['n_pairs']} pairs keep their sign across thresholds, "
                f"but none is larger than the limit. Area trend {summary[key]['trend_km2_per_30d']:+.2f} km2 "
                f"per 30 days (linear fit, not significance-tested)."
            )
        payload["change_detection"][key]["verdict"] = verdicts[key]
        payload["change_detection"][key]["caption"] = (
            f"Method {key}: area +/-{summary[key]['band_km2']:.1f} km2 absolute (threshold +/-{BAND_DB} dB); "
            f"sensitivity {det['km2_per_0.1db']:.2f} km2 per 0.1 dB; "
            f"change detection limit {limit_km2:.2f} km2 (offset MAD {det['offset_uncertainty']['mad_db']:.2f} dB "
            f"+ land definition {det['offset_uncertainty']['land_definition_db']:.2f} dB); "
            f"pairs above limit {len(cleared)}/{det['n_pairs']}"
        )

    payload["primary_verdict"] = verdicts.get("B", "")
    payload["primary_caption"] = payload["change_detection"]["B"]["caption"]
    (INTERIM / "water_stats.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print("\nVerdict (method B, primary):")
    print("  " + verdicts.get("B", ""))
    for key in ("A", "B", "C", "D"):
        det = detection[key]
        print(f"  {key}: {det['km2_per_0.1db']:.2f} km2/0.1 dB, "
              f"offset uncertainty {det['offset_uncertainty']['area_equivalent_km2']:.2f} km2, "
              f"sign-robust {det['n_sign_robust']}/{det['n_pairs']}")

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
