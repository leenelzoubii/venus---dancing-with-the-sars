"""Mosaicking two adjacent NISAR GCOV frames of one acquisition.

A single GCOV frame can leave a corner of the Dead Sea outside the swath; the neighbouring frame of
the same track and date fills it in. Both frames are already geocoded on the same UTM grid at the same
20 m spacing, so this is a transparent union in native coordinates - no resampling, no interpolation,
and no value is invented: where both frames are valid, the mean is used, and where only one is valid,
that one is used unchanged.
"""

from __future__ import annotations

import numpy as np


def _axis_bounds(values: list[np.ndarray]) -> tuple[float, float, float]:
    first = float(values[0][0])
    step = float(values[0][1] - values[0][0]) if values[0].size > 1 else 20.0
    lo = min(float(v.min()) for v in values)
    hi = max(float(v.max()) for v in values)
    return lo, hi, abs(step)


def mosaic_items(items: list[dict]) -> dict:
    """Combine same-date subset items on a common native grid.

    Each item has ``x``, ``y`` (pixel-centre coordinates, x increasing, y decreasing), ``arrays``
    ({pol: float32}), ``mask`` (uint8 or None) and ``meta``. Returns one item with the union grid.
    """
    if len(items) == 1:
        return items[0]
    xs = [np.asarray(item["x"], dtype="float64") for item in items]
    ys = [np.asarray(item["y"], dtype="float64") for item in items]
    x_lo, x_hi, px = _axis_bounds(xs)
    y_lo, y_hi, py = _axis_bounds(ys)
    py = px if abs(py - px) < 1e-6 else py
    nx = int(round((x_hi - x_lo) / px)) + 1
    ny = int(round((y_hi - y_lo) / py)) + 1
    x = x_lo + np.arange(nx) * px
    y = y_hi - np.arange(ny) * py

    pols = sorted({pol for item in items for pol in item["arrays"]})
    total = {}
    count = {}
    for pol in pols:
        total[pol] = np.zeros((ny, nx), dtype="float64")
        count[pol] = np.zeros((ny, nx), dtype="uint16")

    mask_sum = np.zeros((ny, nx), dtype="uint8")
    mask_any = np.zeros((ny, nx), dtype=bool)
    for item in items:
        col0 = int(round((float(item["x"][0]) - x_lo) / px))
        row0 = int(round((y_hi - float(item["y"][0])) / py))
        for pol, array in item["arrays"].items():
            array = np.asarray(array, dtype="float32")
            h, w = array.shape
            block = total[pol][row0:row0 + h, col0:col0 + w]
            counts = count[pol][row0:row0 + h, col0:col0 + w]
            valid = np.isfinite(array)
            block[valid] += array[valid]
            counts[valid] += 1
        # A missing mask (an interrupted product or an unreadable dataset) must not void that whole
        # frame: fall back to "valid wherever the data is finite", which is stricter than ignoring it.
        if item.get("mask") is not None:
            m = np.asarray(item["mask"], dtype="uint8")
            good = (m != 0) & (m != 255)
        else:
            first = next(iter(item["arrays"].values()))
            good = np.isfinite(np.asarray(first))
        h, w = good.shape
        mask_any[row0:row0 + h, col0:col0 + w] |= good

    arrays = {}
    for pol in pols:
        out = np.full((ny, nx), np.nan, dtype="float32")
        good = count[pol] > 0
        out[good] = (total[pol][good] / count[pol][good]).astype("float32")
        arrays[pol] = out
    mask = np.where(mask_any, 1, 255).astype("uint8") if any(i.get("mask") is not None for i in items) else None
    meta = dict(items[0]["meta"])
    meta["mosaic_frames"] = [item["meta"].get("frame") for item in items]
    meta["mosaic_sources"] = [item.get("stem") for item in items]
    return {"meta": meta, "x": x.tolist(), "y": y.tolist(), "arrays": arrays, "mask": mask,
            "looks": None, "stem": "+".join(str(item.get("stem")) for item in items)}
