"""Series integrity and mosaic tests: no maturity or CRID is ever mixed inside a series."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT  # noqa: E402
from venus.mosaic import mosaic_items  # noqa: E402


def _item(x0, y0, rows, cols, value, valid=True):
    x = np.arange(cols) * 20.0 + x0
    y = y0 - np.arange(rows) * 20.0
    array = np.full((rows, cols), value, dtype="float32")
    mask = np.full((rows, cols), 1 if valid else 255, dtype="uint8")
    return {"meta": {"frame": value}, "x": x, "y": y, "arrays": {"HV": array}, "mask": mask, "stem": str(value)}


def test_mosaic_fills_a_corner_from_the_second_frame():
    left = _item(0.0, 0.0, 10, 10, 1.0)
    # Second frame is shifted east by eight pixels and invalid on its west edge.
    right = _item(160.0, 0.0, 10, 10, 2.0, valid=True)
    right["mask"][:, :2] = 255
    out = mosaic_items([left, right])
    hv = out["arrays"]["HV"]
    mask = out["mask"]
    assert hv.shape[0] == 10
    assert np.isfinite(hv).all()
    # The overlap is the mean of the two valid frames; the east extension comes from frame 2 only.
    assert hv[0, 8] == pytest.approx(1.5)
    assert hv[0, 17] == pytest.approx(2.0)
    assert (mask == 1).all()


def test_mosaic_single_item_is_returned_unchanged():
    item = _item(0.0, 0.0, 4, 4, 3.0)
    assert mosaic_items([item]) is item


def test_every_built_place_keeps_series_integrity():
    manifests = sorted((REPO_ROOT / "web" / "data").glob("*/manifest.json"))
    if not manifests:
        pytest.skip("no built places")
    problems = []
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        series = {row["id"]: row for row in manifest.get("series", [])}
        if not series:
            continue  # legacy single-series bundle from v2
        for layer in manifest["layers"]:
            sid = layer.get("series")
            if sid not in series:
                problems.append(f"{path.parent.name}/{layer['id']} has no declared series")
            elif layer.get("crid") != series[sid].get("crid"):
                problems.append(f"{path.parent.name}/{layer['id']} CRID {layer.get('crid')} != {series[sid].get('crid')}")
        stats_path = path.parent / "water_stats.json"
        if stats_path.exists():
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            if stats.get("series") and stats["series"] not in series:
                problems.append(f"{path.parent.name}/water_stats names unknown series {stats['series']}")
    assert not problems, problems
