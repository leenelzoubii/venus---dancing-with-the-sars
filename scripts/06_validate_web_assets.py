"""Step 6b - validate the web assets before anyone deploys them. Exit code 1 on any failure.

    python scripts/06_validate_web_assets.py

Checks:
  1. every file the manifest names exists;
  2. every PNG opens, has sane dimensions, and carries an alpha channel or a transparency index;
  3. layer bounds are valid, ordered, and inside a sane box around the AOI;
  4. each .js wrapper carries exactly the same content as its .json twin;
  5. the whole web/data folder is under the size budget;
  6. every layer has every required metadata field;
  7. the .js wrappers are pure ASCII (non-ASCII is escaped as \\uXXXX);
  8. every layer is the PROVISIONAL product (CRID P05023); no layer names a VALIDATED product.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT  # noqa: E402

WEB_DATA = REPO_ROOT / "web" / "data"
SIZE_BUDGET_MB = 30.0
LON_RANGE = (35.40, 35.70)
LAT_RANGE = (31.30, 31.60)
REQUIRED_FIELDS = [
    "id", "label", "file", "kind", "polarization", "date", "bounds", "colormap", "description",
    "product", "crid", "maturity", "track", "frame", "direction", "native_crs", "display_crs", "processing",
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


def main() -> int:
    report = Report()
    if not WEB_DATA.exists():
        print(f"FAIL  {WEB_DATA} does not exist. Run scripts/05_export_web_assets.py first.")
        return 1

    manifest_path = WEB_DATA / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layers = manifest["layers"]
    report.check(len(layers) > 0, f"manifest lists {len(layers)} layers")

    # 1. files named by the manifest exist
    missing = [layer["file"] for layer in layers if not (WEB_DATA / layer["file"]).exists()]
    report.check(not missing, f"every layer file exists ({len(layers) - len(missing)}/{len(layers)})")

    # 2. PNG sanity
    shapes: dict[str, set] = {"backscatter": set(), "change": set(), "water": set(), "band": set()}
    bad_png = []
    for layer in layers:
        path = WEB_DATA / layer["file"]
        if not path.exists():
            continue
        with Image.open(path) as image:
            width, height = image.size
            has_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
            if not (1 <= width <= 4000 and 1 <= height <= 4000 and has_alpha):
                bad_png.append(layer["file"])
            shapes.setdefault(layer["kind"], set()).add((height, width))
    report.check(not bad_png, f"every PNG has sane size and transparency ({', '.join(bad_png) or 'all ok'})")
    for kind, values in shapes.items():
        if values:
            report.check(len(values) == 1, f"all {kind} layers share one pixel grid {sorted(values)}")

    # 3. bounds
    bad_bounds = []
    for layer in layers:
        (south, west), (north, east) = layer["bounds"]
        ok = (
            south < north and west < east
            and LAT_RANGE[0] <= south and north <= LAT_RANGE[1]
            and LON_RANGE[0] <= west and east <= LON_RANGE[1]
        )
        if not ok:
            bad_bounds.append(layer["id"])
    report.check(not bad_bounds, f"all layer bounds valid and inside lon {LON_RANGE} lat {LAT_RANGE} "
                                 f"({', '.join(bad_bounds) or 'all ok'})")

    # 4. json and js carry identical content
    mismatched = []
    for stem in JSON_FILES:
        json_path = WEB_DATA / f"{stem}.json"
        js_path = WEB_DATA / f"{stem}.js"
        if not json_path.exists() or not js_path.exists():
            mismatched.append(f"{stem} (missing)")
            continue
        if json.loads(json_path.read_text(encoding="utf-8")) != read_js_payload(js_path):
            mismatched.append(stem)
    report.check(not mismatched, f"json and js twins identical ({', '.join(mismatched) or 'all 5 match'})")

    # 5. size budget
    total_mb = sum(f.stat().st_size for f in WEB_DATA.rglob("*") if f.is_file()) / 1e6
    report.check(total_mb < SIZE_BUDGET_MB, f"total web/data {total_mb:.2f} MB < {SIZE_BUDGET_MB:.0f} MB budget")

    # 6. required metadata
    incomplete = []
    for layer in layers:
        missing_fields = [f for f in REQUIRED_FIELDS if f not in layer or layer[f] in (None, "")]
        if missing_fields:
            incomplete.append(f"{layer['id']}: {','.join(missing_fields)}")
    report.check(not incomplete, f"every layer has all required metadata ({'; '.join(incomplete[:3]) or 'all ok'})")

    # 7. ASCII-only js wrappers
    non_ascii = []
    for path in WEB_DATA.glob("*.js"):
        try:
            path.read_bytes().decode("ascii")
        except UnicodeDecodeError:
            non_ascii.append(path.name)
    report.check(not non_ascii, f"js wrappers are pure ASCII ({', '.join(non_ascii) or 'all ok'})")

    # 8. provisional only, no validated product named in any layer
    wrong_crid = [layer["id"] for layer in layers if layer.get("crid") != "P05023"]
    report.check(not wrong_crid, f"every layer is CRID P05023 ({', '.join(wrong_crid) or 'all ok'})")
    named = []
    for layer in layers:
        text = json.dumps(layer)
        if any(marker in text for marker in VALIDATED_MARKERS):
            named.append(layer["id"])
    report.check(not named, f"no layer names a VALIDATED product ({', '.join(named) or 'none'})")

    print(f"Validated {len(layers)} layers in {WEB_DATA.relative_to(REPO_ROOT)}\n")
    return report.print()


if __name__ == "__main__":
    raise SystemExit(main())
