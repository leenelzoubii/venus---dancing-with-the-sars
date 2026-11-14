"""Turning processed radar windows into small, web-ready static assets.

The app must load only pre-computed files: no backend, no API keys, no live processing. This module
is the bridge between the analysis grid (EPSG:32636, 20 m UTM) and the browser (EPSG:3857 images over
a slippy map).

Two things matter scientifically:

* **Georeferencing.** A PNG is a plain image, so the manifest carries the WGS84 box that tells Leaflet
  where to put it. That box is derived from the product's own coordinate vectors, not from the AOI
  polygon, and it is widened by half a pixel because NISAR's convention is pixel *centres*.
* **Stated stretch.** Every image ships with the dB values that map to black and to white, and those
  limits are shared by every date, so a colour difference can never be mistaken for a date difference.

Reprojection note: the source is a projected UTM grid, so its footprint is a *trapezoid* in lon/lat.
We resample into a north-up Web Mercator rectangle using ``rasterio.warp.reproject``, which means the
image Leaflet stretches over the bounds is geometrically correct rather than approximately correct.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

# Change ramp: blue (less echo later) -> light -> orange (more echo later). Both ends are chosen for
# colour-blind safety and for print: they differ in lightness as well as in hue.
CHANGE_STOPS = [
    (0.0, (59, 130, 246)),    # #3B82F6
    (0.5, (217, 222, 232)),   # #D9DEE8
    (1.0, (245, 158, 11)),    # #F59E0B
]

CRS_EPSG4326 = "EPSG:4326"
CRS_EPSG3857 = "EPSG:3857"

WATER_RGB = (34, 211, 238)   # cyan, translucent
BAND_RGB = (250, 204, 21)    # amber: pixels that flip inside the uncertainty band


def _ramp(normalised: np.ndarray, stops=CHANGE_STOPS) -> np.ndarray:
    """Map 0..1 to RGB with linear interpolation between stops."""
    t = np.clip(normalised, 0.0, 1.0)
    out = np.zeros((*t.shape, 3), dtype="float32")
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        span = max(p1 - p0, 1e-9)
        mask = (t >= p0) & (t <= p1)
        if not mask.any():
            continue
        local = (t[mask] - p0) / span
        for channel in range(3):
            out[..., channel][mask] = c0[channel] + local * (c1[channel] - c0[channel])
    return out


def grey_rgba(values: np.ndarray, vmin: float, vmax: float) -> Image.Image:
    """Greyscale backscatter; NaN becomes transparent rather than black."""
    span = max(float(vmax) - float(vmin), 1e-6)
    scaled = np.clip((values - vmin) / span, 0.0, 1.0) * 255.0
    valid = np.isfinite(values)
    grey = np.where(valid, scaled, 0.0).astype("uint8")
    rgba = np.zeros((*values.shape, 4), dtype="uint8")
    rgba[..., 0] = grey
    rgba[..., 1] = grey
    rgba[..., 2] = grey
    rgba[..., 3] = np.where(valid, 255, 0).astype("uint8")
    return Image.fromarray(rgba, mode="RGBA")


def change_rgba(delta_db: np.ndarray, limit_db: float, neutral_below_db: float = 0.25) -> Image.Image:
    """Diverging change image; changes smaller than ``neutral_below_db`` are made transparent."""
    valid = np.isfinite(delta_db)
    normalised = (np.clip(np.nan_to_num(delta_db, nan=0.0), -limit_db, limit_db) + limit_db) / (
        2 * limit_db
    )
    rgb = _ramp(normalised)
    alpha = np.where(valid, 210, 0).astype("uint8")
    alpha[valid & (np.abs(np.nan_to_num(delta_db)) < neutral_below_db)] = 0
    rgba = np.zeros((*delta_db.shape, 4), dtype="uint8")
    rgba[..., :3] = rgb.astype("uint8")
    rgba[..., 3] = alpha
    return Image.fromarray(rgba, mode="RGBA")


def mask_palette(mask: np.ndarray, rgb: tuple[int, int, int], alpha: int = 170) -> Image.Image:
    """Quantise a boolean mask to a palette PNG: two colours and transparency, a few KB on disk.

    Palette mode is used because a water mask is one bit of information; storing it as 32-bit RGBA
    would cost sixteen times more for the same picture.
    """
    index = np.where(np.asarray(mask, dtype=bool), 1, 0).astype("uint8")
    image = Image.fromarray(index, mode="P")
    palette = [0, 0, 0, *rgb]
    image.putpalette(palette + [0] * (768 - len(palette)))
    # Index 0 is the transparent background; index 1 carries the mask colour.
    image.info["transparency"] = 0
    image.info["alpha_level"] = alpha
    return image


def lonlat_bounds(x: np.ndarray, y: np.ndarray, pixel_m: float, crs_wkt: str) -> list[float]:
    """``[south, west, north, east]`` for one window, from the product's own coordinate vectors.

    ``x``/``y`` are pixel *centres*, so half a pixel is added on each side to cover the full footprint.
    All four corners are reprojected because a projected rectangle is not a lon/lat rectangle, and the
    enclosing box is what Leaflet can use.
    """
    from pyproj import CRS, Transformer

    inverse = Transformer.from_crs(CRS.from_user_input(crs_wkt), CRS.from_epsg(4326), always_xy=True)
    half = pixel_m / 2.0
    x0, x1 = float(x[0]) - half, float(x[-1]) + half
    y0, y1 = float(y[0]) + half, float(y[-1]) - half
    lons, lats = inverse.transform([x0, x1, x1, x0], [y0, y0, y1, y1])
    return [min(lats), min(lons), max(lats), max(lons)]


def mercator_bbox(bounds: list[float]) -> tuple[float, float, float, float]:
    """WGS84 ``[s,w,n,e]`` to EPSG:3857 ``(left, bottom, right, top)``."""
    from pyproj import CRS, Transformer

    forward = Transformer.from_crs(CRS_EPSG4326, CRS_EPSG3857, always_xy=True)
    left, bottom = forward.transform(bounds[1], bounds[0])
    right, top = forward.transform(bounds[3], bounds[2])
    return left, bottom, right, top


def reproject(
    array: np.ndarray,
    src_transform,
    src_crs: str,
    dst_transform,
    dst_crs: str,
    dst_shape: tuple[int, int],
    mask: bool = False,
) -> np.ndarray:
    """Resample one band into a north-up destination grid.

    Bilinear for continuous dB fields, nearest for masks: interpolating a mask would invent water
    fractions that cannot exist.
    """
    from rasterio.warp import Resampling, reproject as warp_reproject

    if mask:
        source = np.asarray(array, dtype="uint8")
        destination = np.zeros(dst_shape, dtype="uint8")
        warp_reproject(
            source=source, destination=destination, src_transform=src_transform, src_crs=src_crs,
            dst_transform=dst_transform, dst_crs=dst_crs,
            resampling=Resampling.nearest, src_nodata=0, dst_nodata=0,
        )
        return destination.astype(bool)

    source = np.asarray(array, dtype="float32")
    destination = np.full(dst_shape, np.nan, dtype="float32")
    warp_reproject(
        source=source, destination=destination, src_transform=src_transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan,
    )
    return destination


def write_js_wrapper(path, variable: str, payload: Any) -> None:
    """Write JSON as a script that assigns a global, so the app works from ``file://``.

    Browsers refuse ``fetch()`` of a local file, but a <script> tag is always allowed. The payload is
    escaped to pure ASCII (``\\uXXXX``) so the file cannot break on an encoding mismatch.
    """
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    path.write_text(f"window.{variable} = {text};\n", encoding="ascii")


def write_json(path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=True), encoding="utf-8")


@dataclass
class Layer:
    """One exported image plus the metadata a reader needs to interpret it."""

    id: str
    label: str
    file: str
    kind: str
    polarization: str
    date: str
    bounds: list[list[float]]
    vmin: float | None = None
    vmax: float | None = None
    colormap: str = ""
    description: str = ""
    extra: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "label": self.label,
            "file": self.file,
            "kind": self.kind,
            "polarization": self.polarization,
            "date": self.date,
            "bounds": self.bounds,
            "colormap": self.colormap,
            "description": self.description,
        }
        if self.vmin is not None:
            payload["vmin"] = round(float(self.vmin), 2)
        if self.vmax is not None:
            payload["vmax"] = round(float(self.vmax), 2)
        if self.extra:
            payload.update(self.extra)
        return payload
