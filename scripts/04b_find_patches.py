"""Step 4b - candidate change patches on the eastern plain, with the evidence attached.

The plain east of the Dead Sea is where the strongest non-water signal lives. This script does not
explain it. It finds blobs that are persistently different from the first date, measures them, and
writes the evidence into files a human can read, so that the explanation (or the decision to drop
them) is made from the data rather than from a hunch.

Detection rule, deliberately conservative:

* work at 60 m (3x3 blocked average in power) - at 20 m speckle alone crosses any threshold;
* |delta| > T dB versus the reference date, using offset-corrected dB;
* that must happen on at least ``min_consecutive`` CONSECUTIVE dates, because speckle is not
  correlated between dates and real change is;
* drop water pixels and low-look pixels;
* keep components of at least ``min_area_px`` pixels.

    python scripts/04b_find_patches.py --aoi dead_sea_east
    python scripts/04b_find_patches.py --aoi dead_sea_east --threshold-db 2 --min-area-px 10
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio.features  # noqa: E402
from affine import Affine  # noqa: E402
from pyproj import CRS, Transformer  # noqa: E402
from shapely.geometry import mapping, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change, patches, stack, water  # noqa: E402
from venus.config import REPO_ROOT, add_aoi_arguments, load_study_area  # noqa: E402

INTERIM = REPO_ROOT / "data" / "interim"
DOCS = REPO_ROOT / "docs"
SPECKLE = ("median", 5)
POLS = ("HH", "HV")


def multilook_grid(meta: dict, factor: int) -> tuple[Affine, float]:
    """Affine transform and pixel size of the blocked-averaged grid, from the native coordinates.

    x/y are pixel *centres* 20 m apart, so the block grid origin is the outer edge of the first pixel
    and each new pixel is ``factor * 20`` m wide.
    """
    spacing = float(meta["pixel_spacing_m"])
    x0 = float(meta["x"][0]) - spacing / 2.0
    y0 = float(meta["y"][0]) + spacing / 2.0
    size = spacing * factor
    return Affine(size, 0.0, x0, 0.0, -size, y0), size


def to_lonlat(xs, ys, crs_wkt: str):
    transformer = Transformer.from_crs(CRS.from_wkt(crs_wkt), CRS.from_epsg(4326), always_xy=True)
    return transformer.transform(xs, ys)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_aoi_arguments(ap)
    ap.add_argument("--threshold-db", type=float, default=None, help="Override |delta| threshold.")
    ap.add_argument("--min-area-px", type=int, default=None, help="Override minimum patch area in px.")
    ap.add_argument("--min-consecutive", type=int, default=None, help="Override consecutive-date rule.")
    ap.add_argument("--tag", default="", help="Suffix for output files, e.g. _sensitive.")
    args = ap.parse_args()

    area = load_study_area(args.aoi, args.aoi_wkt)
    cfg = area.patches or {}
    threshold_db = float(args.threshold_db if args.threshold_db is not None else cfg.get("threshold_db", 3.0))
    min_consecutive = int(args.min_consecutive if args.min_consecutive is not None else cfg.get("min_consecutive", 2))
    min_area_px = int(args.min_area_px if args.min_area_px is not None else cfg.get("min_area_px", 20))
    looks_pct = float(cfg.get("min_looks_percentile", 10))
    connectivity = int(cfg.get("connectivity", 8))
    tag = args.tag
    factor = int(area.processing.get("multilook", 3))

    scenes = stack.load_scenes(area.name)
    grid = stack.verify_grid(scenes)
    if grid["problems"]:
        raise SystemExit("Grid problems: " + "; ".join(grid["problems"]))

    offsets_path = INTERIM / "offsets.json"
    offsets_doc = json.loads(offsets_path.read_text(encoding="utf-8")) if offsets_path.exists() else {"offsets": []}
    offsets = {(r["date"], r["pol"]): float(r["offset_dB"] or 0.0) for r in offsets_doc.get("offsets", [])}
    reference = scenes[0]
    dates = [s.date for s in scenes]
    transform, pixel_m = multilook_grid(reference.meta, factor)

    print(f"AOI {area.name}: {len(scenes)} dates, reference {reference.date}, {factor}x{factor} -> {pixel_m:.0f} m")
    print(f"Rule: |delta| > {threshold_db:.1f} dB on >= {min_consecutive} consecutive dates, "
          f"area >= {min_area_px} px, connectivity {connectivity}")

    # ---- load, offset, multilook --------------------------------------------------------------
    db: dict[tuple[str, str], np.ndarray] = {}
    for scene in scenes:
        for pol in POLS:
            power = change.multilook_power(scene.power(pol), factor)
            db[(scene.date, pol)] = change.power_to_db(change.speckle_filter(power, *SPECKLE)) - offsets.get(
                (scene.date, pol), 0.0
            )

    looks60 = change.multilook_power(reference.looks.astype("float32"), factor)
    looks_cut = float(np.nanpercentile(looks60, looks_pct))
    print(f"numberOfLooks at 60 m: 10th percentile = {looks_cut:.2f} (pixels below it are excluded)")

    # ---- water exclusion, primary method B, union over all dates -------------------------------
    water_union = np.zeros_like(looks60, dtype=bool)
    for scene in scenes:
        threshold = water.two_step_threshold(db[(scene.date, "HV")])
        if np.isfinite(threshold):
            water_union |= np.isfinite(db[(scene.date, "HV")]) & (db[(scene.date, "HV")] < threshold)
    print(f"Water excluded (method B, any date): {100 * water_union.mean():.1f}% of the window")

    eligible = np.isfinite(looks60) & (looks60 >= looks_cut) & ~water_union

    # ---- deltas versus the reference ----------------------------------------------------------
    delta = {pol: [] for pol in POLS}
    for scene in scenes[1:]:
        for pol in POLS:
            delta[pol].append(change.difference_db(db[(scene.date, pol)], db[(reference.date, pol)]))

    def detect(threshold: float, min_px: int) -> tuple[np.ndarray, int]:
        stacks = [patches.changed_stack(delta[pol], threshold) & eligible for pol in POLS]
        changed = np.logical_or.reduce(stacks)
        persistent = patches.consecutive_any(changed, min_consecutive)
        return patches.label_patches(persistent, min_px, connectivity)

    labels, count = detect(threshold_db, min_area_px)
    print(f"\nPatches found: {count}")

    # ---- properties ---------------------------------------------------------------------------
    gdal_crs = CRS.from_wkt(reference.meta["crs_wkt"])
    records = []
    timeseries = []
    for label, slc in enumerate(patches.patch_slices(labels, count), start=1):
        if slc is None:
            continue
        window = labels[slc] == label
        rows, cols = np.nonzero(window)
        rows = rows + slc[0].start
        cols = cols + slc[1].start
        area_km2 = patches.subpixel_area_km2(int(window.sum()), pixel_m)

        centroid_x = transform.c + (cols.mean() + 0.5) * transform.a
        centroid_y = transform.f + (rows.mean() + 0.5) * transform.e
        lon, lat = to_lonlat([centroid_x], [centroid_y], reference.meta["crs_wkt"])

        per_date = {}
        deltas_per_date = {}
        for pol in POLS:
            series = patches.patch_statistics(labels, db[(reference.date, pol)])
            per_date[pol] = series.get(label)
        for index, scene in enumerate(scenes[1:]):
            for pol in POLS:
                values = np.where(labels == label, delta[pol][index], np.nan)
                finite = values[np.isfinite(values)]
                deltas_per_date.setdefault(scene.date, {})[pol] = (
                    float(np.median(finite)) if finite.size else float("nan")
                )
                timeseries.append({
                    "patch_id": f"P{label:02d}",
                    "date": scene.date,
                    "pol": pol,
                    "db": round(float(per_date[pol]), 3) if per_date[pol] is not None else None,
                    "delta_db": round(float(np.median(finite)), 3) if finite.size else None,
                })

        mean_delta = {d: float(np.nanmean([v[pol] for pol in POLS])) for d, v in deltas_per_date.items()}
        sign = patches.dominant_sign(mean_delta)
        first = patches.first_date_above(mean_delta, threshold_db)
        n_dates = patches.count_dates_above(mean_delta, threshold_db)

        # Polygon from the labelled raster, in UTM then reprojected to WGS84.
        polygons = [
            shape(geom) for geom, value in rasterio.features.shapes(
                labels.astype("int32"), mask=(labels == label), transform=transform
            ) if value == label
        ]
        utm_geom = unary_union(polygons)
        transformer = Transformer.from_crs(gdal_crs, CRS.from_epsg(4326), always_xy=True)

        def _project(x, y, z=None):
            return transformer.transform(x, y)

        from shapely.ops import transform as shapely_transform

        wgs84 = shapely_transform(_project, utm_geom)

        records.append({
            "id": f"P{label:02d}",
            "label": label,
            "lon": round(float(lon[0]), 6),
            "lat": round(float(lat[0]), 6),
            "area_km2": round(area_km2, 4),
            "sign": sign,
            "first_date": first,
            "n_dates": n_dates,
            "mean_looks": round(float(np.nanmean(np.where(labels == label, looks60, np.nan))), 2),
            "ref_HH_db": round(float(per_date["HH"]), 2) if per_date["HH"] is not None else None,
            "ref_HV_db": round(float(per_date["HV"]), 2) if per_date["HV"] is not None else None,
            "geometry_wgs84": wgs84,
            "delta_by_date": deltas_per_date,
        })

    distances = patches.distance_to_mask_km(labels, water_union, pixel_m)
    for record in records:
        record["water_distance_km"] = round(distances.get(record["label"], float("nan")), 3)

    # ---- outputs ------------------------------------------------------------------------------
    features = []
    for record in records:
        features.append({
            "type": "Feature",
            "geometry": mapping(record["geometry_wgs84"]),
            "properties": {k: v for k, v in record.items() if k not in ("geometry_wgs84", "label")},
        })
    geojson = {
        "type": "FeatureCollection",
        "name": f"{area.name}_patches",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }
    (INTERIM / f"patches{tag}.geojson").write_text(json.dumps(geojson, indent=1), encoding="utf-8")

    with open(INTERIM / f"patch_timeseries{tag}.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["patch_id", "date", "pol", "db", "delta_db"])
        writer.writeheader()
        writer.writerows(timeseries)

    # Human log for Leyan: objective columns filled, judgement columns deliberately empty.
    DOCS.mkdir(parents=True, exist_ok=True)
    human = ["behaviour", "on_the_ground", "hypothesis", "evidence", "confidence", "use_in_pitch"]
    with open(DOCS / f"patch_log{tag}.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["patch_id", "lon", "lat", "area_km2", "sign", "first_date", "n_dates",
                         "mean_looks"] + human)
        for record in records:
            writer.writerow([
                record["id"], record["lon"], record["lat"], record["area_km2"], record["sign"],
                record["first_date"] or "", record["n_dates"], record["mean_looks"],
            ] + [""] * len(human))

    # ---- preview: HV delta on the last date, with outlines --------------------------------------
    last_index = len(delta["HV"]) - 1
    limit = float(np.nanpercentile(np.abs(delta["HV"][last_index]), 99))
    fig, ax = plt.subplots(figsize=(7.5, 12), constrained_layout=True)
    image = ax.imshow(delta["HV"][last_index], cmap="RdBu_r", vmin=-limit, vmax=limit)
    ax.contour(labels > 0, levels=[0.5], colors="#111111", linewidths=0.8)
    for record in records:
        ax.text(record["lon"] and (np.nonzero(labels == record["label"])[1].mean()),
                np.nonzero(labels == record["label"])[0].mean(),
                record["id"], fontsize=7, color="#000000", weight="bold")
    ax.set_title(f"Candidate patches, HV change {dates[-1]} minus {reference.date}", fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])
    bar = fig.colorbar(image, ax=ax, fraction=0.04, pad=0.02)
    bar.set_label("dB change (blue = less echo later, red = more)")
    fig.text(0.01, 0.004,
             f"NISAR L2 GCOV CRID {reference.meta.get('crid')} PROVISIONAL | track {reference.meta.get('track')} "
             f"frame {reference.meta.get('frame')} DESC | HV | {factor}x{factor} multilook (60 m) | offset removed | "
             f"|delta| > {threshold_db:.1f} dB on {min_consecutive} consecutive dates | "
             f"area >= {min_area_px} px | water and low-look pixels excluded",
             fontsize=5.5, color="#444444")
    fig.savefig(INTERIM / f"patch_preview{tag}.png", dpi=130, bbox_inches="tight")
    plt.close(fig)

    # ---- timeseries small multiples ------------------------------------------------------------
    if records:
        ncols = 4
        nrows = int(np.ceil(len(records) / ncols))
        fig, axes = plt.subplots(nrows, ncols, figsize=(13, 2.6 * nrows), squeeze=False)
        x = np.arange(len(dates))
        for ax, record in zip(axes.ravel(), records):
            for pol, colour in (("HH", "#b2182b"), ("HV", "#2166ac")):
                series = [0.0] + [
                    record["delta_by_date"].get(d, {}).get(pol, np.nan) for d in dates[1:]
                ]
                ax.plot(x, series, marker="o", markersize=3, color=colour, label=pol)
            ax.axhline(0, color="#999999", linewidth=0.6)
            ax.axhline(threshold_db, color="#bbbbbb", linewidth=0.5, linestyle="--")
            ax.axhline(-threshold_db, color="#bbbbbb", linewidth=0.5, linestyle="--")
            ax.axvspan(2.5, 3.5, color="#eeeeee", zorder=0)
            ax.set_title(f"{record['id']}  {record['area_km2']:.3f} km2  {record['sign']}", fontsize=8)
            ax.tick_params(labelsize=6)
            ax.set_xticks(x[::2])
            ax.set_xticklabels([d[5:] for d in dates[::2]], rotation=45, fontsize=5)
            ax.set_ylim(-8, 8)
            if ax is axes.ravel()[0]:
                ax.legend(fontsize=6)
        for ax in axes.ravel()[len(records):]:
            ax.axis("off")
        fig.suptitle(f"Patch time series, delta in dB versus {reference.date} (shaded: mission outage)",
                     fontsize=11)
        fig.tight_layout(rect=[0, 0.02, 1, 0.97])
        fig.savefig(INTERIM / f"patch_timeseries{tag}.png", dpi=130, bbox_inches="tight")
        plt.close(fig)

    # ---- sensitivity, reported not tuned -------------------------------------------------------
    print("\nWhy so few: |delta| at 60 m is small. Share of pixels above each threshold,")
    print("and share surviving the consecutive-date rule:")
    pooled = np.abs(np.concatenate([d[np.isfinite(d)].ravel() for d in delta["HV"]]))
    for threshold in (1.0, 1.5, 2.0, 3.0, 4.0):
        changed = np.logical_or.reduce([patches.changed_stack(delta[pol], threshold) & eligible for pol in POLS])
        persistent = patches.consecutive_any(changed, min_consecutive)
        print(f"  T={threshold:.1f} dB: changed {100 * changed.mean():6.3f}%  persistent {100 * persistent.mean():6.3f}%")

    print("\nSensitivity of the patch count (rows = threshold dB, columns = min area px):")
    cols = [10, 20, 40]
    print("    T     " + "  ".join(f"{c:>4d}px" for c in cols))
    for threshold in (1.0, 1.5, 2.0, 3.0, 4.0):
        counts = []
        for min_px in cols:
            _, n = detect(threshold, min_px)
            counts.append(n)
        marker = "  <- configured default" if abs(threshold - threshold_db) < 1e-9 else ""
        print(f"  {threshold:.1f}    " + "  ".join(f"{c:>6d}" for c in counts) + marker)

    print("\nNote: the coloured specks in the change map are sub-dB. A 3 dB persistent test finds nothing,")
    print("which is the honest answer at this threshold. Lowering T finds patches but also noise;")
    print("any patch reported at T < 2 dB must be checked against the optical imagery before use.")

    print(f"\nWrote patches.geojson ({count} features), patch_timeseries.csv, patch_preview.png, "
          f"patch_timeseries.png to {INTERIM.relative_to(REPO_ROOT)}")
    print(f"Wrote docs/patch_log.csv with {len(human)} empty human columns for the analyst.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
