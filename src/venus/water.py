"""Water mapping that can survive a reviewer, not just a screenshot.

The hard part is not "pixels darker than -20 dB". It is that the Dead Sea is not the textbook case:
measured open water here is about -20.5 dB in HV but only -13.7 dB in HH, and HH land runs from -13
to -5 dB, so the two populations overlap and no single HH threshold separates them. Otsu on the whole
window is also biased, because land covers far more pixels than water and pulls the "valley" up.

So this module offers three defensible estimators plus the old per-image Otsu for comparison:

* ``Method A`` - one HV threshold for the whole series, from the valley of the pooled histogram;
* ``Method B`` - two steps: discard obvious land, then Otsu on what is left;
* ``Method C`` - two-component Gaussian mixture, threshold where the posteriors cross;
* ``Method D`` - the previous per-image Otsu, kept only as a comparison.

Every area is reported with a +/- band and after a small morphological clean-up, because counting
single isolated dark pixels as lakes is how SAR water maps get embarrassing areas.
"""

from __future__ import annotations

import numpy as np

# 20 m x 20 m pixels: 400 m2 per pixel.
DEFAULT_PIXEL_M = 20.0

# Obvious land in HV: above the transition zone between the water mode (about -20.5 dB) and the
# land mode (about -14 dB). Used by method B to stop land from dominating the histogram.
DEFAULT_LAND_CUT_DB = -15.0

# Clean-up sizes, in pixels (1 px = 0.0004 km2 at 20 m).
DEFAULT_MIN_BLOB_PX = 10   # 0.004 km2 - smaller dark specks are speckle, not water
DEFAULT_MAX_HOLE_PX = 10   # 0.004 km2 - smaller bright specks inside water are filled


def _gaussian(x: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    sigma = max(float(sigma), 1e-6)
    return np.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))


def histogram_valley(
    db: np.ndarray,
    low: float = -26.0,
    high: float = -10.0,
    step: float = 0.1,
    smooth_sigma: float = 2.0,
) -> float:
    """Method A: the minimum of a smoothed histogram between its two modes.

    Finding the two modes first and then the lowest point between them is the honest version of "the
    valley": a bare ``argmin`` over the whole histogram would happily return the empty tail at -26 dB.
    """
    from scipy.ndimage import gaussian_filter1d

    values = np.asarray(db, dtype="float64")
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan")
    counts, edges = np.histogram(values, bins=np.arange(low, high + step, step))
    centres = (edges[:-1] + edges[1:]) / 2.0
    smoothed = gaussian_filter1d(counts.astype("float64"), smooth_sigma)

    dark = smoothed[: int(len(smoothed) * 0.5)]
    bright = smoothed[int(len(smoothed) * 0.5) :]
    if dark.size == 0 or bright.size == 0:
        return float("nan")
    water_mode = centres[int(np.argmax(dark))]
    land_mode = centres[int(len(dark) + np.argmax(bright))]
    if not water_mode < land_mode:
        return float("nan")

    between = (centres > water_mode) & (centres < land_mode)
    if not between.any():
        return float("nan")
    idx = np.flatnonzero(between)
    return float(centres[idx[int(np.argmin(smoothed[between]))]])


def otsu_from_values(values: np.ndarray, low: float = -30.0, high: float = 5.0, step: float = 0.05) -> float:
    """Otsu's threshold (maximised between-class variance) on a 1-D sample."""
    values = np.asarray(values, dtype="float64")
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


def two_step_threshold(db: np.ndarray, land_cut_db: float = DEFAULT_LAND_CUT_DB) -> float:
    """Method B: drop obvious land, then run Otsu on the rest.

    The point is to give Otsu a sample where water is no longer a minority: the land mode that
    dominated the full histogram is removed before it can bias the split.
    """
    values = np.asarray(db, dtype="float64")
    candidates = values[np.isfinite(values) & (values <= land_cut_db)]
    if candidates.size == 0:
        return float("nan")
    return otsu_from_values(candidates)


