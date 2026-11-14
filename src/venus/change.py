"""Turning GCOV power into something a human can read.

Three conversions, in the order the pipeline applies them:

1. **power -> dB** (``10*log10``) - GCOV diagonal terms are gamma-0 *power*, not amplitude;
2. **speckle reduction** - a small median or boxcar window, because radar images are grainy;
3. **stretch to 8-bit** - percentile clip, so one bright outlier cannot flatten the picture.

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


def multilook_power(power: np.ndarray, factor: int = 1) -> np.ndarray:
    """Average ``factor x factor`` blocks **in the power domain**, then return power.

    This is the radiometrically correct order: averaging must happen on linear power, not on dB
    (averaging dB under-estimates the mean because log is concave). Multi-looking cuts speckle
    variance roughly with the number of looks, which is what makes a difference image readable
    instead of pure noise.
    """
    arr = np.asarray(power, dtype="float32")
    factor = int(factor)
    if factor <= 1:
        return arr

    rows = (arr.shape[0] // factor) * factor
    cols = (arr.shape[1] // factor) * factor
    block = arr[:rows, :cols].reshape(rows // factor, factor, cols // factor, factor)
    valid = np.isfinite(block)
    summed = np.where(valid, block, 0.0).sum(axis=(1, 3), dtype="float64")
    count = valid.sum(axis=(1, 3))
    out = np.full((rows // factor, cols // factor), np.nan, dtype="float32")
    np.divide(summed, count, out=out, where=count > 0)
    return out


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
    """Ratio expressed in dB - identical arithmetic to the difference of two dB images, kept as a
    separate name because the *interpretation* differs (multiplicative change in power)."""
    return difference_db(later_db, earlier_db)


def water_mask(db: np.ndarray, threshold_db: float = -17.0) -> np.ndarray:
    """Boolean mask of very dark pixels (open water candidate).

    The threshold is a starting point, not a truth: it must be tuned on the data and sanity-checked
    against known open water. Wind roughening, wet salt crust and shadow all break the simple rule.
    Use :func:`otsu_threshold` to derive one from the data instead of guessing.
    """
    arr = np.asarray(db, dtype="float32")
    return np.isfinite(arr) & (arr < threshold_db)


def otsu_threshold(
    db: np.ndarray, low: float = -30.0, high: float = 5.0, step: float = 0.05
) -> float:
    """Two-class Otsu threshold in dB: finds the valley between the dark (water) and bright modes.

    Derived from the image itself, which matters because NISAR L-band backscatter over the Dead Sea
    is *not* the textbook -20 dB: measured water sits near -13.7 dB in HH and -20.5 dB in HV. A fixed
    literature threshold would map the lake incorrectly.
    """
    values = np.asarray(db, dtype="float64")
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan")
    counts, edges = np.histogram(values, bins=np.arange(low, high + step, step))
    centres = (edges[:-1] + edges[1:]) / 2.0
    weight_dark = np.cumsum(counts).astype("float64")
    total = weight_dark[-1]
    if total <= 0:
        return float("nan")
    cum_mean = np.cumsum(counts * centres)
    mean_total = cum_mean[-1]
    weight_bright = total - weight_dark
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mean_total * weight_dark / total - cum_mean) ** 2 / (
            weight_dark * weight_bright / total**2
        )
    between[~np.isfinite(between)] = np.nan
    return float(centres[int(np.nanargmax(between))])


def threshold_sensitivity(
    db: np.ndarray,
    threshold_db: float,
    half_width_db: float = 1.5,
    step_db: float = 0.5,
    pixel_size_m: float = 20.0,
) -> list[tuple[float, float]]:
    """Water area as the threshold moves, so uncertainty can be quoted instead of hidden."""
    offsets = np.arange(-half_width_db, half_width_db + 1e-9, step_db)
    return [
        (float(threshold_db + o), area_km2(water_mask(db, threshold_db + o), pixel_size_m))
        for o in offsets
    ]



def area_km2(mask: np.ndarray, pixel_size_m: float) -> float:
    """Area of a boolean mask given the pixel spacing in metres."""
    return float(np.count_nonzero(mask)) * (pixel_size_m**2) / 1e6


def land_mask(
    hv_db: np.ndarray,
    looks: np.ndarray | None = None,
    hh_db: np.ndarray | None = None,
    hv_land_cut_db: float = -15.0,
    min_looks: float = 4.0,
) -> np.ndarray:
    """Pixels we are willing to call land when estimating a scene-wide offset.

    Deliberately strict, because an offset estimated over water or over noisy low-look pixels would
    be an offset of the wrong population. Land here means:

    * valid in HV (and in HH when supplied - both must exist for the difference to exist);
    * ``HV > hv_land_cut_db`` - above the water/land transition, so open water is excluded;
    * ``numberOfLooks >= min_looks`` - low-look pixels are the noisiest and least trustworthy;
    * ``mask == 1`` when a mask is supplied.

    The cut is a documented choice, not a constant of nature: open water on this AOI sits near
    -20.5 dB in HV, and the land mode starts around -14 dB.
    """
    land = np.isfinite(hv_db) & (hv_db > hv_land_cut_db)
    if hh_db is not None:
        land &= np.isfinite(hh_db)
    if looks is not None:
        with np.errstate(invalid="ignore"):
            land &= np.isfinite(looks) & (looks >= min_looks)
    return land


def robust_offset_db(
    later_db: np.ndarray, earlier_db: np.ndarray, land: np.ndarray
) -> tuple[float, int, float]:
    """Scene-wide offset in dB: median of (later - earlier) over land, with its MAD.

    The median ignores the tails (a lake drying is a real change, and it should not drag the
    correction); the MAD says how tightly the land population agrees, which is the uncertainty on
    the offset itself.
    """
    diff = np.asarray(later_db, dtype="float32") - np.asarray(earlier_db, dtype="float32")
    selected = diff[np.asarray(land, dtype=bool) & np.isfinite(diff)]
    if selected.size == 0:
        return float("nan"), 0, float("nan")
    median = float(np.median(selected))
    mad = float(np.median(np.abs(selected - median)))
    return median, int(selected.size), mad
