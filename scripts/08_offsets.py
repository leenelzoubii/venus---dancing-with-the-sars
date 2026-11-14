"""Step 8 - per-date scene-wide offsets, estimated on land only.

Two dates a month apart differ by a whole-scene brightness shift of a few tenths of a dB. That shift
applies to water and land alike, so it cannot be surface change; it is either calibration or a
seasonal effect common to everything. Either way it must be measured before any differencing, and it
must be measured on the population we trust: stable land, good look counts, not the lake.

    python scripts/08_offsets.py --aoi dead_sea_east

Writes data/interim/offsets.csv, offsets.json and offset_vs_date.png.
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
from matplotlib.patches import Rectangle  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change, stack  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

INTERIM = REPO_ROOT / "data" / "interim"
MULTILOOK = 3
SPECKLE = ("median", 5)
HV_LAND_CUT_DB = -15.0
MIN_LOOKS = 4.0
OUTAGE = ("2026-07-27", "2026-08-10")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    scenes = stack.load_scenes(area.name)
    grid = stack.verify_grid(scenes)
    if grid["problems"]:
        raise SystemExit("Grid problems: " + "; ".join(grid["problems"]))

    reference = scenes[0]
    print(f"AOI {area.name}: {len(scenes)} dates, reference {reference.date}")

    def prepare(scene, pol):
        power = change.multilook_power(scene.power(pol), MULTILOOK)
        return change.power_to_db(change.speckle_filter(power, *SPECKLE))

    db = {(s.date, p): prepare(s, p) for s in scenes for p in ("HH", "HV")}
    land = change.land_mask(
        db[(reference.date, "HV")],
        looks=change.multilook_power(reference.looks.astype("float32"), MULTILOOK),
        hh_db=db[(reference.date, "HH")],
        hv_land_cut_db=HV_LAND_CUT_DB,
        min_looks=MIN_LOOKS,
    )
    land_pct = 100 * float(land.mean())
    print(f"Land definition: HV > {HV_LAND_CUT_DB} dB, looks >= {MIN_LOOKS}, finite HH+HV "
          f"-> {land_pct:.1f}% of the window, {int(land.sum())} px\n")

    rows = []
    for scene in scenes:
        for pol in ("HH", "HV"):
            offset, n, mad = change.robust_offset_db(db[(scene.date, pol)], db[(reference.date, pol)], land)
            rows.append({
                "date": scene.date,
                "pol": pol,
                "offset_dB": round(offset, 3) if np.isfinite(offset) else None,
                "n_pixels": n,
                "MAD_dB": round(mad, 3) if np.isfinite(mad) else None,
            })

    table = pd.DataFrame(rows)
    table.to_csv(INTERIM / "offsets.csv", index=False, encoding="utf-8")

    # ---- how much does the offset move if the land definition moves? --------------------------
    variants = [
        {"hv_cut_db": -14.0, "min_looks": MIN_LOOKS},
        {"hv_cut_db": -16.0, "min_looks": MIN_LOOKS},
        {"hv_cut_db": HV_LAND_CUT_DB, "min_looks": 3.0},
        {"hv_cut_db": HV_LAND_CUT_DB, "min_looks": 6.0},
    ]
    sensitivity = {}
    for pol in ("HH", "HV"):
        spread = 0.0
        for variant in variants:
            alt = change.land_mask(
                db[(reference.date, "HV")],
                looks=change.multilook_power(reference.looks.astype("float32"), MULTILOOK),
                hh_db=db[(reference.date, "HH")],
                hv_land_cut_db=variant["hv_cut_db"],
                min_looks=variant["min_looks"],
            )
            values = [
                change.robust_offset_db(db[(s.date, pol)], db[(reference.date, pol)], alt)[0]
                for s in scenes[1:]
            ]
            baseline = [
                change.robust_offset_db(db[(s.date, pol)], db[(reference.date, pol)], land)[0]
                for s in scenes[1:]
            ]
            spread = max(spread, float(np.nanmax(np.abs(np.array(values) - np.array(baseline)))))
        sensitivity[pol] = round(spread, 3)
        print(f"{pol}: offset moves at most {spread:.3f} dB when the land definition changes "
              f"(4 variants: HV cut -14/-16 dB, looks 3/6)")

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aoi": area.name,
        "reference_date": reference.date,
        "product": "NISAR L2 GCOV",
        "crid": reference.meta.get("crid"),
        "geometry": f"track {reference.meta.get('track')} frame {reference.meta.get('frame')} "
                    f"{reference.meta.get('direction')}",
        "processing": [
            f"{MULTILOOK}x{MULTILOOK} multilook in power ({20 * MULTILOOK} m)",
            "10*log10(power)",
            f"median {SPECKLE[1]}x{SPECKLE[1]} speckle filter",
            "offset = median of (date - reference) over land",
        ],
        "land_definition": {
            "hv_cut_db": HV_LAND_CUT_DB,
            "min_looks": MIN_LOOKS,
            "requires_finite": ["HH", "HV"],
            "share_of_window_pct": round(land_pct, 2),
            "n_pixels": int(land.sum()),
        },
        "land_definition_sensitivity_dB": sensitivity,
        "offsets": rows,
    }
    (INTERIM / "offsets.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")

    pivot = table.pivot(index="date", columns="pol", values="offset_dB")
    print(table.to_string(index=False))


    # ---- offset versus date ------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 4.6), constrained_layout=True)
    dates = list(pivot.index)
    x = np.arange(len(dates))
    for pol, colour in (("HV", "#2166ac"), ("HH", "#b2182b")):
        ax.plot(x, pivot[pol].to_numpy(), marker="o", label=f"{pol} offset", color=colour)
    ax.axhline(0.0, color="#888888", linewidth=0.8)
    ax.axvspan(2.5, 3.5, color="#dddddd", alpha=0.7, label="mission outage 27 Jul - 10 Aug")
    ax.set_xticks(x)
    ax.set_xticklabels(dates, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("offset vs reference date (dB)")
    ax.set_title(f"Scene-wide offset by date, land only (reference {reference.date})", fontsize=11)
    ax.legend(fontsize=8)
    ax.text(
        0.01, -0.42,
        "Hypothesis, not finding: a step at the outage or at a processing change suggests calibration drift; "
        "a smooth seasonal curve suggests real surface change (soil moisture, drying).\n"
        f"NISAR L2 GCOV CRID {reference.meta.get('crid')} | track {reference.meta.get('track')} frame "
        f"{reference.meta.get('frame')} | median over land where HV > {HV_LAND_CUT_DB} dB and looks >= {MIN_LOOKS}",
        transform=ax.transAxes, fontsize=6, color="#444444", va="top",
    )
    fig.savefig(INTERIM / "offset_vs_date.png", dpi=140, bbox_inches="tight")
    plt.close(fig)

    print(f"\nWrote offsets.csv, offsets.json, offset_vs_date.png to {INTERIM.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
