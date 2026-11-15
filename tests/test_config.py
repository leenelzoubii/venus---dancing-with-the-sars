"""Tests for the config loader. Fast, offline, no data needed."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import StudyArea, load_study_area, short_wkt  # noqa: E402


def test_active_aoi_loads_by_default():
    area = load_study_area()
    # v3 makes the whole-lake window the default place; the east-shore strip remains available.
    assert area.name == "dead_sea_full"
    assert area.wkt.startswith("POLYGON((")
    assert area.search["processing_level"] == "GCOV"


def test_named_aoi():
    area = load_study_area("dead_sea_east")
    assert area.title.startswith("Dead Sea")


def test_unknown_aoi_raises_with_hint():
    with pytest.raises(KeyError) as excinfo:
        load_study_area("atlantis")
    assert "dead_sea_east" in str(excinfo.value)


def test_adhoc_wkt_overrides_config():
    area = load_study_area(wkt="POLYGON((0 0, 1 0, 1 1, 0 0))")
    assert isinstance(area, StudyArea)
    assert area.name == "adhoc"
    assert "0 0" in area.wkt


def test_search_kwargs_are_asf_search_camel_case():
    kwargs = load_study_area().as_search_kwargs()
    assert kwargs["dataset"] == "NISAR"
    assert kwargs["processingLevel"] == "GCOV"
    assert kwargs["dataMaturity"] == "PROVISIONAL"
    assert kwargs["intersectsWith"].startswith("POLYGON")


def test_short_wkt_truncates():
    long = "POLYGON((" + ", ".join(f"{i}.0 {i}.0" for i in range(50)) + "))"
    assert len(short_wkt(long, 40)) <= 40
    assert short_wkt(long, 40).endswith("...")
