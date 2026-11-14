"""Tests for the NISAR grid geometry helpers.

No network, no HDF5: these check the index arithmetic that decides which pixels we read from a
1.9 GB product. Getting this wrong silently shifts our imagery by kilometres.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.nisar import _coverage_slice  # noqa: E402


def test_ascending_axis_covers_the_request():
    xs = 500000.0 + 20.0 * np.arange(100)  # 20 m spacing, eastwards
    sl = _coverage_slice(xs, 500400.0, 501000.0)
    assert xs[sl][0] <= 500400.0
    assert xs[sl][-1] >= 501000.0


def test_descending_axis_covers_the_request():
    # Real NISAR yCoordinates run north -> south with -20 m spacing.
    ys = 3566000.0 - 20.0 * np.arange(100)  # last pixel centre is 3564020
    sl = _coverage_slice(ys, 3564200.0, 3564600.0)
    window = ys[sl]
    assert window.max() >= 3564600.0
    assert window.min() <= 3564200.0


def test_request_past_the_data_edge_is_clipped_to_what_exists():
    # Asking for ground below the last row must clip, never invent rows or wrap around.
    ys = 3566000.0 - 20.0 * np.arange(100)
    sl = _coverage_slice(ys, 3563000.0, 3564100.0)
    assert sl.stop == 100
    assert ys[sl].min() == pytest.approx(3564020.0)


def test_request_beyond_the_edge_is_clipped_not_wrapped():
    xs = 500000.0 + 20.0 * np.arange(10)
    sl = _coverage_slice(xs, 400000.0, 900000.0)
    assert (sl.start, sl.stop) == (0, 10)


def test_reversed_bounds_are_accepted():
    xs = 500000.0 + 20.0 * np.arange(100)
    forward = _coverage_slice(xs, 500400.0, 501000.0)
    reversed_ = _coverage_slice(xs, 501000.0, 500400.0)
    assert (forward.start, forward.stop) == (reversed_.start, reversed_.stop)


def test_slice_is_never_empty():
    xs = 500000.0 + 20.0 * np.arange(100)
    sl = _coverage_slice(xs, 500500.2, 500500.3)  # inside a single pixel
    assert sl.stop > sl.start
