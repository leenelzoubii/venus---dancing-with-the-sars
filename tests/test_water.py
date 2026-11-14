"""Tests for the four water-mapping estimators - all pure functions, no files, no network."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import water  # noqa: E402


def two_mode_sample(n=40000, seed=7):
    """A synthetic bimodal sample: water near -21 dB, land near -14 dB, like the Dead Sea."""
    rng = np.random.default_rng(seed)
    wet = rng.normal(-21.0, 1.2, size=n // 4)
    dry = rng.normal(-14.0, 2.0, size=n - n // 4)
    return np.concatenate([wet, dry])


def test_histogram_valley_lands_between_the_modes():
    db = two_mode_sample()
    threshold = water.histogram_valley(db)
    assert -20.0 < threshold < -15.0


def test_histogram_valley_ignores_the_empty_tail():
    # A long empty left tail must not be mistaken for the valley.
    db = two_mode_sample()
    assert water.histogram_valley(db) > -25.0


def test_two_step_threshold_removes_land_bias():
    db = two_mode_sample()
    full = water.otsu_from_values(db)
    two_step = water.two_step_threshold(db)
    # Otsu on everything is pulled up by the dominant land mode; the two-step version sits lower.
    assert two_step < full
    assert -22.0 < two_step < -16.0


def test_gmm_threshold_recovers_the_crossing_point():
    db = two_mode_sample()
    threshold = water.gmm_threshold(db)
    assert -21.0 < threshold < -16.0


def test_gmm_threshold_survives_a_single_population():
    rng = np.random.default_rng(3)
    threshold = water.gmm_threshold(rng.normal(-14.0, 1.0, size=5000))
    assert np.isfinite(threshold)


def test_clean_mask_removes_small_blobs():
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:5, 2:5] = True      # 9 px - below the 10 px cut-off, removed
    mask[10:15, 10:15] = True  # 25 px - kept
    cleaned = water.clean_mask(mask, min_blob_px=10, max_hole_px=10)
    assert not cleaned[2:5, 2:5].any()
    assert cleaned[10:15, 10:15].all()


def test_clean_mask_fills_tiny_holes_but_keeps_large_ones():
    mask = np.ones((30, 30), dtype=bool)
    mask[5, 5] = False            # 1 px hole - filled
    mask[20:25, 20:25] = False    # 25 px hole - kept as land
    cleaned = water.clean_mask(mask, min_blob_px=10, max_hole_px=10)
    assert cleaned[5, 5]
    assert not cleaned[20:25, 20:25].any()


def test_water_area_counts_pixels_and_cleans():
    db = np.full((10, 10), -14.0, dtype="float32")
    db[0:5, 0:10] = -21.0
    area = water.water_area_km2(np.isfinite(db) & (db < -18.0), pixel_size_m=20.0)
    assert area == pytest.approx(50 * 400 / 1e6)  # 50 px * 400 m2 = 0.02 km2


def test_area_band_is_ordered():
    db = two_mode_sample().reshape(-1, 20)
    centre, low, high = water.area_band(db, -18.0, half_width_db=1.5)
    assert low < centre < high


def test_sweep_is_monotonic_in_area():
    db = np.repeat(two_mode_sample()[:20000], 1).reshape(100, -1)
    rows = water.sweep(db, low_db=-22.0, high_db=-15.0, step_db=1.0)
    areas = [a for _, a in rows]
    assert areas == sorted(areas)
    assert len(rows) == 8


def test_nan_pixels_are_never_counted_as_water():
    db = np.full((5, 5), np.nan, dtype="float32")
    db[0, 0] = -25.0
    mask = np.isfinite(db) & (db < -18.0)
    # One isolated pixel is one pixel uncorrected, and speckle once the documented clean-up runs.
    assert water.water_area_km2(mask, clean=False) == pytest.approx(0.0004)
    assert water.water_area_km2(mask, clean=True) == 0.0
