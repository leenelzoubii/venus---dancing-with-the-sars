"""Tests for candidate-patch detection: runs, connectivity, size filtering, signs, distances.

These lock in the rules that keep speckle out of the patch list, because those rules are the only
thing standing between us and a map covered in fake change.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import patches  # noqa: E402


def _stack(frames):
    return np.stack([np.asarray(f, dtype=bool).reshape(1, -1) for f in frames], axis=0)


def test_consecutive_requires_adjacent_dates():
    stack = _stack([
        [1, 0],  # A changed on date 1 only
        [0, 1],  # B changed on date 2 only
        [1, 0],  # A changed again on date 3 - but never twice in a row
    ])
    assert not patches.consecutive_any(stack, 2).any()


def test_consecutive_detects_a_true_run():
    stack = _stack([
        [0, 0],
        [1, 0],
        [1, 1],
        [0, 1],
    ])
    result = patches.consecutive_any(stack, 2)
    # Both pixels changed on at least two adjacent dates (1-3 and 2-4 respectively).
    assert result.all()


def test_consecutive_with_one_is_changed_ever():
    stack = _stack([[1, 0], [0, 1]])
    assert patches.consecutive_any(stack, 1).all()


def test_consecutive_shorter_than_requested_returns_nothing():
    stack = _stack([[1, 1]])
    assert not patches.consecutive_any(stack, 3).any()


def test_label_patches_uses_eight_connectivity():
    mask = np.zeros((6, 6), dtype=bool)
    mask[1, 1] = True
    mask[2, 2] = True  # diagonal neighbour: one patch at 8-connectivity
    mask[5, 5] = True  # separate speck
    labels, count = patches.label_patches(mask, min_area_px=1, connectivity=8)
    assert count == 2
    assert labels[1, 1] == labels[2, 2]


def test_label_patches_drops_small_blobs_and_orders_by_area():
    mask = np.zeros((12, 12), dtype=bool)
    mask[0:2, 0:2] = True     # 4 px
    mask[5:9, 5:9] = True     # 16 px
    labels, count = patches.label_patches(mask, min_area_px=10, connectivity=8)
    assert count == 1
    assert labels[6, 6] == 1  # the survivor is P01


def test_label_patches_respects_minimum_area():
    mask = np.zeros((10, 10), dtype=bool)
    mask[1:3, 1:3] = True
    labels, count = patches.label_patches(mask, min_area_px=5)
    assert count == 0
    assert not labels.any()


def test_patch_statistics_is_nan_aware_median():
    labels = np.zeros((4, 4), dtype="int32")
    labels[1:3, 1:3] = 1
    values = np.full((4, 4), np.nan, dtype="float32")
    values[1, 1] = 1.0
    values[1, 2] = 3.0
    values[2, 1] = 5.0
    stats = patches.patch_statistics(labels, values, min_valid=1)
    assert stats[1] == 3.0


def test_patch_statistics_skips_patches_with_too_few_pixels():
    labels = np.zeros((4, 4), dtype="int32")
    labels[1, 1] = 1
    values = np.full((4, 4), np.nan, dtype="float32")
    values[1, 1] = -4.0
    assert patches.patch_statistics(labels, values, min_valid=3) == {}


def test_subpixel_area_matches_pixel_count():
    # 20 px at 60 m = 20 * 3600 m2 = 0.072 km2
    assert patches.subpixel_area_km2(20, 60.0) == 0.072


def test_dominant_sign_picks_the_majority_direction():
    assert patches.dominant_sign({"a": -4.0, "b": -3.5, "c": 0.2}) == "darker"
    assert patches.dominant_sign({"a": 4.0, "b": 3.5}) == "brighter"
    assert patches.dominant_sign({}) == "unknown"


def test_first_date_and_count_above():
    series = {"2026-06-24": 0.5, "2026-07-06": -3.4, "2026-07-18": -2.0}
    assert patches.first_date_above(series, 3.0) == "2026-07-06"
    assert patches.count_dates_above(series, 3.0) == 1
    assert patches.first_date_above(series, 10.0) is None


def test_distance_to_mask_is_zero_inside_and_grows_outside():
    labels = np.zeros((10, 10), dtype="int32")
    labels[0:2, 0:2] = 1     # two rows away from the water band
    labels[8:10, 8:10] = 2   # three rows away on the other side
    target = np.zeros((10, 10), dtype=bool)
    target[3, 0:10] = True   # a horizontal band at row 3
    distances = patches.distance_to_mask_km(labels, target, pixel_m=60.0)
    assert distances[1] < distances[2]
    assert distances[1] == 2 * 60.0 / 1000.0  # rows 0-1 to row 3 is two rows
    assert distances[2] == 5 * 60.0 / 1000.0  # rows 8-9 to row 3 is five rows
