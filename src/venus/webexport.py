"""Turning the analysis grids into small, web-ready static assets.

The app must load only pre-computed files: no backend, no API keys, no live processing. This module
is the bridge between the analysis grid (EPSG:32636, UTM metres) and the browser, which draws images
over a Web Mercator (EPSG:3857) slippy map.

Scientific points that matter here:

* **Pixel convention.** NISAR coordinates are pixel *centres*, so a pixel's footprint extends half a
  pixel either side. :func:`grid_transform` builds the affine from the outer edges, not the centres.
* **Reprojection.** The UTM window is a rotated-looking trapezoid in lon/lat. We resample it into a
  north-up Web Mercator rectangle so that Leaflet's image overlay is geometrically exact.
  Continuous dB fields use bilinear resampling; masks use nearest, because interpolating a water
  mask would invent fractional water that cannot exist.
* **Fixed scales.** Every date of a layer type shares one colour limit, so a colour difference can
  never be read as a date difference. The limits are written into the manifest.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from affine import Affine
from PIL import Image

CRS_NATIVE = "EPSG:32636"
CRS_WEB = "EPSG:3857"
CRS_WGS84 = "EPSG:4326"

# Change ramp, colour-blind safe: blue (less echo later) -> light -> orange (more echo later).
CHANGE_STOPS = [
    (0.0, (0x3B, 0x82, 0xF6)),   # #3B82F6
    (0.5, (0xD9, 0xDE, 0xE8)),   # #D9DEE8
    (1.0, (0xF5, 0x9E, 0x0B)),   # #F59E0B
]

WATER_RGB = (0x22, 0xD3, 0xEE)   # cyan, drawn translucent
BAND_RGB = (0xFA, 0xCC, 0x15)    # amber: pixels that flip inside the +/-1.5 dB band
WATER_ALPHA = 170
BAND_ALPHA = 200


def ramp(normalised: np.ndarray, stops=CHANGE_STOPS) -> np.ndarray:
    """Map values in 0..1 to RGB by linear interpolation between the colour stops."""
    t = np.clip(np.asarray(normalised, dtype="float64"), 0.0, 1.0)
    out = np.zeros((*t.shape, 3), dtype="float64")
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        mask = (t >= p0) & (t <= p1)
        if not mask.any():
            continue
        local = (t[mask] - p0) / max(p1 - p0, 1e-12)
        for channel in range(3):
            out[..., channel][mask] = c0[channel] + local * (c1[channel] - c0[channel])
    return out


def grey_rgba(values: np.ndarray, vmin: float, vmax: float) -> Image.Image:
    """Greyscale backscatter. NaN pixels are fully transparent, never black."""
    span = max(float(vmax) - float(vmin), 1e-6)
    scaled = np.clip((np.asarray(values, dtype="float64") - vmin) / span, 0.0, 1.0) * 255.0
    valid = np.isfinite(values)
    grey = np.where(valid, scaled, 0.0).astype("uint8")
    rgba = np.zeros((*np.shape(values), 4), dtype="uint8")
    rgba[..., 0:3] = grey[..., None]
    rgba[..., 3] = np.where(valid, 255, 0).astype("uint8")
    return Image.fromarray(rgba, mode="RGBA")


def change_rgba(delta_db: np.ndarray, limit_db: float, neutral_below_db: float = 0.25) -> Image.Image:
    """Diverging change image. NaN is transparent; |change| below ``neutral_below_db`` is too."""
    delta = np.asarray(delta_db, dtype="float64")
    valid = np.isfinite(delta)
    normalised = (np.clip(np.nan_to_num(delta), -limit_db, limit_db) + limit_db) / (2 * limit_db)
    rgb = ramp(normalised)
    alpha = np.where(valid, 215, 0).astype("uint8")
    alpha[valid & (np.abs(np.nan_to_num(delta)) < neutral_below_db)] = 0
    rgba = np.zeros((*delta.shape, 4), dtype="uint8")
    rgba[..., :3] = np.round(rgb).astype("uint8")
    rgba[..., 3] = alpha
    return Image.fromarray(rgba, mode="RGBA")


def mask_palette(mask: np.ndarray, rgb: tuple[int, int, int], alpha: int) -> Image.Image:
    """A boolean mask as a palette PNG: index 0 fully transparent, index 1 a translucent colour.

    Palette mode keeps a one-bit picture to a few kilobytes, where RGBA would cost sixteen times more.
    """
    index = np.asarray(mask, dtype=bool).astype("uint8")
    image = Image.fromarray(index, mode="P")
    palette = [0, 0, 0, *rgb]
    image.putpalette(palette + [0] * (768 - len(palette)))
    image.info["transparency"] = bytes([0, alpha])
    return image


def save_png(image: Image.Image, path) -> int:
    """Write an optimised PNG and return its size in bytes."""
    image.save(path, format="PNG", optimize=True)
    return path.stat().st_size


def grid_transform(x: np.ndarray, y: np.ndarray, pixel_m: float) -> Affine:
    """Affine transform of a grid whose ``x``/``y`` are pixel centres, from the outer edges.

    Half a pixel is removed from the first centre so the transform points at the top-left corner of
    the first pixel. Without this the whole image shifts by 10 m, which at 60 m is a sixth of a pixel
    of geometry error on every layer.
    """
    half = pixel_m / 2.0
    return Affine(pixel_m, 0.0, float(x[0]) - half, 0.0, -pixel_m, float(y[0]) + half)


def reproject_to_web(
    array: np.ndarray,
    src_transform: Affine,
    src_crs: str = CRS_NATIVE,
    mask: bool = False,
) -> tuple[np.ndarray, Affine]:
    """Resample a grid into a north-up EPSG:3857 rectangle. Returns (array, transform)."""
    from rasterio.crs import CRS
    from rasterio.warp import Resampling, calculate_default_transform, reproject as warp

    rows, cols = array.shape
    dst_crs = CRS.from_string(CRS_WEB)
    dst_transform, width, height = calculate_default_transform(
        CRS.from_string(src_crs), dst_crs, cols, rows,
        *_outer_bounds(src_transform, rows, cols),
    )
    if mask:
        source = np.asarray(array, dtype="uint8")
        destination = np.zeros((height, width), dtype="uint8")
        warp(source=source, destination=destination, src_transform=src_transform,
             src_crs=CRS.from_string(src_crs), dst_transform=dst_transform, dst_crs=dst_crs,
             resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
        return destination.astype(bool), dst_transform

    source = np.asarray(array, dtype="float32")
    destination = np.full((height, width), np.nan, dtype="float32")
    warp(source=source, destination=destination, src_transform=src_transform,
         src_crs=CRS.from_string(src_crs), dst_transform=dst_transform, dst_crs=dst_crs,
         resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan)
    return destination, dst_transform


def _outer_bounds(transform: Affine, rows: int, cols: int) -> tuple[float, float, float, float]:
    """(left, bottom, right, top) of the grid in its own CRS."""
    left = transform.c
    top = transform.f
    right = left + cols * transform.a
    bottom = top + rows * transform.e
    return min(left, right), min(bottom, top), max(left, right), max(bottom, top)


def web_bounds_lonlat(transform: Affine, height: int, width: int) -> list[list[float]]:
    """Leaflet bounds ``[[south, west], [north, east]]`` of an EPSG:3857 image.

    Leaflet stretches an image linearly across the bounds in Web Mercator space, so the rectangle in
    EPSG:3857 is converted back to lon/lat corner by corner. The result is what the manifest carries.
    """
    from pyproj import Transformer

    left = transform.c
    top = transform.f
    right = left + width * transform.a
    bottom = top + height * transform.e
    inverse = Transformer.from_crs(CRS_WEB, CRS_WGS84, always_xy=True)
    lons, lats = inverse.transform([left, right], [bottom, top])
    return [[round(lats[0], 6), round(lons[0], 6)], [round(lats[1], 6), round(lons[1], 6)]]


def lonlat_bounds_of_native(x: np.ndarray, y: np.ndarray, pixel_m: float) -> list[list[float]]:
    """Native-grid bounds in lon/lat, widened by half a pixel. Used for the sanity check."""
    from pyproj import Transformer

    half = pixel_m / 2.0
    xs = [float(x[0]) - half, float(x[-1]) + half]
    ys = [float(y[-1]) - half, float(y[0]) + half]
    inverse = Transformer.from_crs(CRS_NATIVE, CRS_WGS84, always_xy=True)
    lons, lats = inverse.transform([xs[0], xs[1], xs[1], xs[0]], [ys[0], ys[0], ys[1], ys[1]])
    return [[round(min(lats), 6), round(min(lons), 6)], [round(max(lats), 6), round(max(lons), 6)]]


def round_geojson(geojson: dict, decimals: int = 6, simplify_deg: float = 0.00005) -> dict:
    """Simplify polygons slightly (about 5 m) and round every coordinate to ``decimals`` places."""
    from shapely.geometry import mapping, shape

    out = {"type": "FeatureCollection", "features": []}
    for feature in geojson["features"]:
        geom = shape(feature["geometry"])
        if simplify_deg > 0:
            geom = geom.simplify(simplify_deg, preserve_topology=True)
        out["features"].append({
            "type": "Feature",
            "geometry": _round_coords(mapping(geom), decimals),
            "properties": feature["properties"],
        })
    return out


def _round_coords(geometry: dict, decimals: int) -> dict:
    def walk(node):
        if isinstance(node[0], (float, int)):
            return [round(float(node[0]), decimals), round(float(node[1]), decimals)]
        return [walk(child) for child in node]

    return {"type": geometry["type"], "coordinates": walk(geometry["coordinates"])}


def write_json(path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=True), encoding="utf-8")


def write_js(path, key: str, payload: Any) -> None:
    """Write the same payload as a script that adds itself to ``window.VENUS``.

    Browsers refuse ``fetch()`` of a local file (file://), but a <script> tag always works. The JSON is
    escaped to pure ASCII (non-ASCII becomes \\uXXXX), so no encoding can break it.
    """
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    path.write_text(
        f"window.VENUS = window.VENUS || {{}};\nwindow.VENUS[{json.dumps(key)}] = {text};\n",
        encoding="ascii",
    )


def assert_provisional(layers: list[dict], crid: str = "P05023") -> None:
    """Fail loudly if any layer is not the provisional product. Mixing maturities is never allowed."""
    bad = [layer["id"] for layer in layers if layer.get("crid") != crid]
    if bad:
        raise SystemExit(f"REFUSING TO EXPORT: layers not from CRID {crid}: {', '.join(bad)}")