def gmm_threshold(values: np.ndarray, max_iter: int = 300, tol: float = 1e-7) -> float:
    """Method C: fit two 1-D Gaussians by EM, return where their posteriors cross.

    Water and land are each roughly bell-shaped in dB, so the boundary is the intensity at which a
    pixel is equally likely to belong to either. Implemented in numpy: no extra dependency, and the
    whole fit is inspectable.
    """
    x = np.asarray(values, dtype="float64")
    x = x[np.isfinite(x)]
    if x.size < 100:
        return float("nan")

    p10, p90 = np.percentile(x, [10, 90])
    mu = np.array([p10, p90], dtype="float64")
    sigma = np.array([max(x.std() / 2.0, 0.5)] * 2, dtype="float64")
    weight = np.array([0.5, 0.5], dtype="float64")

    for _ in range(max_iter):
        resp = np.stack([weight[k] * _gaussian(x, mu[k], sigma[k]) for k in range(2)])
        total = resp.sum(axis=0)
        total[total <= 0] = 1e-300
        resp = resp / total
        counts = resp.sum(axis=1)
        new_mu = (resp * x).sum(axis=1) / counts
        new_var = (resp * (x - new_mu[:, None]) ** 2).sum(axis=1) / counts
        new_sigma = np.sqrt(np.maximum(new_var, 1e-6))
        new_weight = counts / x.size
        converged = np.all(np.abs(new_mu - mu) < tol)
        mu, sigma, weight = new_mu, new_sigma, new_weight
        if converged:
            break

    order = np.argsort(mu)
    mu, sigma, weight = mu[order], sigma[order], weight[order]
    grid = np.linspace(mu[0], mu[1], 4001)
    diff = weight[0] * _gaussian(grid, mu[0], sigma[0]) - weight[1] * _gaussian(grid, mu[1], sigma[1])
    return float(grid[int(np.argmin(np.abs(diff)))])


def clean_mask(
    mask: np.ndarray,
    min_blob_px: int = DEFAULT_MIN_BLOB_PX,
    max_hole_px: int = DEFAULT_MAX_HOLE_PX,
) -> np.ndarray:
    """Remove water blobs smaller than ``min_blob_px`` and fill holes smaller than ``max_hole_px``."""
    from scipy import ndimage

    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return mask

    filled = ndimage.binary_fill_holes(mask)
    holes = filled & ~mask
    if holes.any():
        labels, count = ndimage.label(holes)
        if count:
            sizes = ndimage.sum(holes, labels, index=np.arange(1, count + 1))
            small = np.nonzero(sizes <= max_hole_px)[0] + 1
            if small.size:
                mask = mask | np.isin(labels, small)

    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    keep = np.nonzero(sizes >= min_blob_px)[0] + 1
    return np.isin(labels, keep)


def water_area_km2(
    mask: np.ndarray,
    pixel_size_m: float = DEFAULT_PIXEL_M,
    clean: bool = True,
    min_blob_px: int = DEFAULT_MIN_BLOB_PX,
    max_hole_px: int = DEFAULT_MAX_HOLE_PX,
) -> float:
    """Area of a boolean water mask in km2, after the documented clean-up."""
    if clean:
        mask = clean_mask(mask, min_blob_px, max_hole_px)
    return float(np.count_nonzero(mask)) * (pixel_size_m**2) / 1e6


def area_at_threshold(
    db: np.ndarray, threshold_db: float, pixel_size_m: float = DEFAULT_PIXEL_M, clean: bool = True
) -> float:
    values = np.asarray(db, dtype="float32")
    return water_area_km2(np.isfinite(values) & (values < threshold_db), pixel_size_m, clean)


def area_band(
    db: np.ndarray,
    threshold_db: float,
    half_width_db: float = 1.5,
    pixel_size_m: float = DEFAULT_PIXEL_M,
) -> tuple[float, float, float]:
    """(area, low, high) for a threshold and its +/- half-width band."""
    low = area_at_threshold(db, threshold_db - half_width_db, pixel_size_m)
    high = area_at_threshold(db, threshold_db + half_width_db, pixel_size_m)
    centre = area_at_threshold(db, threshold_db, pixel_size_m)
    return centre, low, high


def sweep(
    db: np.ndarray,
    low_db: float = -22.0,
    high_db: float = -15.0,
    step_db: float = 0.25,
    pixel_size_m: float = DEFAULT_PIXEL_M,
) -> list[tuple[float, float]]:
    """Water area at every threshold in a range: the honest way to show how much the answer moves."""
    thresholds = np.arange(low_db, high_db + 1e-9, step_db)
    return [(round(float(t), 2), area_at_threshold(db, float(t), pixel_size_m)) for t in thresholds]
