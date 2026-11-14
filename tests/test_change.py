"""Tests for the change-detection maths. Fast, offline, no data needed.

These lock in the numbers we verified against a real NISAR GCOV product on 2026-11-13, so a future
refactor cannot silently switch power for amplitude or average in the wrong domain.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import change  # noqa: E402


def test_dB_uses_ten_log10_because_gcov_is_power():
    # gamma-0 power 0.1 -> -10 dB. If someone switches to 20*log10 this becomes -20 and fails.
    db = change.power_to_db(np.array([0.1, 1.0, 10.0], dtype="float32"))
    assert db == pytest.approx([-10.0, 0.0, 10.0], abs=1e-4)


def test_zero_and_nan_are_nan_not_minus_inf():
    db = change.power_to_db(np.array([0.0, -1.0, np.nan], dtype="float32"))
    assert np.all(np.isnan(db))


def test_multilook_averages_power_not_decibels():
    # Power values 0.01 and 1.0 (a 20 dB spread): mean power is 0.505, so dB = 10*log10(0.505)
    # = -2.97 dB. Averaging dB instead would give (-20 + 0)/2 = -10 dB, which is wrong by 7 dB.
    power = np.array([[0.01, 0.01], [1.0, 1.0]], dtype="float32")
    out = change.multilook_power(power, factor=2)
    assert out.shape == (1, 1)
    assert out[0, 0] == pytest.approx(0.505, rel=1e-4)


def test_multilook_handles_nan_and_trims_remainder():
    power = np.array(
        [[1.0, 1.0, 9.0], [1.0, np.nan, 9.0], [9.0, 9.0, 9.0]], dtype="float32"
    )
    out = change.multilook_power(power, factor=2)
    assert out.shape == (1, 1)  # 3x3 -> one full 2x2 block
    assert out[0, 0] == pytest.approx(1.0, rel=1e-4)  # one NaN ignored, not propagated


def test_otsu_finds_the_valley_between_two_modes():
    rng = np.random.default_rng(0)
    water = rng.normal(-20.0, 0.6, 4000)
    land = rng.normal(-12.0, 1.5, 6000)
    threshold = change.otsu_threshold(np.concatenate([water, land]))
    assert -19.0 < threshold < -14.0


def test_water_mask_thresholds_and_drops_nan():
    db = np.array([-25.0, -19.0, -10.0, np.nan], dtype="float32")
    mask = change.water_mask(db, -17.0)
    assert mask.tolist() == [True, True, False, False]


def test_area_counts_pixels_at_pixel_spacing():
    mask = np.zeros((10, 10), dtype=bool)
    mask[:5, :5] = True  # 25 pixels at 20 m = 25 * 400 m2 = 0.01 km2
    assert change.area_km2(mask, 20.0) == pytest.approx(0.01, rel=1e-6)


def test_difference_is_later_minus_earlier():
    later = np.array([-10.0, -20.0], dtype="float32")
    earlier = np.array([-8.0, -20.0], dtype="float32")
    assert change.difference_db(later, earlier).tolist() == pytest.approx([-2.0, 0.0])
