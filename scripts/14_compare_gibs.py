"""Step 14 - one neutral comparison between our false colour and NASA's GIBS NISAR mosaic.

This is context, not calibration. The two images are not the same date: GIBS currently publishes
only a 3-day best-available mosaic (2026-11-12..14 at the time of writing), while our processed
series ends earlier. We log the numbers and one sentence, and we do not tune our recipe to match.

    python scripts/14_compare_gibs.py
"""

from __future__ import annotations

import colorsys
import io
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT  # noqa: E402

PLACE = "dead_sea_full"
GIBS = "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi"
LAYER = "NISAR_L2_Geocoded_Polarimetric_Covariance"
GIBS_DATE = "2026-11-13"
# (name, lon, lat): open water in the middle of the lake, and the dry eastern margin.
POINTS = [("lake", 35.50, 31.55), ("land", 35.62, 31.70)]


def get_map(bbox: tuple[float, float, float, float]) -> Image.Image:
    west, south, east, north = bbox
    query = {
        "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0", "LAYERS": LAYER,
        "CRS": "EPSG:3857", "BBOX": f"{west},{south},{east},{north}".replace(",", ","),
        "WIDTH": "900", "HEIGHT": "900", "FORMAT": "image/png", "TRANSPARENT": "true",
        "TIME": GIBS_DATE,
    }
    url = GIBS + "?" + urllib.parse.urlencode(query)
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read()
    return Image.open(io.BytesIO(payload)).convert("RGBA")


def sample_mean(image: Image.Image, lon: float, lat: float, bbox, radius: int = 6):
    west, south, east, north = bbox
    from pyproj import Transformer
    forward = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    x, y = forward.transform(lon, lat)
    width, height = image.size
    col = int((x - west) / (east - west) * width)
    row = int((north - y) / (north - south) * height)
    array = np.array(image)
    patch = array[max(0, row - radius):row + radius, max(0, col - radius):col + radius]
    if patch.size == 0:
        return None
    rgb = patch[..., :3].reshape(-1, 3)
    alpha = patch[..., 3].reshape(-1)
    rgb = rgb[alpha > 0]
    if rgb.size == 0:
        return None
    mean = rgb.mean(axis=0)
    hue = colorsys.rgb_to_hsv(*(mean / 255.0))[0] * 360.0
    return [round(float(v), 1) for v in mean] + [round(float(hue), 1)]


def main() -> int:
    from pyproj import Transformer
    outdir = REPO_ROOT / "web" / "data" / PLACE
    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    (south, west), (north, east) = manifest["bounds"]
    forward = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    x0, y0 = forward.transform(west, south)
    x1, y1 = forward.transform(east, north)
    bbox_3857 = (x0, y0, x1, y1)
    bbox_wms = (x0, y0, x1, y1)

    gibs = get_map(bbox_wms)

    rgb_layers = sorted([layer for layer in manifest["layers"] if layer["kind"] == "rgb"],
                        key=lambda layer: layer["date"])
    if not rgb_layers:
        print("no RGB layer to compare yet")
        return 1
    ours_layer = rgb_layers[-1]
    ours = Image.open(outdir / ours_layer["file"]).convert("RGBA")

    lines = [f"# GIBS comparison - {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}", "",
             f"GIBS layer `{LAYER}` on {GIBS_DATE}; our nearest RGB layer on {ours_layer['date']} "
             f"({ours_layer['series']}). Different dates, same geometry; context only.", "",
             "| source | region | mean R | mean G | mean B | hue deg |", "|---|---|---|---|---|---|"]
    for name, lon, lat in POINTS:
        gibs_mean = sample_mean(gibs, lon, lat, bbox_3857)
        ours_mean = sample_mean(ours, lon, lat, bbox_3857)
        for label, values in ((f"NASA GIBS {GIBS_DATE}", gibs_mean), (f"ours {ours_layer['date']}", ours_mean)):
            if values:
                lines.append(f"| {label} | {name} | {values[0]} | {values[1]} | {values[2]} | {values[3]} |")
    lines += ["", "One sentence: the two mosaics are not the same date and are not expected to match "
                  "pixel for pixel; the lake reads olive in our view while NASA's description says calm "
                  "water is blue, and the difference is not yet explained.", ""]
    (REPO_ROOT / "docs" / "GIBS_COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
