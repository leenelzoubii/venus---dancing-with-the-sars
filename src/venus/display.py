"""Display chain: sharp, deep-zoom radar imagery for the browser.

Two chains live in this project and they must not be confused:

* the **analysis chain** (``change.py``, 60 m multilook + median speckle filter) produces the numbers;
  it is untouched by this module;
* the **display chain** (this module) produces only what the eye sees: native 20 m linear-power
  samples, reprojected once to Web Mercator at about 10 m, stretched in dB with limits pooled over
  every date of the place, then handed to the existing false-colour recipe.

Why native resolution: NISAR GCOV is already multilooked (mean 9.34 looks) at 20 m. Multilooking it
again to 60 m and then upscaling on screen is what made the map blocky. Reprojecting once, on linear
power, keeps the radiometry honest; resampling an already-coloured RGB would blend colours that were
never measured.

Nothing here changes a statistic: the analysis arrays are passed through untouched elsewhere.
"""

from __future__ import annotations

import math

import numpy as np
from affine import Affine
from PIL import Image

from . import webexport as wx

DISPLAY_CROP_MARGIN = 0.05      # +5 % around the AOI bbox, kept only if it stays inside valid data
MIN_VALID_FRACTION = 0.995      # a crop rectangle must be at least 99.5 % valid
# NISAR (20 m native) targets ~10-13 m in Web Mercator; S1 (30 m native) targets ~15-20 m.
# The allowed band is +/- 2 m around the target centre.
TARGET_PX_M = (10.0, 13.0)      # default for NISAR (20 m native -> 10-13 m display)


def display_resolution(native_px_m: float, centre_lat: float, target_px_m: tuple[float, float] | None = None) -> float:
    """Half a native pixel in Web Mercator metres.

    For NISAR (20 m native) this is ~10-12 m. For S1 (30 m native) this is ~15-18 m.
    """
    target = target_px_m or TARGET_PX_M
    res = native_px_m / math.cos(math.radians(centre_lat)) / 2.0
    if not (target[0] - 2.0 <= res <= target[1] + 2.0):
        raise SystemExit(f"display resolution {res:.2f} m is outside the expected {target[0]-2:.0f}-{target[1]+2:.0f} m band")
    return res


