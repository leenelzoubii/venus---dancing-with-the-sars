"""Step 7 - contact sheets: nine dates on one page, so a human can see the series at a glance.

Two jobs, and the second is the science one:

1. ``contact_<POL>_db.png`` - raw backscatter, identical colour limits on every panel. If the limits
   moved between panels the eye would read stretch as change.
2. ``contact_delta_<POL>.png`` - each date minus the first, after offset removal and 3x3 multilook,
   on a symmetric diverging ramp with NaN transparent.

    python scripts/07_contact_sheets.py --aoi dead_sea_east
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no GUI, ever: this may run on a headless machine

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change, stack  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

OUT = REPO_ROOT / "data" / "interim" / "contact_sheets"
POLS = ("HV", "HH")
MULTILOOK = 3          # 3x3 x 20 m = 60 m
SPECKLE = ("median", 5)

# Colour-blind-safe diverging ramp: deep blue (darker later) -> white -> orange (brighter later).
DIVERGING = LinearSegmentedColormap.from_list(
    "venus_diverging", ["#2166ac", "#92c5de", "#f7f7f7", "#f4a582", "#b2182b"], N=256
)


def caption(scene_meta: dict, extra: str) -> str:
    return (
        f"NISAR L2 GCOV (CRID {scene_meta.get('crid')}, {scene_meta.get('maturity')})  |  "
        f"track {scene_meta.get('track')} frame {scene_meta.get('frame')} "
        f"{scene_meta.get('direction')}  |  window rows {scene_meta['rows'][0]}-{scene_meta['rows'][1]} "
        f"cols {scene_meta['cols'][0]}-{scene_meta['cols'][1]} at 20 m, EPSG:32636  |  {extra}"
    )


def grid_axes(n: int):
    fig, axes = plt.subplots(3, 3, figsize=(13, 15), constrained_layout=False)
    axes = axes.ravel()
    for ax in axes[n:]:
        ax.axis("off")
    return fig, axes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    scenes = stack.load_scenes(area.name)
    grid = stack.verify_grid(scenes)
    if grid["problems"]:
        raise SystemExit("Grid problems, refusing to draw: " + "; ".join(grid["problems"]))

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"AOI {area.name}: {len(scenes)} dates, {grid['shape']} px on one grid")

    # ---- load once: dB (speckle-filtered) + power for multilook -------------------------------
    db = {}
    power = {}
    for scene in scenes:
        for pol in POLS:
            power[(scene.date, pol)] = scene.power(pol)
            db[(scene.date, pol)] = change.speckle_filter(
                change.power_to_db(power[(scene.date, pol)]), SPECKLE[0], SPECKLE[1]
            )

    # ---- 2a. absolute backscatter, one shared stretch -----------------------------------------
    for pol in POLS:
        pooled = np.concatenate([db[(s.date, pol)][np.isfinite(db[(s.date, pol)])].ravel() for s in scenes])
        vmin, vmax = (float(v) for v in np.percentile(pooled, [2, 98]))
        print(f"{pol}: pooled 2nd/98th percentile = {vmin:.2f} / {vmax:.2f} dB (shared by all panels)")

        fig, axes = grid_axes(len(scenes))
        image = None
        for ax, scene in zip(axes, scenes):
            image = ax.imshow(
                db[(scene.date, pol)], cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest"
            )
            ax.set_title(f"{scene.date}  {pol}", fontsize=10, loc="left")
            ax.set_xticks([])
            ax.set_yticks([])
        fig.suptitle(f"Contact sheet - {pol} gamma-0 backscatter, offset NOT applied", fontsize=13)
        cbar = fig.colorbar(image, ax=axes.tolist(), fraction=0.025, pad=0.02)
        cbar.set_label("dB")
        fig.text(
            0.01, 0.005,
            caption(scenes[0].meta, f"processing: 10*log10(power), median {SPECKLE[1]}x{SPECKLE[1]}; "
                                    f"stretch = pooled 2nd-98th percentile ({vmin:.1f} to {vmax:.1f} dB)"),
            fontsize=6, color="#444444",
        )
        path = OUT / f"contact_{pol}_db.png"
        fig.savefig(path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        print(f"  wrote {path.relative_to(REPO_ROOT)}")

    # ---- 2b. change relative to the first date, offsets removed -------------------------------
    reference = scenes[0]
    offsets = {}
    multilooked = {}
    for scene in scenes:
        for pol in POLS:
            multilooked[(scene.date, pol)] = change.multilook_power(power[(scene.date, pol)], MULTILOOK)

    land = change.land_mask(
        change.power_to_db(change.speckle_filter(multilooked[(reference.date, "HV")], "median", 5)),
        looks=change.multilook_power(reference.looks.astype("float32"), MULTILOOK),
        hh_db=change.power_to_db(change.speckle_filter(multilooked[(reference.date, "HH")], "median", 5)),
        hv_land_cut_db=-15.0,
        min_looks=4.0,
    )
    for scene in scenes:
        for pol in POLS:
            if scene.date == reference.date:
                continue
            later = change.power_to_db(change.speckle_filter(multilooked[(scene.date, pol)], "median", 5))
            earlier = change.power_to_db(change.speckle_filter(multilooked[(reference.date, pol)], "median", 5))
            offset, _, _ = change.robust_offset_db(later, earlier, land)
            offsets[(scene.date, pol)] = offset

    deltas = {}
    for scene in scenes:
        if scene.date == reference.date:
            continue
        for pol in POLS:
            later = change.power_to_db(change.speckle_filter(multilooked[(scene.date, pol)], "median", 5))
            earlier = change.power_to_db(change.speckle_filter(multilooked[(reference.date, pol)], "median", 5))
            deltas[(scene.date, pol)] = change.difference_db(later, earlier) - offsets[(scene.date, pol)]

    for pol in POLS:
        pooled = np.concatenate([np.abs(deltas[(s.date, pol)][np.isfinite(deltas[(s.date, pol)])]).ravel()
                                 for s in scenes if s.date != reference.date])
        p99 = float(np.percentile(pooled, 99))
        limit = min(6.0, p99)
        print(f"{pol}: symmetric limit = +/-{limit:.2f} dB "
              f"({'6 dB cap' if p99 > 6.0 else 'pooled 99th percentile of |delta|'})")

        fig, axes = grid_axes(len(scenes))
        image = None
        for ax, scene in zip(axes, scenes):
            if scene.date == reference.date:
                ax.axis("off")
                ax.text(0.5, 0.5, "reference date\n" + scene.date, ha="center", va="center", fontsize=11)
                continue
            image = ax.imshow(
                deltas[(scene.date, pol)], cmap=DIVERGING, vmin=-limit, vmax=limit,
                interpolation="nearest",
            )
            ax.set_title(f"{scene.date} minus {reference.date}", fontsize=10, loc="left")
            ax.set_xticks([])
            ax.set_yticks([])
        fig.suptitle(f"Change in {pol} (dB) relative to {reference.date}, scene offset removed", fontsize=13)
        cbar = fig.colorbar(image, ax=axes.tolist(), fraction=0.025, pad=0.02)
        cbar.set_label("dB change (blue = less echo later, red = more)")
        note = "  |  ".join(
            f"{s.date}: {offsets[(s.date, pol)]:+.2f} dB" for s in scenes if s.date != reference.date
        )
        fig.text(
            0.01, 0.012, caption(scenes[0].meta,
                                 f"processing: 3x3 multilook in power (60 m), 10*log10, median 5x5, "
                                 f"land-median offset removed, limit +/-{limit:.1f} dB; NaN transparent"),
            fontsize=6, color="#444444",
        )
        fig.text(0.01, 0.004, "offsets removed: " + note, fontsize=6, color="#444444")
        path = OUT / f"contact_delta_{pol}.png"
        fig.savefig(path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        print(f"  wrote {path.relative_to(REPO_ROOT)}")

    print(f"\nContact sheets in {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
