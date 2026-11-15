"""Step 19 - add new series to an existing place WITHOUT rebuilding what is already there (v4).

Reads each processed place's manifest, finds cached acquisitions that no layer represents yet, groups
them into series (maturity, CRID, track, direction, polarizations) and adds display layers only:

* HV-only series get the HV grey layer (no RGB), as R4 requires for new dual-pol series;
* HH-only series keep the single-pol ramp and a grey layer;
* dual-pol series that already have both channels get the RGB plus the two grey layers;
* a date whose frames do not fully cover the shared rectangle is marked ``coverage: partial`` and is
  shown, never used in a statistic (there are no statistics for these series anyway: BETA and short
  VALIDATED are browse-only).

Existing layers, water_stats and offsets are not touched. The shared display rectangle and pixel size
come from the manifest, so new layers align with old ones.

    python scripts/19_add_series_site.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import display as dx, webexport as wx  # noqa: E402
from venus.config import REPO_ROOT  # noqa: E402
from venus.mosaic import mosaic_items  # noqa: E402

SUBSETS = REPO_ROOT / "data" / "raw" / "subsets"
WEB_DATA = REPO_ROOT / "web" / "data"


def series_key(meta) -> tuple:
    pols = "".join(sorted(set(str(meta.get("polarizations", "")).split("+"))))
    return (meta.get("maturity"), meta.get("crid"), int(meta.get("track", 0)),
            str(meta.get("direction", "")), pols)


def series_id(key) -> str:
    maturity, crid, track, direction, pols = key
    return f"{track}-{str(direction)[:4].upper()}-{crid}-{pols}"


def load_new(place: str, manifest: dict) -> dict:
    covered = {(layer.get("series"), layer["date"]) for layer in manifest["layers"]}
    by_date = defaultdict(list)
    for sidecar in sorted((SUBSETS / place).glob("*.json")):
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        key = series_key(meta)
        if (series_id(key), meta["acquisition_date"]) in covered:
            continue
        base = sidecar.with_suffix("")
        arrays = {}
        for pol in ("HH", "HV"):
            path = Path(f"{base}_{pol}.npy")
            if path.exists():
                array = np.load(path)
                if array.size:
                    arrays[pol] = array
        if not arrays:
            continue
        mask_path = Path(f"{base}_mask.npy")
        by_date[(meta["acquisition_date"], key)].append({
            "meta": meta, "stem": sidecar.stem, "arrays": arrays,
            "mask": np.load(mask_path) if mask_path.exists() else None,
            "x": np.array(meta["x"], dtype="float64"), "y": np.array(meta["y"], dtype="float64"),
        })
    groups = defaultdict(list)
    for (day, key), items in by_date.items():
        card = mosaic_items(items)
        card["day"] = day
        card["key"] = key
        groups[series_id(key)].append(card)
    for cards in groups.values():
        cards.sort(key=lambda card: card["day"])
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    names = ([args.aoi] if args.aoi else
             [p["name"] for p in json.loads((WEB_DATA / "places.json").read_text(encoding="utf-8"))["places"]
              if p.get("processed")])
    for name in names:
        manifest_path = WEB_DATA / name / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing = manifest["layers"]
        if not existing:
            continue
        # Legacy bundles (v2) have layers but no series list. Give the existing layers a synthetic
        # legacy series so the app keeps showing them next to the new ones.
        if not manifest.get("series"):
            legacy_id = (f"{existing[0].get('track')}-{str(existing[0].get('direction'))[:4].upper()}-"
                         f"{existing[0].get('crid')}-"
                         f"{''.join(sorted(set(p for layer in existing for p in str(layer.get('polarization', '')).split('+') if p)))}")
            dates = sorted({layer["date"] for layer in existing})
            for layer in existing:
                layer.setdefault("series", legacy_id)
                layer.setdefault("coverage", "full")
            manifest["series"] = [{
                "id": legacy_id, "label": f"{manifest.get('maturity')} - track {manifest.get('track')}",
                "maturity": manifest.get("maturity"), "crid": manifest.get("crid"),
                "track": manifest.get("track"), "direction": manifest.get("direction"),
                "polarizations": manifest.get("polarizations", []), "dates": dates,
                "analysis": True, "coverage": {day: "full" for day in dates},
                "source": "built before the series model; treated as one PROVISIONAL series",
            }]
            manifest["primary_series"] = legacy_id
        crop = existing[0]["crop_bounds_3857"]
        px = existing[0]["px_size_m_3857"]
        bounds = manifest["bounds"]
        disp_t, disp_w, disp_h = dx.grid_for_rect(tuple(crop), px)
        budget = 900_000 if name == "dead_sea_full" else 700_000
        groups = load_new(name, manifest)
        if not groups:
            print(f"{name:16s} nothing new")
            continue
        added = 0
        for sid, cards in groups.items():
            key = cards[0]["key"]
            # If the same (maturity, CRID, track, direction) series already exists, extend it rather
            # than opening a second lane just because the fetched polarization is narrower.
            for row in manifest["series"]:
                if (row.get("maturity"), row.get("crid"), row.get("track"),
                        row.get("direction")) == key[:4]:
                    sid = row["id"]
                    break
            src_crs = cards[0]["meta"].get("crs_wkt") or f"EPSG:{cards[0]['meta']['epsg']}"
            native_px = float(cards[0]["meta"]["pixel_spacing_m"])
            pols = sorted(set.intersection(*[set(card["arrays"]) for card in cards]))
            if not pols:
                continue
            # pooled limits per polarization over this series only
            limits = {}
            for pol in pols:
                pooled = []
                for card in cards:
                    valid = dx.valid_native(card["arrays"][pol], card["mask"])
                    power = card["arrays"][pol][valid & (card["arrays"][pol] > 0)]
                    if power.size:
                        pooled.append(10 * np.log10(power))
                values = np.concatenate(pooled)
                limits[pol] = tuple(float(v) for v in np.percentile(values, [2, 98]))
            display_chain = [
                f"{native_px:.0f} m native power ({'/'.join(pols)} only for this series)",
                "invalid -> NaN (mask 0/255 or non-finite)",
                "mosaic of the frames present for this date (native UTM, mean where both valid)",
                f"reprojected once to EPSG:3857 at {px} m, bilinear on linear power",
                "dB stretch clipped at this series' pooled 2nd/98th percentile",
                "8 px inward edge feather (display only)",
                "WebP lossy with alpha; NO statistics are computed from this series",
            ]
            dates = [card["day"] for card in cards]
            coverage = {}
            for card in cards:
                transform = wx.grid_transform(np.asarray(card["x"]), np.asarray(card["y"]), native_px)
                valid = None
                for pol in pols:
                    v = dx.valid_native(card["arrays"][pol], card["mask"])
                    valid = v if valid is None else (valid & v)
                grid_valid = dx.warp_valid(valid, transform, src_crs, disp_t, disp_w, disp_h)
                fraction = float(grid_valid.mean())
                coverage[card["day"]] = "full" if fraction >= 0.99 else "partial"

                def save(rgba, filename, **fields):
                    nonlocal added
                    image = Image.fromarray(np.ascontiguousarray(rgba), mode="RGBA")
                    size = 0
                    for quality in (82, 75, 68):
                        size = dx.save_webp(image, WEB_DATA / name / "layers" / filename, quality=quality)
                        if size <= budget:
                            break
                    dx.save_preview(image, WEB_DATA / name / "layers" /
                                    (Path(filename).stem + "_preview.webp"))
                    manifest["layers"].append({
                        "file": f"layers/{filename}", "format": "webp",
                        "preview": f"layers/{Path(filename).stem}_preview.webp",
                        "native_px_m": native_px, "px_size_m_3857": px, "bounds": bounds,
                        "crop_bounds_3857": crop, "display_chain": display_chain,
                        "series": sid, "coverage": coverage[card["day"]],
                        "product": "NISAR L2 GCOV", "crid": key[1], "maturity": key[0],
                        "track": key[2], "frame": card["meta"].get("frame"), "direction": key[3],
                        "native_crs": f"EPSG:{card['meta']['epsg']}", "display_crs": wx.CRS_WEB,
                        "offset_applied_db": 0.0, "display_multilook": 1,
                        **fields,
                    })
                    added += 1

                for pol in pols:
                    power, weight = dx.warp_nansafe(card["arrays"][pol], valid, transform, src_crs,
                                                    disp_t, disp_w, disp_h)
                    vmin, vmax = limits[pol]
                    db = dx.single_pol_db(power, vmin, vmax, weight >= 0.5)
                    rgba = np.array(wx.grey_rgba(db, vmin, vmax))
                    save(dx.feather_alpha(rgba, 8), f"backscatter_{pol}_{card['day']}.webp",
                         id=f"{sid}_backscatter_{pol}_{card['day']}", kind="backscatter",
                         label=f"Backscatter {pol} {card['day']}", polarization=pol, date=card["day"],
                         vmin=round(vmin, 2), vmax=round(vmax, 2),
                         colormap="grey: dark = smooth (water), bright = rough",
                         description=f"Gamma-0 backscatter {pol} on {card['day']} ({key[0]} series).",
                         processing=display_chain)
                if "HH" in pols and "HV" not in pols:
                    power, weight = dx.warp_nansafe(card["arrays"]["HH"], valid, transform, src_crs,
                                                    disp_t, disp_w, disp_h)
                    vmin, vmax = limits["HH"]
                    db = dx.single_pol_db(power, vmin, vmax, weight >= 0.5)
                    rgb = dx.single_pol_ramp(db, vmin, vmax)
                    rgba = dx.rgba_from_rgb(rgb, weight >= 0.5)
                    save(dx.feather_alpha(rgba, 8), f"rgb_HH_{card['day']}.webp",
                         id=f"{sid}_rgb_HH_{card['day']}", kind="rgb",
                         label=f"False colour HH {card['day']}", polarization="HH", date=card["day"],
                         vmin=round(vmin, 2), vmax=round(vmax, 2),
                         colormap="single-polarization ramp: blue (low) to green to orange to yellow (high)",
                         description=f"Single-polarization false colour on {card['day']} ({key[0]} series).",
                         processing=display_chain)
            existing_row = next((row for row in manifest["series"] if row["id"] == sid), None)
            if existing_row:
                existing_row["dates"] = sorted(set(existing_row.get("dates", [])) | set(dates))
                existing_row.setdefault("coverage", {}).update(coverage)
                existed = True
            else:
                manifest["series"].append({
                    "id": sid, "label": f"{key[0]} - track {key[2]} {str(key[3]).lower()}",
                    "maturity": key[0], "crid": key[1], "track": key[2], "direction": key[3],
                    "polarizations": pols, "dates": dates, "analysis": False,
                    "coverage": coverage,
                    "polarization_note": "HV only" if pols == ["HV"] else ("HH only" if pols == ["HH"] else ""),
                    "source": "ASF DAAC NISAR L2 GCOV; browse-only series, no statistics",
                })
                existed = False
            print(f"{name:16s} +{len(cards)} dates  {sid}  coverage {list(coverage.values())}"
                  + ("  (extended)" if existed else ""))
        manifest["generated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wx.write_json(WEB_DATA / name / "manifest.json", manifest)
        wx.write_js(WEB_DATA / name / "manifest.js", "place_manifest", manifest)
        print(f"{name:16s} added {added} layers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