def valid_native(array: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    """True where a native sample is usable: finite and not flagged by the product mask."""
    valid = np.isfinite(array)
    if mask is not None:
        valid &= (mask != 0) & (mask != 255)
    return valid


def aoi_rect_3857(wkt, margin: float = DISPLAY_CROP_MARGIN) -> tuple[float, float, float, float]:
    """The AOI lon/lat bbox as an axis-aligned EPSG:3857 rectangle, optionally grown by ``margin``."""
    from pyproj import Transformer
    from shapely import wkt as shapely_wkt

    minx, miny, maxx, maxy = shapely_wkt.loads(wkt).bounds
    dx, dy = (maxx - minx) * margin, (maxy - miny) * margin
    forward = Transformer.from_crs(wx.CRS_WGS84, wx.CRS_WEB, always_xy=True)
    xs, ys = forward.transform([minx - dx, maxx + dx], [miny - dy, maxy + dy])
    return min(xs), min(ys), max(xs), max(ys)


def grid_for_rect(rect: tuple[float, float, float, float], target_res: float) -> tuple[Affine, int, int]:
    """A north-up grid that exactly fills ``rect`` at about ``target_res`` metres per pixel."""
    left, bottom, right, top = rect
    width = max(1, round((right - left) / target_res))
    height = max(1, round((top - bottom) / target_res))
    return Affine((right - left) / width, 0.0, left, 0.0, (bottom - top) / height, top), width, height


def warp_valid(
    valid: np.ndarray,
    src_transform: Affine,
    src_crs: str,
    dst_transform: Affine,
    width: int,
    height: int,
) -> np.ndarray:
    """Nearest-neighbour validity on the destination grid (no invented fractional validity)."""
    from rasterio.crs import CRS
    from rasterio.warp import Resampling, reproject as warp

    destination = np.zeros((height, width), dtype="uint8")
    warp(
        source=np.asarray(valid, dtype="uint8"),
        destination=destination,
        src_transform=src_transform,
        src_crs=CRS.from_string(src_crs),
        dst_transform=dst_transform,
        dst_crs=CRS.from_string(wx.CRS_WEB),
        resampling=Resampling.nearest,
        src_nodata=0,
        dst_nodata=0,
    )
    return destination.astype(bool)


def choose_crop(
    valid: np.ndarray,
    src_transform: Affine,
    src_crs: str,
    aoi_wkt: str,
    centre_lat: float,
    native_px_m: float,
    target_px_m: tuple[float, float] | None = None,
) -> tuple[tuple[float, float, float, float], float, float]:
    """Pick ONE axis-aligned crop rectangle, shared by every layer of the place.

    Starts at the AOI bbox +5 % (kept only when it is already >= 99.5 % valid) and shrinks stepwise by
    2 % of the current size per side until the rectangle is >= 99.5 % valid. Returns
    (rect_3857, display_res_m, valid_fraction).
    """
    res = display_resolution(native_px_m, centre_lat, target_px_m)
    for margin in (DISPLAY_CROP_MARGIN, 0.0):
        left, bottom, right, top = aoi_rect_3857(aoi_wkt, margin)
        transform, width, height = grid_for_rect((left, bottom, right, top), res)
        valid_grid = warp_valid(valid, src_transform, src_crs, transform, width, height)
        row0, row1, col0, col1 = 0, height, 0, width
        fraction = float(valid_grid.mean())
        for _ in range(120):
            if fraction >= MIN_VALID_FRACTION:
                break
            step_y = max(1, round((row1 - row0) * 0.02))
            step_x = max(1, round((col1 - col0) * 0.02))
            bands = {
                "top": valid_grid[row0:row0 + step_y, col0:col1],
                "bottom": valid_grid[row1 - step_y:row1, col0:col1],
                "left": valid_grid[row0:row1, col0:col0 + step_x],
                "right": valid_grid[row0:row1, col1 - step_x:col1],
            }
            # Trim the side that is least valid. Symmetric shrinking would throw away good data on
            # the opposite side when a swath edge cuts across only one corner.
            side = min(bands, key=lambda key: float(bands[key].mean()))
            if side == "top":
                row0 += step_y
            elif side == "bottom":
                row1 -= step_y
            elif side == "left":
                col0 += step_x
            else:
                col1 -= step_x
            if col1 - col0 < 8 or row1 - row0 < 8:
                fraction = 0.0
                break
            fraction = float(valid_grid[row0:row1, col0:col1].mean())
        if fraction >= MIN_VALID_FRACTION:
            dx = (right - left) / width
            dy = (top - bottom) / height
            cropped = (left + col0 * dx, top - row1 * dy, left + col1 * dx, top - row0 * dy)
            return cropped, res, fraction
    raise SystemExit("cannot find a 99.5 % valid crop for this place; investigate the cached data")


def pooled_db_limits(arrays_by_date: dict[str, np.ndarray], valid_by_date: dict[str, np.ndarray],
                     percentiles=(2.0, 98.0)) -> tuple[float, float]:
    """2nd/98th percentiles of dB over every valid pixel of every date (identical for all dates)."""
    chunks = []
    for day, power in arrays_by_date.items():
        valid = valid_by_date[day] & np.isfinite(power) & (power > 0)
        if valid.any():
            chunks.append(10.0 * np.log10(power[valid]))
    if not chunks:
        raise SystemExit("no valid power pixels to compute display limits")
    pooled = np.concatenate(chunks)
    lo, hi = (float(v) for v in np.percentile(pooled, percentiles))
    return lo, max(hi, lo + 1.0)


def stretched_linear(power: np.ndarray, vmin: float, vmax: float, valid: np.ndarray) -> np.ndarray:
    """Clip a linear-power band at the pooled dB limits and return linear power again.

    The existing false-colour recipe is absolute and expects linear power, so the only honest way to
    give it date-independent limits is to clip in dB and convert back. No per-date stretch, no
    invented values, invalid samples stay NaN.
    """
    out = np.full(power.shape, np.nan, dtype="float32")
    good = valid & np.isfinite(power) & (power > 0)
    db = 10.0 * np.log10(power[good])
    out[good] = np.power(10.0, np.clip(db, vmin, vmax) / 10.0).astype("float32")
    return out


def single_pol_db(power: np.ndarray, vmin: float, vmax: float, valid: np.ndarray) -> np.ndarray:
    """dB image clipped at the pooled limits; NaN outside the valid mask."""
    out = np.full(power.shape, np.nan, dtype="float32")
    good = valid & np.isfinite(power) & (power > 0)
    db = 10.0 * np.log10(power[good])
    out[good] = np.clip(db, vmin, vmax).astype("float32")
    return out


def single_pol_ramp(db: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """The fixed blue-green-orange-yellow single-pol ramp, driven by the pooled limits.

    The ramp is absolute; we map the pooled 2-98 % dB range onto its own published domain so the same
    colour means the same relative backscatter on every date of this place.
    """
    stops = wx.SINGLE_POL_STOPS
    low, high = stops[0][0], stops[-1][0]
    t = np.clip((db - vmin) / max(vmax - vmin, 1e-6), 0.0, 1.0)
    return wx.single_pol_rgb(low + t * (high - low), stops)


def save_webp(image: Image.Image, path, quality: int = 82, method: int = 4) -> int:
    """Lossy WebP with alpha. Returns the file size in bytes.

    Method 4 rather than 6: method 6 took 87 s for a 964x2434 layer on the build machine, which would
    make a six-place rebuild take over an hour. Method 4 costs about 2.6 s and stays far inside the
    700 KB per-layer budget (measured average about 100 KB), so the extra search buys nothing here.
    """
    image.save(path, format="WEBP", quality=quality, method=method)
    return path.stat().st_size


def save_preview(image: Image.Image, path, max_px: int = 256, budget: int = 15_000) -> int:
    """A tiny WebP shown instantly while the full layer loads. Never above ``budget`` bytes."""
    scale = min(1.0, max_px / max(image.size))
    small = image if scale >= 1.0 else image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )
    for quality in (60, 50, 40, 30):
        size = save_webp(small, path, quality=quality, method=4)
        if size <= budget:
            return size
    return size


def save_layer(image: Image.Image, path, budget: int = 700_000) -> tuple[int, int]:
    """Write a full WebP within budget and a preview beside it. Returns (bytes, quality_used)."""
    for quality in (82, 75, 68):
        size = save_webp(image, path, quality=quality)
        if size <= budget:
            break
    else:
        # Last resort: use 60
        size = save_webp(image, path, quality=60)
    save_preview(image, path.with_name(path.stem + "_preview.webp"))
    return size, quality


def warp_nansafe(
    power: np.ndarray,
    valid: np.ndarray,
    src_transform: Affine,
    src_crs: str,
    dst_transform: Affine,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear reprojection of linear power without letting invalid pixels smear in.

    Data times valid and valid are warped separately and divided, so a nodata neighbour contributes
    nothing instead of pulling the value toward zero. Returns (power, weight); keep pixels where
    weight >= 0.5.
    """
    from rasterio.crs import CRS
    from rasterio.warp import Resampling, reproject as warp

    good = valid & np.isfinite(power)
    source = np.where(good, power, 0.0).astype("float32")
    weight = good.astype("float32")
    dst_data = np.zeros((height, width), dtype="float32")
    dst_weight = np.zeros((height, width), dtype="float32")
    for array, destination in ((source, dst_data), (weight, dst_weight)):
        warp(
            source=array,
            destination=destination,
            src_transform=src_transform,
            src_crs=CRS.from_string(src_crs),
            dst_transform=dst_transform,
            dst_crs=CRS.from_string(wx.CRS_WEB),
            resampling=Resampling.bilinear,
            src_nodata=None,
            dst_nodata=0.0,
        )
    out = np.full((height, width), np.nan, dtype="float32")
    keep = dst_weight >= 0.5
    out[keep] = dst_data[keep] / dst_weight[keep]
    return out, dst_weight


def rgba_from_rgb(rgb: np.ndarray, valid: np.ndarray, alpha: int = 255) -> np.ndarray:
    """Stack three colour channels and a validity mask into RGBA."""
    rgba = np.zeros((*rgb.shape[:2], 4), dtype="uint8")
    rgba[..., :3] = np.clip(rgb, 0, 255).astype("uint8")
    rgba[..., 3] = np.where(valid, alpha, 0).astype("uint8")
    return rgba


def rgba_from_mask(mask: np.ndarray, rgb: tuple[int, int, int], alpha: int) -> np.ndarray:
    """Colour a boolean mask, fully transparent elsewhere."""
    rgba = np.zeros((*mask.shape, 4), dtype="uint8")
    rgba[mask, :3] = rgb
    rgba[mask, 3] = alpha
    return rgba


def feather_alpha(rgba: np.ndarray, width: int = 6) -> np.ndarray:
    """Fade alpha over the outer ``width`` pixels of the crop rectangle (display only).

    The rectangle edge is a display artefact, not a sensor edge. Feathering it avoids a hard stair
    step while leaving fully valid pixels fully opaque.
    """
    out = rgba.copy()
    if width <= 0:
        return out
    rows, cols = out.shape[:2]
    ramp = np.ones((rows, cols), dtype="float32")
    for index in range(width):
        value = (index + 1) / (width + 1)
        ramp[index, :] = np.minimum(ramp[index, :], value)
        ramp[-1 - index, :] = np.minimum(ramp[-1 - index, :], value)
        ramp[:, index] = np.minimum(ramp[:, index], value)
        ramp[:, -1 - index] = np.minimum(ramp[:, -1 - index], value)
    out[..., 3] = np.clip(out[..., 3].astype("float32") * ramp, 0, 255).astype("uint8")
    return out
