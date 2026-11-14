"""Turning GCOV power into something a human can read.

Three conversions, in the order the pipeline applies them:

1. **power -> dB** (``10*log10``) — GCOV diagonal terms are gamma-0 *power*, not amplitude;
2. **speckle reduction** — a small median or boxcar window, because radar images are grainy;
3. **stretch to 8-bit** — percentile clip, so one bright outlier cannot flatten the picture.

And the change operation: **dB difference** (later minus earlier), plus a simple water mask.
"""

from __future__ import annotations

import numpy as np

# Absolute floor for dB conversion: gamma-0 power can legitimately be 0 (masked / no data), and
# log10(0) is -inf. 1e-6 in power is -60 dB, far below any real land or water return.
POWER_FLOOR = 1e-6


def power_to_db(power: np.ndarray) -> np.ndarray:
    """Convert linear power to decibels, preserving invalid pixels as NaN."""
    arr = np.asarray(power, dtype="float32")
    invalid = ~np.isfinite(arr) | (arr <= 0)
    db = np.full(arr.shape, np.nan, dtype="float32")
    np.log10(np.clip(arr, POWER_FLOOR, None), out=db, where=~invalid, dtype="float32")
    db *= 10.0
    db[invalid] = np.nan
    return db


def db_to_power(db: np.ndarray) -> np.ndarray:
    return np.power(10.0, np.asarray(db, dtype="float32") / 10.0)


def speckle_filter(data: np.ndarray, method: str = "median", size: int = 5) -> np.ndarray:
    """Reduce speckle. NaN-aware for the median; boxcar ignores NaNs rather than smearing them."""
    if size <= 1 or method in (None, "none"):
        return data
    size = int(size) | 1  # force odd
    if method == "median":
        from scipy.ndimage import generic_filter

        return generic_filter(data, np.nanmedian, size=size, mode="nearest").astype("float32")
    if method == "boxcar":
        from scipy.ndimage import uniform_filter

        valid = np.isfinite(data)
        filled = np.where(valid, data, 0.0).astype("float32")
        num = uniform_filter(filled, size=size, mode="nearest")
        den = uniform_filter(valid.astype("float32"), size=size, mode="nearest")
        out = np.divide(num, den, out=np.full_like(num, np.nan), where=den > 0)
        out[~valid] = np.nan
        return out.astype("float32")
    raise ValueError(f"Unknown speckle filter {method!r}; use median, boxcar or none.")


def percentile_stretch(
    data: np.ndarray, low: float = 2.0, high: float = 98.0
) -> tuple[np.ndarray, tuple[float, float]]:
    """Clip to percentiles and scale to 0-255. Returns (uint8 image, (vmin, vmax)) for the legend."""
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros(data.shape, dtype="uint8"), (np.nan, np.nan)
    vmin, vmax = (float(v) for v in np.percentile(finite, [low, high]))
    if vmax <= vmin:
        vmax = vmin + 1e-6
    scaled = (np.clip(data, vmin, vmax) - vmin) / (vmax - vmin)
    image = np.nan_to_num(scaled, nan=0.0) * 255.0
    return image.astype("uint8"), (vmin, vmax)


def difference_db(later_db: np.ndarray, earlier_db: np.ndarray) -> np.ndarray:
    """Change in dB (later minus earlier). Negative = the surface returned less echo (e.g. new water)."""
    return (np.asarray(later_db, dtype="float32") - np.asarray(earlier_db, dtype="float32"))


def ratio_db(later_db: np.ndarray, earlier_db: np.ndarray) -> np.ndarray:
    """Ratio expressed in dB — identical arithmetic to the difference of two dB images, kept as a
    separate name because the *interpretation* differs (multiplicative change in power)."""
    return difference_db(later_db, earlier_db)


def water_mask(db: np.ndarray, threshold_db: float = -17.0) -> np.ndarray:
    """Boolean mask of very dark pixels (open water candidate).

    The threshold is a starting point, not a truth: it must be tuned on the data and sanity-checked
    against known open water. Wind roughening, wet salt crust and shadow all break the simple rule.
    """
    arr = np.asarray(db, dtype="float32")
    return np.isfinite(arr) & (arr < threshold_db)


def area_km2(mask: np.ndarray, pixel_size_m: float) -> float:
    """Area of a boolean mask given the pixel spacing in metres."""
    return float(np.count_nonzero(mask)) * (pixel_size_m**2) / 1e6
