"""Candidate surface-change patches: find them honestly, then describe them, then judge nothing.

The design follows one rule: a single noisy date is not a patch. A patch has to be *persistently*
different from the reference - changed by more than the threshold on at least two consecutive dates -
before we will draw a polygon around it. Speckle is uncorrelated between dates, so it rarely survives
that test, while a real clearing, a new pond or a fresh salt crust does.

Nothing here decides whether a patch is real ground change or an artefact. That judgement needs eyes
on the imagery, which is why the output includes the raw evidence (per-date medians, look counts,
distance to water) and an empty column set for the analyst to fill in.
"""

from __future__ import annotations

import numpy as np

# 8-connectivity: a pixel touches its diagonal neighbours too, so a thin diagonal ridge is one object.
EIGHT_CONNECTED = np.ones((3, 3), dtype=bool)


def changed_stack(deltas: list[np.ndarray], threshold_db: float) -> np.ndarray:
    """Boolean 3-D array: True where |delta| exceeds the threshold on that date."""
    if not deltas:
        return np.zeros((0, 0, 0), dtype=bool)
    return np.stack([np.isfinite(d) & (np.abs(d) > threshold_db) for d in deltas], axis=0)


def consecutive_any(stack: np.ndarray, min_consecutive: int = 2) -> np.ndarray:
    """True where a pixel is changed on at least ``min_consecutive`` *consecutive* dates.

    A pixel that flickers on dates 1, 3 and 7 is probably noise; one that is changed on dates 3 and 4
    in a row is a candidate. With ``min_consecutive=1`` this is simply "changed at least once".
    """
    stack = np.asarray(stack, dtype=bool)
    if stack.ndim != 3:
        raise ValueError("expected a 3-D (date, row, col) array")
    if min_consecutive <= 1:
        return stack.any(axis=0)

    n_dates = stack.shape[0]
    if n_dates < min_consecutive:
        return np.zeros(stack.shape[1:], dtype=bool)

    # A sliding window of length k sums to k only where all k frames are True, so one convolution on
    # the date axis tests every run at once.
    from scipy import ndimage

    kernel = np.ones((min_consecutive, 1, 1), dtype=np.uint8)
    counts = ndimage.convolve(stack.astype(np.uint8), kernel, mode="constant", cval=0)
    return (counts >= min_consecutive).any(axis=0)


def label_patches(mask: np.ndarray, min_area_px: int = 20, connectivity: int = 8) -> tuple[np.ndarray, int]:
    """Connected components of ``mask``, dropping any smaller than ``min_area_px``.

    Returns ``(labels, count)`` where labels are 1..count, ordered by decreasing area so that P01 is
    the largest patch - which is the order a reader will ask for them in.
    """
    from scipy import ndimage

    mask = np.asarray(mask, dtype=bool)
    structure = EIGHT_CONNECTED if connectivity == 8 else None
    labels, count = ndimage.label(mask, structure=structure)
    if count == 0:
        return labels.astype("int32"), 0

    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    keep = np.nonzero(sizes >= min_area_px)[0] + 1
    if keep.size == 0:
        return np.zeros_like(labels, dtype="int32"), 0

    # Relabel 1..n, largest first.
    order = np.argsort(-sizes[keep - 1])
    ordered = keep[order]
    remap = np.zeros(int(labels.max()) + 1, dtype="int32")
    remap[ordered] = np.arange(1, ordered.size + 1, dtype="int32")
    return remap[labels].astype("int32"), int(ordered.size)


def patch_slices(labels: np.ndarray, count: int) -> list[tuple[slice, slice]]:
    """Bounding-box slices per label, so per-patch statistics never scan the whole array."""
    from scipy import ndimage

    return ndimage.find_objects(labels, max_label=count)


def patch_statistics(
    labels: np.ndarray, values: np.ndarray, min_valid: int = 3
) -> dict[int, float]:
    """NaN-aware median of ``values`` inside each label. Labels with too few valid pixels are omitted."""
    out: dict[int, float] = {}
    for label, slc in enumerate(patch_slices(labels, int(labels.max())), start=1):
        if slc is None:
            continue
        window = labels[slc] == label
        sample = values[slc][window]
        sample = sample[np.isfinite(sample)]
        if sample.size >= min_valid:
            out[label] = float(np.median(sample))
    return out


def subpixel_area_km2(count_px: int, pixel_m: float) -> float:
    return float(count_px) * (pixel_m**2) / 1e6


def dominant_sign(deltas_by_date: dict[str, float]) -> str:
    """'brighter' or 'darker', whichever the per-date deltas favour on average."""
    values = [v for v in deltas_by_date.values() if np.isfinite(v)]
    if not values:
        return "unknown"
    return "brighter" if float(np.mean(values)) > 0 else "darker"


def distance_to_mask_km(
    labels: np.ndarray, target: np.ndarray, pixel_m: float
) -> dict[int, float]:
    """Distance in km from each patch to the nearest ``target`` pixel (e.g. water).

    One Euclidean distance transform of the target mask gives the answer for every patch at once,
    which is much cheaper than measuring from each polygon separately.
    """
    from scipy import ndimage

    target = np.asarray(target, dtype=bool)
    if not target.any():
        return {label: float("nan") for label in range(1, int(labels.max()) + 1)}
    distance_px = ndimage.distance_transform_edt(~target)
    out: dict[int, float] = {}
    for label, slc in enumerate(patch_slices(labels, int(labels.max())), start=1):
        if slc is None:
            continue
        window = labels[slc] == label
        if not window.any():
            continue
        out[label] = float(distance_px[slc][window].min()) * pixel_m / 1000.0
    return out


def first_date_above(deltas_by_date: dict[str, float], threshold_db: float) -> str | None:
    """Earliest date (chronological dict order) whose |delta| exceeds the threshold."""
    for date, value in deltas_by_date.items():
        if np.isfinite(value) and abs(value) > threshold_db:
            return date
    return None


def count_dates_above(deltas_by_date: dict[str, float], threshold_db: float) -> int:
    return int(sum(1 for v in deltas_by_date.values() if np.isfinite(v) and abs(v) > threshold_db))
