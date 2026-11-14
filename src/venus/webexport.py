"""Turn processed NISAR windows into small, web-ready static assets.

The web app must load only pre-computed files: no backend, no API keys, no live processing. So this
module is the bridge between ``data/raw/subsets`` (float arrays in UTM metres) and ``web/assets``
(8-bit PNG overlays + a manifest that tells the app where to put them).

Two things matter scientifically:

* **Georeferencing.** The PNG is a plain image, so the manifest carries a WGS84 bounding box derived
  from the product's own coordinate vectors (not from the AOI polygon), which is what Leaflet needs.
* **Stated stretch.** Every image ships with the dB values that map to black and to white, so the
  legend is honest and the colours cannot be misread.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# Colour-blind-safe diverging ramp for the change layer, as 8-bit RGB stops:
# deep blue (darker later) -> pale -> deep red (brighter later).
DIVERGING_STOPS = [
    (0.00, (49, 54, 149)),
    (0.25, (116, 173, 209)),
    (0.50, (247, 247, 247)),
    (0.75, (244, 109, 67)),
    (1.00, (165, 0, 38)),
]


def _ramp(normalised: np.ndarray) -> np.ndarray:
    """Map 0..1 to RGB using the diverging stops above (no matplotlib needed at render time)."""
    t = np.clip(normalised, 0.0, 1.0)
    out = np.zeros((*t.shape, 3), dtype="float32")
    stops = DIVERGING_STOPS
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        span = p1 - p0
        mask = (t >= p0) & (t <= p1)
        if not mask.any():
            continue
        local = (t[mask] - p0) / span
        for channel in range(3):
            out[..., channel][mask] = c0[channel] + local * (c1[channel] - c0[channel])
    return out


def render_grey(db: np.ndarray, vmin: float, vmax: float) -> Image.Image:
    """Greyscale backscatter overlay; NaN pixels become transparent, not black."""
    span = max(vmax - vmin, 1e-6)
    scaled = np.clip((db - vmin) / span, 0.0, 1.0) * 255.0
    valid = np.isfinite(db)
    grey = np.where(valid, scaled, 0.0).astype("uint8")
    rgba = np.zeros((*db.shape, 4), dtype="uint8")
    rgba[..., 0] = grey
    rgba[..., 1] = grey
    rgba[..., 2] = grey
    rgba[..., 3] = np.where(valid, 255, 0).astype("uint8")
    return Image.fromarray(rgba, mode="RGBA")


def render_change(diff_db: np.ndarray, limit_db: float, transparent_below_db: float = 0.35) -> Image.Image:
    """Diverging change overlay; near-zero change is made transparent so the imagery shows through."""
    valid = np.isfinite(diff_db)
    normalised = (np.clip(diff_db, -limit_db, limit_db) + limit_db) / (2 * limit_db)
    rgb = _ramp(np.nan_to_num(normalised, nan=0.5))
    alpha = np.where(valid, 255, 0).astype("uint8")
    faint = valid & (np.abs(np.nan_to_num(diff_db)) < transparent_below_db)
    alpha[faint] = 0
    rgba = np.zeros((*diff_db.shape, 4), dtype="uint8")
    rgba[..., :3] = rgb.astype("uint8")
    rgba[..., 3] = alpha
    return Image.fromarray(rgba, mode="RGBA")


def lon_lat_bounds(card: dict[str, Any], pixel_m: float) -> list[float]:
    """Leaflet bounds ``[south, west, north, east]`` for one subset, from the product's coordinates.

    ``x``/``y`` are pixel **centres**, so we add half a pixel on each side to cover the full pixel
    footprint. All four corners are reprojected because a projected rectangle is not a lon/lat
    rectangle, and we take the enclosing box.
    """
    from pyproj import CRS, Transformer

    crs = CRS.from_user_input(card["crs_wkt"])
    inv = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)

    half = pixel_m / 2.0
    x0, x1 = float(card["x"][0]) - half, float(card["x"][-1]) + half
    y0, y1 = float(card["y"][0]) + half, float(card["y"][-1]) - half

    xs = [x0, x1, x1, x0]
    ys = [y0, y0, y1, y1]
    lons, lats = inv.transform(xs, ys)
    return [min(lats), min(lons), max(lats), max(lons)]


@dataclass
class Layer:
    """One PNG plus the numbers its legend needs."""

    png: str
    vmin: float
    vmax: float
    water_km2: float | None = None
    water_threshold_db: float | None = None
    water_low_km2: float | None = None
    water_high_km2: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest with stable ordering so diffs between runs are readable."""
    path.write_text(json.dumps(manifest, indent=1, sort_keys=False), encoding="utf-8")
