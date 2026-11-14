"""Tests for the display chain: resolution rule, crop validity, dB clipping, WebP budgets."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import display as dx  # noqa: E402


def test_display_resolution_is_half_a_native_pixel_in_mercator():
    res = dx.display_resolution(20.0, 31.5)
    assert 10.0 <= res <= 13.0
    assert res == pytest.approx(20.0 / np.cos(np.radians(31.5)) / 2.0)


def test_display_resolution_rejects_nonsense():
    with pytest.raises(SystemExit):
        dx.display_resolution(60.0, 31.5)


def test_valid_native_rejects_zero_255_and_nan():
    array = np.array([[1.0, np.nan], [2.0, 3.0]], dtype="float32")
    mask = np.array([[0, 1], [255, 1]], dtype="uint8")
    valid = dx.valid_native(array, mask)
    assert valid.tolist() == [[False, False], [False, True]]


def test_choose_crop_shrinks_until_the_rectangle_is_valid():
    theme = "POLYGON((36.82 31.845, 36.84 31.845, 36.84 31.855, 36.82 31.855, 36.82 31.845))"
    valid = np.ones((200, 300), dtype=bool)
    valid[:120, :] = False   # a swath edge cuts away the top of the native window
    transform = dx.wx.grid_transform(
        np.arange(300) * 20.0 + 292430.0, 3529030.0 - np.arange(200) * 20.0, 20.0
    )
    rect, res, fraction = dx.choose_crop(valid, transform, "EPSG:32637", theme, 31.82, 20.0)
    assert fraction >= 0.995
    assert 10.0 <= res <= 13.0
    assert rect[2] > rect[0] and rect[3] > rect[1]


def test_stretched_linear_clips_in_db_and_keeps_nan():
    power = np.array([[10.0 ** (-30 / 10), 10.0 ** (-10 / 10)]], dtype="float32")
    valid = np.array([[True, False]])
    out = dx.stretched_linear(power, -20.0, -5.0, valid)
    assert np.isclose(10 * np.log10(out[0, 0]), -20.0, atol=1e-4)  # clipped at the low limit
    assert np.isnan(out[0, 1])                                      # invalid stays invalid


def test_webp_and_preview_stay_inside_budget(tmp_path):
    rgba = np.zeros((240, 320, 4), dtype="uint8")
    rgba[..., 0] = 200
    rgba[..., 3] = 255
    path = tmp_path / "layer.webp"
    size, quality = dx.save_layer(Image.fromarray(rgba, mode="RGBA"), path)
    assert quality in (82, 75, 68)
    assert size <= 700_000
    preview = tmp_path / "layer_preview.webp"
    assert preview.exists() and preview.stat().st_size <= 15_000


def test_feather_leaves_the_interior_opaque_and_fades_the_edge():
    rgba = np.zeros((20, 20, 4), dtype="uint8")
    rgba[..., 3] = 255
    out = dx.feather_alpha(rgba, width=6)
    assert out[10, 10, 3] == 255
    assert out[0, 10, 3] < 255
    assert out[19, 10, 3] < 255
