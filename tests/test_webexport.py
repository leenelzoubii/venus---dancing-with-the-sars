"""Tests for the web-export library: bounds maths, half-pixel widening, colour ramps, alpha, schema.

All offline and fast. The reprojection test uses a synthetic grid whose answer is known in advance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import webexport as wx  # noqa: E402


def test_grid_transform_points_at_outer_edge_not_centre():
    x = np.array([1000.0, 1020.0, 1040.0])
    y = np.array([5000.0, 4980.0])
    t = wx.grid_transform(x, y, 20.0)
    assert t.c == pytest.approx(990.0)   # first centre minus half a pixel
    assert t.f == pytest.approx(5010.0)  # first centre plus half a pixel (y decreases)
    assert t.a == pytest.approx(20.0)
    assert t.e == pytest.approx(-20.0)


def test_half_pixel_widening_is_applied_to_bounds():
    x = np.array([500000.0, 500020.0])
    y = np.array([3500000.0, 3499980.0])
    bounds = wx.lonlat_bounds_of_native(x, y, 20.0, "EPSG:32636")
    from pyproj import Transformer

    inverse = Transformer.from_crs("EPSG:32636", wx.CRS_WGS84, always_xy=True)
    lon_west, _ = inverse.transform(499990.0, 3499990.0)   # outer west edge of first pixel
    lon_east, _ = inverse.transform(500030.0, 3499990.0)   # outer east edge of last pixel
    assert bounds[0][1] == pytest.approx(lon_west, abs=1e-6)
    assert bounds[1][1] == pytest.approx(lon_east, abs=1e-6)


def test_bounds_are_south_west_north_east_ordered():
    x = np.linspace(560000.0, 580000.0, 50)
    y = np.linspace(3500000.0, 3480000.0, 40)
    (south, west), (north, east) = wx.lonlat_bounds_of_native(x, y, 20.0, "EPSG:32636")
    assert south < north
    assert west < east


def test_reprojection_keeps_a_north_up_rectangle_and_bounds_match_it():
    values = np.full((60, 80), -15.0, dtype="float32")
    transform = wx.grid_transform(
        np.linspace(737000.0, 738580.0, 80), np.linspace(3480000.0, 3478800.0, 60), 20.0
    )
    dst, dst_t = wx.reproject_to_web(values, transform, "EPSG:32636")
    assert dst_t.e < 0 and dst_t.b == 0 and dst_t.d == 0   # north-up, no rotation
    bounds = wx.web_bounds_lonlat(dst_t, *dst.shape)
    (south, west), (north, east) = bounds
    assert south < north and west < east
    assert 35.0 < west < 36.0 and 31.0 < south < 32.0
    assert np.isfinite(dst[dst.shape[0] // 2, dst.shape[1] // 2])


def test_mask_reprojection_stays_boolean_and_nearest():
    mask = np.zeros((40, 40), dtype=bool)
    mask[10:20, 10:20] = True
    transform = wx.grid_transform(np.arange(40) * 20.0 + 560000.0, np.arange(40)[::-1] * 20.0 + 3500000.0, 20.0)
    dst, _ = wx.reproject_to_web(mask, transform, "EPSG:32636", mask=True)
    assert dst.dtype == bool
    assert dst.any()
    assert set(np.unique(dst)).issubset({False, True})   # no fractional water


def test_ramp_endpoints_are_the_declared_colours():
    rgb = wx.ramp(np.array([0.0, 0.5, 1.0]))
    assert tuple(np.round(rgb[0]).astype(int)) == (0x3B, 0x82, 0xF6)
    assert tuple(np.round(rgb[1]).astype(int)) == (0xD9, 0xDE, 0xE8)
    assert tuple(np.round(rgb[2]).astype(int)) == (0xF5, 0x9E, 0x0B)


def test_ramp_clips_outside_zero_one():
    rgb = wx.ramp(np.array([-5.0, 5.0]))
    assert tuple(np.round(rgb[0]).astype(int)) == (0x3B, 0x82, 0xF6)
    assert tuple(np.round(rgb[1]).astype(int)) == (0xF5, 0x9E, 0x0B)


def test_grey_nan_is_transparent_not_black():
    values = np.array([[np.nan, -20.0], [-10.0, -15.0]], dtype="float32")
    image = np.array(wx.grey_rgba(values, -20.0, -10.0))
    assert image[0, 0, 3] == 0
    assert image[0, 1, 3] == 255
    assert image[0, 1, 0] == 0          # -20 dB is black
    assert image[1, 0, 0] == 255        # -10 dB is white


def test_change_nan_is_transparent_and_neutral_small_change_too():
    values = np.array([[np.nan, 0.1, 2.0]], dtype="float32")
    image = np.array(wx.change_rgba(values, 2.0, neutral_below_db=0.25))
    assert image[0, 0, 3] == 0      # NaN
    assert image[0, 1, 3] == 0      # |0.1| < 0.25: neutral, shows the imagery underneath
    assert image[0, 2, 3] > 0       # 2 dB: visible


def test_mask_palette_is_transparent_except_mask_pixels():
    mask = np.array([[True, False], [False, True]])
    image = wx.mask_palette(mask, wx.WATER_RGB, wx.WATER_ALPHA)
    rgba = np.array(image.convert("RGBA"))
    assert rgba[0, 0, 3] == wx.WATER_ALPHA
    assert rgba[0, 1, 3] == 0
    assert tuple(rgba[0, 0, :3]) == wx.WATER_RGB


def test_saved_png_is_optimised_and_readable(tmp_path):
    path = tmp_path / "t.png"
    size = wx.save_png(wx.grey_rgba(np.zeros((8, 8), dtype="float32"), -1, 1), path)
    assert size > 0 and path.stat().st_size == size
    with Image.open(path) as image:
        assert image.size == (8, 8)


def test_round_geojson_rounds_to_six_decimals():
    geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[35.1234567891, 31.1], [35.2, 31.2],
                                                         [35.2, 31.3], [35.1234567891, 31.1]]]},
        "properties": {"id": "P01"},
    }]}
    rounded = wx.round_geojson(geojson, decimals=6, simplify_deg=0)
    first = rounded["features"][0]["geometry"]["coordinates"][0][0]
    assert first == [35.123457, 31.1]


def test_write_js_is_ascii_and_assigns_to_window(tmp_path):
    path = tmp_path / "x.js"
    wx.write_js(path, "demo", {"name": "Dead Sea \u00e9 \u0627\u0644"})
    text = path.read_bytes()
    text.decode("ascii")  # raises if any non-ASCII byte
    assert text.startswith(b"window.VENUS = window.VENUS || {};")
    assert b'window.VENUS["demo"] = ' in text


def test_js_and_json_carry_identical_payload(tmp_path):
    payload = {"a": 1, "b": [1.5, "x"], "c": {"d": None}}
    wx.write_json(tmp_path / "p.json", payload)
    wx.write_js(tmp_path / "p.js", "p", payload)
    loaded = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    body = (tmp_path / "p.js").read_text(encoding="ascii").split("= ", 2)[-1].rstrip().rstrip(";")
    assert loaded == json.loads(body)


def test_assert_provisional_refuses_a_validated_layer():
    good = [{"id": "a", "crid": "P05023"}]
    bad = good + [{"id": "b", "crid": "P05036"}]
    wx.assert_provisional(good)
    with pytest.raises(SystemExit):
        wx.assert_provisional(bad)


def test_manifest_fields_the_validator_requires_are_listed_here():
    from importlib import util

    spec = util.spec_from_file_location("validate", Path(__file__).resolve().parents[1] / "scripts" / "06_validate_web_assets.py")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {"id", "crid", "bounds", "processing", "display_crs"} <= set(module.REQUIRED_FIELDS)


def test_rgb_decomposition_marks_invalid_pixels_black():
    copol = np.array([[0.2, 0.2]])
    crosspol = np.array([[0.02, 0.02]])
    invalid = np.array([[True, False]])
    rgb = wx.rgb_decomposition(copol, crosspol, invalid)
    assert tuple(rgb[0, 0]) == (0, 0, 0)
    assert rgb[0, 1].any()


def test_rgb_decomposition_calm_water_is_blue_dominant():
    # Calm water: moderate co-pol (about -14 dB) and very little cross-pol. The reference colour
    # description says calm water is blue, so blue should dominate green.
    rgb = wx.rgb_decomposition(np.array([[0.04]]), np.array([[0.0001]]), np.array([[False]]))
    red, green, blue = rgb[0, 0]
    assert blue > green
    assert blue > red


def test_rgb_decomposition_is_absolute_not_stretched():
    # Same inputs give the same colour regardless of the rest of the image: no per-image stretch.
    single = wx.rgb_decomposition(np.array([[0.3]]), np.array([[0.03]]), np.array([[False]]))
    crowd = wx.rgb_decomposition(np.array([[0.3, 5.0]]), np.array([[0.03, 0.5]]), np.array([[False, False]]))
    assert tuple(single[0, 0]) == tuple(crowd[0, 0])


def test_source_crs_is_respected_not_assumed():
    # A grid geocoded in UTM 37N over Azraq must land at Azraq (about 36.85 E), never one zone west.
    x = np.linspace(292430.0, 292430.0 + 19 * 20.0, 20)
    y = np.linspace(3529030.0, 3529030.0 - 19 * 20.0, 20)
    values = np.full((20, 20), -12.0, dtype="float32")
    transform = wx.grid_transform(x, y, 20.0)
    dst, dst_t = wx.reproject_to_web(values, transform, "EPSG:32637")
    (south, west), (north, east) = wx.web_bounds_lonlat(dst_t, *dst.shape)
    assert 36.7 < (west + east) / 2.0 < 37.0
    assert 31.7 < (south + north) / 2.0 < 32.0


def test_one_extent_for_every_layer_pixel_size():
    x = np.linspace(292430.0, 292430.0 + 99 * 20.0, 100)
    y = np.linspace(3529030.0, 3529030.0 - 99 * 20.0, 100)
    transform = wx.grid_transform(x, y, 20.0)
    extent_t, extent_w, extent_h = wx.web_grid(transform, "EPSG:32637", 100, 100)
    g60_t, g60_w, g60_h = wx.web_grid(transform, "EPSG:32637", 100, 100, target_res=60.0)
    g20_t, g20_w, g20_h = wx.web_grid(transform, "EPSG:32637", 100, 100, target_res=20.0)
    assert wx.web_bounds_lonlat(extent_t, extent_h, extent_w) == wx.web_bounds_lonlat(g60_t, g60_h, g60_w)
    assert wx.web_bounds_lonlat(extent_t, extent_h, extent_w) == wx.web_bounds_lonlat(g20_t, g20_h, g20_w)
    assert 10.0 < abs(g20_t.a) < 20.0 * 1.2


def test_every_built_place_is_georeferenced_and_layers_share_bounds():
    from venus.config import REPO_ROOT, load_study_area
    from pyproj import Geod
    from shapely import wkt as shapely_wkt
    from shapely.geometry import Point
    from shapely.ops import nearest_points

    manifests = sorted((REPO_ROOT / "web").glob("data/*/manifest.json"))
    if not manifests:
        pytest.skip("no built places")
    geod = Geod(ellps="WGS84")
    failures = []
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        area = load_study_area(path.parent.name)
        bbox = shapely_wkt.loads(area.wkt)
        (south, west), (north, east) = manifest["bounds"]
        point = Point((west + east) / 2.0, (south + north) / 2.0)
        if not bbox.contains(point):
            nearest = nearest_points(bbox, point)[0]
            km = geod.inv(nearest.x, nearest.y, point.x, point.y)[2] / 1000.0
            if km > 5.0:
                failures.append(f"{path.parent.name} centre {km:.1f} km outside AOI")
        shared = {json.dumps(layer["bounds"]) for layer in manifest["layers"]}
        if len(shared) > 1:
            failures.append(f"{path.parent.name} has {len(shared)} distinct bounds")
    assert not failures, failures
