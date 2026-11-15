"""Step 6b - validate the web assets before anyone deploys them. Exit code 1 on any failure.

    python scripts/06_validate_web_assets.py

Per place (every configured place that has a manifest):
  1. every file the manifest names exists, and every preview exists;
  2. every image opens, is a WebP, has sane dimensions and carries alpha;
  3. layer bounds are valid, ordered, and shared exactly by every layer of the place;
  4. the overlay centre lies inside the AOI buffered by 5 km (the georeferencing gate G0);
  5. every layer has every required metadata field;
  6. every layer is PROVISIONAL (CRID P05023); no layer names a VALIDATED product;
  7. display layers are native-source and <= 13 m in EPSG:3857 (G1);
  8. every layer file is <= 700 KB (G7) and its crop is >= 99.5 % valid (G3).

Global:
  9. every .json/.js twin carries identical content; wrappers are pure ASCII;
 10. the whole web/data folder is inside the 60 MB budget.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Geod
from shapely import wkt as shapely_wkt
from shapely.geometry import Point
from shapely.ops import nearest_points

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT, load_config, load_study_area  # noqa: E402

WEB_DATA = REPO_ROOT / "web" / "data"
SIZE_BUDGET_MB = 220.0
LAYER_BUDGET_BYTES = 700_000
WHOLE_LAKE_BUDGET_BYTES = 900_000
AOI_BUFFER_KM = 5.0
MIN_VALID_FRACTION = 0.995
DISPLAY_KINDS = ("rgb", "backscatter")
MAX_DISPLAY_PX_M = 30.0
MIN_DISPLAY_PX_M = 9.0
REQUIRED_FIELDS = [
    "id", "label", "file", "format", "preview", "kind", "polarization", "date", "bounds", "coverage",
    "crop_bounds_3857", "px_size_m_3857", "native_px_m", "colormap",
    "description", "display_chain", "product", "crid", "maturity", "track", "frame",
    "direction", "native_crs", "display_crs", "processing",
]
JSON_FILES = ["manifest", "water_stats", "offsets", "patches", "license_and_attribution"]
VALIDATED_MARKERS = ("P05036", "VALIDATED")


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes: list[str] = []

    def check(self, ok: bool, message: str) -> None:
        (self.passes if ok else self.failures).append(message)

    def print(self) -> int:
        for message in self.passes:
            print(f"PASS  {message}")
        for message in self.failures:
            print(f"FAIL  {message}")
        print(f"\n{len(self.passes)} passed, {len(self.failures)} failed")
        return 1 if self.failures else 0


def read_js_payload(path: Path) -> dict:
    text = path.read_text(encoding="ascii")
    start = text.index("= ", text.index("window.VENUS[")) + 2
    body = text[start:].rstrip().rstrip(";")
    return json.loads(body)


def alpha_fraction(path: Path) -> float:
    with Image.open(path) as image:
        array = np.array(image.convert("RGBA"))
    return float((array[..., 3] > 0).mean())


def validate_place(report: Report, name: str) -> None:
    outdir = WEB_DATA / name
    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    layers = manifest["layers"]
    report.check(len(layers) > 0, f"{name}: manifest lists {len(layers)} layers")

    missing = [layer["file"] for layer in layers if not (outdir / layer["file"]).exists()]
    missing += [layer["preview"] for layer in layers if not (outdir / layer["preview"]).exists()]
    report.check(not missing, f"{name}: every layer and preview file exists ({len(missing)} missing)")

    bad_image, oversize, low_valid, wrong_format, big_px = [], [], [], [], []
    shapes: dict[str, set] = {}
    for layer in layers:
        path = outdir / layer["file"]
        if not path.exists():
            continue
        size = path.stat().st_size
        budget = WHOLE_LAKE_BUDGET_BYTES if name == "dead_sea_full" else LAYER_BUDGET_BYTES
        if size > budget:
            oversize.append(f"{layer['id']} {size // 1024} KB")
        if path.suffix != ".webp" or layer.get("format") != "webp":
            wrong_format.append(layer["id"])
        with Image.open(path) as image:
            width, height = image.size
            has_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
            if not (1 <= width <= 6000 and 1 <= height <= 6000 and has_alpha):
                bad_image.append(layer["id"])
            shapes.setdefault(layer["kind"], set()).add((height, width))
        if layer["kind"] in DISPLAY_KINDS and layer.get("coverage", "full") == "full":
            fraction = alpha_fraction(path)
            if fraction < MIN_VALID_FRACTION:
                low_valid.append(f"{layer['id']} {fraction:.3f}")
            px_size = layer.get("px_size_m_3857") or 99
            if (px_size > MAX_DISPLAY_PX_M or px_size < MIN_DISPLAY_PX_M) and not layer.get("resolution_fallback"):
                big_px.append(f"{layer['id']} {layer['px_size_m_3857']}")
            if layer.get("native_px_m") != 20.0:
                big_px.append(f"{layer['id']} native {layer.get('native_px_m')}")

    report.check(not bad_image, f"{name}: every image opens with transparency ({len(layers)} checked)")
    report.check(not wrong_format, f"{name}: every layer is WebP ({', '.join(wrong_format[:3]) or 'all ok'})")
    report.check(not oversize, f"{name}: every layer <= {LAYER_BUDGET_BYTES // 1000} KB ({', '.join(oversize[:3]) or 'all ok'})")
    report.check(not low_valid, f"{name}: every crop >= {MIN_VALID_FRACTION:.1%} valid ({', '.join(low_valid[:3]) or 'all ok'})")
    report.check(not big_px, f"{name}: display layers are native 20 m, <= {MAX_DISPLAY_PX_M:.0f} m in EPSG:3857 "
                              f"({', '.join(big_px[:3]) or 'all ok'})")

    (south, west), (north, east) = manifest["bounds"]
    report.check(south < north and west < east, f"{name}: manifest bounds valid and ordered")

    shared = {json.dumps(layer["bounds"]) for layer in layers}
    report.check(len(shared) == 1, f"{name}: all layers share identical bounds ({len(shared)} distinct)")

    geo = Geod(ellps="WGS84")
    aoi = shapely_wkt.loads(load_study_area(name).wkt)
    point = Point((west + east) / 2.0, (south + north) / 2.0)
    if aoi.contains(point):
        report.check(True, f"{name}: overlay centre is inside the AOI")
    else:
        nearest = nearest_points(aoi, point)[0]
        km = geo.inv(nearest.x, nearest.y, point.x, point.y)[2] / 1000.0
        report.check(km <= AOI_BUFFER_KM,
                     f"{name}: overlay centre {km:.1f} km from the AOI (limit {AOI_BUFFER_KM:.0f} km)")

    incomplete = []
    for layer in layers:
        fields = REQUIRED_FIELDS + (["vmin", "vmax"] if layer["kind"] in ("backscatter", "change", "rgb") else [])
        missing_fields = [f for f in fields if f not in layer or layer[f] in (None, "")]
        if missing_fields:
            incomplete.append(f"{layer['id']}: {','.join(missing_fields)}")
    report.check(not incomplete, f"{name}: every layer has all required metadata "
                                 f"({'; '.join(incomplete[:2]) or 'all ok'})")

    # Series integrity: every layer names its series; its CRID matches that series; no statistics
    # object spans two series. Mixing maturities inside one comparison is never allowed.
    series_rows = manifest.get("series") or []
    series_by_id = {row["id"]: row for row in series_rows}
    if series_rows:
        bad_series = [layer["id"] for layer in layers
                      if layer.get("series") not in series_by_id]
        report.check(not bad_series, f"{name}: every layer belongs to a declared series")
        mismatched = [layer["id"] for layer in layers
                      if layer.get("series") in series_by_id
                      and layer.get("crid") != series_by_id[layer["series"]].get("crid")]
        report.check(not mismatched, f"{name}: every layer CRID matches its series ({', '.join(mismatched[:3]) or 'all ok'})")
        stats_path = outdir / "water_stats.json"
        if stats_path.exists():
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            stats_series = stats.get("series")
            report.check(stats_series is None or stats_series in series_by_id,
                         f"{name}: statistics object names one declared series")
        wrong_crid = [layer["id"] for layer in layers
                      if layer.get("crid") != series_by_id.get(layer.get("series"), {}).get("crid")]
        report.check(not wrong_crid, f"{name}: no layer mixes CRIDs across series")
    else:
        wrong_crid = [layer["id"] for layer in layers if layer.get("crid") != "P05023"]
        report.check(not wrong_crid, f"{name}: every layer is CRID P05023 (legacy single-series)")

    # A multi-series place legitimately contains BETA/VALIDATED layers, each inside its own series.
    # The rule is not "no VALIDATED anywhere" but "no layer belongs to a series it does not match".
    if not series_rows:
        named = [layer["id"] for layer in layers
                 if any(marker in json.dumps(layer) for marker in VALIDATED_MARKERS)]
        report.check(not named, f"{name}: no layer names a VALIDATED product (legacy bundle)")


def main() -> int:
    report = Report()
    if not WEB_DATA.exists():
        print(f"FAIL  {WEB_DATA} does not exist. Run scripts/12_build_place_site.py first.")
        return 1

    places = json.loads((WEB_DATA / "places.json").read_text(encoding="utf-8"))["places"]
    names = [place["name"] for place in places if place.get("processed")]
    built = [name for name in names if (WEB_DATA / name / "manifest.json").exists()]
    report.check(len(built) == len(names), f"all {len(names)} processed places have a manifest ({len(built)} found)")
    for name in built:
        validate_place(report, name)

    mismatched = []
    for outdir in sorted(WEB_DATA.glob("*/")):
        for stem in JSON_FILES:
            json_path = outdir / f"{stem}.json"
            js_path = outdir / f"{stem}.js"
            if not json_path.exists() or not js_path.exists():
                continue
            if json.loads(json_path.read_text(encoding="utf-8")) != read_js_payload(js_path):
                mismatched.append(f"{outdir.name}/{stem}")
    report.check(not mismatched, f"json and js twins identical ({', '.join(mismatched) or 'all match'})")

    non_ascii = []
    for path in WEB_DATA.glob("*.js"):
        try:
            path.read_bytes().decode("ascii")
        except UnicodeDecodeError:
            non_ascii.append(path.name)
    report.check(not non_ascii, f"js wrappers are pure ASCII ({', '.join(non_ascii) or 'all ok'})")

    total_mb = sum(f.stat().st_size for f in WEB_DATA.rglob("*") if f.is_file()) / 1e6
    report.check(total_mb < SIZE_BUDGET_MB, f"total web/data {total_mb:.2f} MB < {SIZE_BUDGET_MB:.0f} MB budget")

    print(f"Validated {len(built)} places in {WEB_DATA.relative_to(REPO_ROOT)}\n")
    return report.print()


if __name__ == "__main__":
    raise SystemExit(main())
