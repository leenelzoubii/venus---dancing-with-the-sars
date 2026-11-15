"""Legend single-source-of-truth tests (v4): the web ramp equals the renderer ramp."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import ramps, webexport as wx  # noqa: E402
from venus.config import REPO_ROOT  # noqa: E402


def _hex(colour) -> str:
    return "#{:02X}{:02X}{:02X}".format(*[int(c) for c in colour])


def test_ramp_payload_matches_the_renderer():
    payload = ramps.payload()
    change = [stop["rgb"] for stop in payload["change"]["stops"]]
    assert change == [[0x3B, 0x82, 0xF6], [0xD9, 0xDE, 0xE8], [0xF5, 0x9E, 0x0B]]
    assert [tuple(stop["rgb"]) for stop in payload["change"]["stops"]] == [
        stop[1] for stop in wx.CHANGE_STOPS
    ]
    assert [tuple(stop["rgb"]) for stop in payload["single_pol"]["stops"]] == [
        stop[1] for stop in wx.SINGLE_POL_STOPS
    ]
    assert tuple(payload["water"]["rgb"]) == wx.WATER_RGB
    assert tuple(payload["band"]["rgb"]) == wx.BAND_RGB
    assert payload["change"]["hex"][0] == _hex(wx.CHANGE_STOPS[0][1])


def test_every_exported_kind_is_declared():
    payload = ramps.payload()
    assert set(payload["kinds"]) == set(ramps.LEGEND_KINDS)


def test_web_payload_matches_the_python_ramps():
    path = REPO_ROOT / "web" / "data" / "ramps.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kinds"] == ramps.LEGEND_KINDS
    assert payload["change"]["hex"][0] == _hex(wx.CHANGE_STOPS[0][1])
    assert payload["single_pol"]["hex"][-1] == _hex(wx.SINGLE_POL_STOPS[-1][1])
