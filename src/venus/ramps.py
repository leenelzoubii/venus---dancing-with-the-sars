"""Single source of truth for every colour ramp (v4).

The Python renderer (``webexport``) and the web legend both read these values. The build exports them
to ``web/data/ramps.json``/``ramps.js`` so no colour is hard-coded twice. Hex strings are for the
browser; the tuples are what PIL draws with.
"""

from __future__ import annotations

from . import webexport as wx

# Kind names that the web app must be able to explain, one legend entry each.
LEGEND_KINDS = ["rgb", "single_pol", "backscatter", "change", "water", "band", "patches", "context"]


def payload() -> dict:
    def stops(values):
        return [{"value": value, "rgb": [int(c) for c in colour]} for value, colour in values]

    return {
        "version": 1,
        "change": {
            "stops": stops(wx.CHANGE_STOPS),
            "hex": ["#3B82F6", "#D9DEE8", "#F59E0B"],
        },
        "single_pol": {
            "stops": stops(wx.SINGLE_POL_STOPS),
            "hex": ["#1E3C96", "#28965A", "#E68C28", "#F0DC3C"],
        },
        "grey": {"min": "#05070D", "max": "#F4F6FB", "unit": "dB"},
        "water": {"rgb": list(wx.WATER_RGB), "hex": "#22D3EE", "alpha": wx.WATER_ALPHA},
        "band": {"rgb": list(wx.BAND_RGB), "hex": "#FACC15", "alpha": wx.BAND_ALPHA},
        "patches": {"outline": "#E2B862", "hypothesis_label": True},
        "context": {"hex": "#8899AA", "source": "NASA GIBS / Worldview"},
        "kinds": LEGEND_KINDS,
    }
