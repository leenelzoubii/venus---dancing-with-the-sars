"""Step 4 - make the first real pictures and the first change map.

Reads the cached AOI windows from step 3 and produces, in ``data/interim/preview/``:

* one greyscale dB image per date and polarization (simple percentile stretch);
* a dB difference image for a chosen pair of dates (later minus earlier);
* a water-mask area table so we can start talking in numbers, honestly.

    python scripts/04_make_change_products.py --aoi dead_sea_east
    python scripts/04_make_change_products.py --aoi dead_sea_east --first 2026-06-24 --last 2026-10-10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402


def load_sidecars(indir: Path) -> list[dict]:
    cards = []
    for path in sorted(indir.glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        card["_json"] = path
        cards.append(card)
    return cards


def load_layer(card: dict, pol: str) -> np.ndarray:
    path = card["_json"].with_name(card["_json"].stem + f"_{pol}.npy")
    return np.load(path)


def extent_km(card: dict) -> list[float]:
    x, y = np.asarray(card["x"]), np.asarray(card["y"])
    return [0.0, (x[-1] - x[0]) / 1000.0, 0.0, (y[-1] - y[0]) / 1000.0]


def plot_single(db: np.ndarray, card: dict, pol: str, out: Path) -> tuple[float, float]:
    img, (vmin, vmax) = change.percentile_stretch(db, 2, 98)
    fig, ax = plt.subplots(figsize=(6.5, 9), dpi=140)
    ax.imshow(img, cmap="gray", extent=extent_km(card), origin="upper", interpolation="nearest")
    ax.set_title(
        f"NISAR GCOV {pol}  |  {card['acquisition_date']}  |  {card['maturity']}\n"
        f"track {card['track']} frame {card['frame']:03d} {card['direction'].lower()}  |  dB stretch {vmin:.1f} to {vmax:.1f}",
        fontsize=9,
        loc="left",
    )
    ax.set_xlabel("km (east)")
    ax.set_ylabel("km (north, from top of window)")
    fig.text(
        0.01, 0.01,
        f"product: {card['granule']}\nlayer: {card['layers'][pol]['dataset']} (gamma-0 power, 10*log10)",
        fontsize=6, color="#555",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out)
    plt.close(fig)
    return vmin, vmax


def plot_difference(
    diff: np.ndarray, first: dict, second: dict, pol: str, out: Path, offset_db: float = 0.0
) -> tuple[float, float]:
    """Difference image, with the scene-wide radiometric offset removed so real structure shows."""
    corrected = diff - offset_db
    finite = corrected[np.isfinite(corrected)]
    lim = float(np.percentile(np.abs(finite), 98)) if finite.size else 6.0
    lim = max(lim, 1.0)
    fig, ax = plt.subplots(figsize=(6.5, 9), dpi=140)
    im = ax.imshow(
        corrected, cmap="RdBu_r", vmin=-lim, vmax=lim, extent=extent_km(second), origin="upper",
        interpolation="nearest",
    )
    note = f"scene-wide offset {offset_db:+.2f} dB removed" if offset_db else "no offset removed"
    ax.set_title(
        f"Change in backscatter, {pol}  |  {second['acquisition_date']} minus {first['acquisition_date']}\n"
        f"blue = brighter later   red = darker later   |   {note}",
        fontsize=8.5, loc="left",
    )
    ax.set_xlabel("km (east)")
    ax.set_ylabel("km (north, from top of window)")
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("dB, relative to scene median")
    fig.text(
        0.01, 0.01,
        "same track/frame/direction only | gamma-0 power | multi-looked | median-filtered before differencing",
        fontsize=6, color="#555",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out)
    plt.close(fig)
    return -lim, lim


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    ap.add_argument("--indir", type=Path, default=None, help="Folder with step-3 subsets.")
    ap.add_argument("--outdir", type=Path, default=REPO_ROOT / "data" / "interim" / "preview")
    ap.add_argument("--pol", default=None, help="Polarization for the change pair (default: config).")
    ap.add_argument("--first", help="Earlier date, YYYY-MM-DD (default: first available).")
    ap.add_argument("--last", help="Later date, YYYY-MM-DD (default: last available).")
    ap.add_argument(
        "--threshold-db",
        type=float,
        default=None,
        help="Fixed water-mask threshold in dB. Omit to derive one per date with Otsu.",
    )
    ap.add_argument(
        "--multilook",
        type=int,
        default=None,
        help="Average NxN blocks in power before processing (e.g. 3 -> 60 m pixels, less speckle). "
        "Default: the config's processing.multilook.",
    )
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    indir = args.indir or (REPO_ROOT / "data" / "raw" / "subsets" / area.name)
    if not indir.exists():
        raise SystemExit(f"No subsets in {indir}. Run scripts/03_fetch_subset.py first.")
    pol = (args.pol or area.processing.get("polarization", "HH")).upper()
    filt = area.processing.get("speckle_filter", "median")
    win = int(area.processing.get("speckle_window", 5))
    factor = int(args.multilook if args.multilook is not None else area.processing.get("multilook", 1))
    factor = max(1, factor)
    pixel_m = float(area.processing.get("pixel_spacing_m", 20)) * factor

    cards = [c for c in load_sidecars(indir) if pol in c.get("layers", {})]
    if not cards:
        raise SystemExit(f"No subsets containing {pol} in {indir}.")
    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f"AOI {area.name}: {len(cards)} date(s) with {pol} in {indir.relative_to(REPO_ROOT)}")
    print(
        f"Processing: 10*log10(power) -> {factor}x{factor} multilook ({pixel_m:.0f} m) -> "
        f"{filt} {win}x{win} -> percentile stretch\n"
    )

    db_by_date: dict[str, np.ndarray] = {}
    threshold_by_date: dict[str, float] = {}
    mask_by_date: dict[str, np.ndarray] = {}
    rows = []
    for card in cards:
        day = card["acquisition_date"]
        power = load_layer(card, pol)
        if factor > 1:
            power = change.multilook_power(power, factor)
        db = change.power_to_db(power)
        db = change.speckle_filter(db, filt, win)
        db_by_date[day] = db
        out = args.outdir / f"{day}_{pol}_db.png"
        vmin, vmax = plot_single(db, card, pol, out)

        # Threshold: fixed if the user gave one, otherwise the valley between the dark water mode
        # and the bright land mode in this particular image.
        threshold = args.threshold_db
        if threshold is None:
            threshold = change.otsu_threshold(db)
        threshold_by_date[day] = threshold
        mask = change.water_mask(db, threshold)
        mask_by_date[day] = mask
        area_km2 = change.area_km2(mask, pixel_m)
        band = change.threshold_sensitivity(db, threshold, half_width_db=1.5, pixel_size_m=pixel_m)
        valid = np.isfinite(db)
        rows.append(
            {
                "date": day,
                "pol": pol,
                "valid_fraction": round(float(valid.mean()), 4),
                "db_median": round(float(np.nanmedian(db)), 2),
                "db_p5": round(float(np.nanpercentile(db, 5)), 2),
                "db_p95": round(float(np.nanpercentile(db, 95)), 2),
                "water_threshold_dB": round(float(threshold), 2),
                "water_km2": round(area_km2, 2),
                "water_km2_low_thr": round(min(a for _, a in band), 2),
                "water_km2_high_thr": round(max(a for _, a in band), 2),
                "water_fraction": round(float(mask.mean()), 4),
                "stretch_dB": f"{vmin:.1f}..{vmax:.1f}",
                "png": out.name,
            }
        )
        print(
            f"  {day}: median {rows[-1]['db_median']:>7.2f} dB   water(<{threshold:.2f} dB) "
            f"{area_km2:8.2f} km2  (band {rows[-1]['water_km2_low_thr']:.1f}-"
            f"{rows[-1]['water_km2_high_thr']:.1f} km2 over +/-1.5 dB)   -> {out.name}"
        )

    table = pd.DataFrame(rows)
    csv_out = args.outdir / f"stats_{pol}.csv"
    table.to_csv(csv_out, index=False)
    print(f"\nWrote {csv_out.relative_to(REPO_ROOT)}")

    dates = sorted(db_by_date)
    first = args.first or dates[0]
    last = args.last or dates[-1]

    # Per-date thresholds make the two images comparable; a single fixed threshold does not,
    # because the acquisitions differ by a scene-wide radiometric offset that shifts every mode.
    if first in db_by_date and last in db_by_date and first != last:
        w1, w2 = mask_by_date[first], mask_by_date[last]
        print(
            f"\nWater mask: {first} {table.loc[table['date'] == first, 'water_km2'].iloc[0]:.1f} km2  ->  "
            f"{last} {table.loc[table['date'] == last, 'water_km2'].iloc[0]:.1f} km2   "
            f"(thresholds {threshold_by_date[first]:.2f} / {threshold_by_date[last]:.2f} dB)"
        )
        print(
            f"  water lost {change.area_km2(w1 & ~w2, pixel_m):.2f} km2, "
            f"gained {change.area_km2(~w1 & w2, pixel_m):.2f} km2"
        )
        print(
            f"  WARNING if the two thresholds differ by more than ~0.5 dB: that is a radiometric "
            f"offset (here {threshold_by_date[last] - threshold_by_date[first]:+.2f} dB), not ground change."
        )

    if first in db_by_date and last in db_by_date and first != last:
        diff = change.difference_db(db_by_date[last], db_by_date[first])
        offset = float(np.nanmedian(diff))
        out = args.outdir / f"diff_{first}_{last}_{pol}.png"
        lo, hi = plot_difference(
            diff, cards[dates.index(first)], cards[dates.index(last)], pol, out, offset_db=offset
        )
        both_water = mask_by_date[first] & mask_by_date[last]
        both_land = ~mask_by_date[first] & ~mask_by_date[last]
        stats = {
            "first": first, "last": last, "pol": pol,
            "differences_of_interest": {
                "median_dB": round(float(np.nanmedian(diff)), 2),
                "p2_dB": round(float(np.nanpercentile(diff, 2)), 2),
                "p98_dB": round(float(np.nanpercentile(diff, 98)), 2),
                "strong_darkening_fraction (<-3 dB)": round(float(np.nanmean(diff < -3)), 4),
                "strong_brightening_fraction (>+3 dB)": round(float(np.nanmean(diff > 3)), 4),
                "median_dB_over_water": round(float(np.nanmedian(diff[both_water])), 2)
                if both_water.any() else None,
                "median_dB_over_land": round(float(np.nanmedian(diff[both_land])), 2)
                if both_land.any() else None,
            },
            "water_threshold_dB": {first: round(float(threshold_by_date[first]), 2),
                                   last: round(float(threshold_by_date[last]), 2)},
            "water_km2": {first: round(change.area_km2(mask_by_date[first], pixel_m), 2),
                          last: round(change.area_km2(mask_by_date[last], pixel_m), 2)},
            "display_limits_dB": [round(lo, 2), round(hi, 2)],
            "scene_wide_offset_dB_removed": round(offset, 2),
            "multilook": factor,
            "pixel_spacing_m": pixel_m,
            "png": out.name,
        }
        (args.outdir / f"diff_{first}_{last}_{pol}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
        print(f"  change {first} -> {last}: median {stats['differences_of_interest']['median_dB']} dB, "
              f"{stats['differences_of_interest']['strong_darkening_fraction (<-3 dB)'] * 100:.1f}% darker by >3 dB, "
              f"water {stats['differences_of_interest']['median_dB_over_water']} dB vs "
              f"land {stats['differences_of_interest']['median_dB_over_land']} dB -> {out.name}")
    else:
        print(f"\nNo pair to difference (first={first}, last={last}).")

    print("\nNext: review the PNGs in Explorer, then tell me what you see before we interpret it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
