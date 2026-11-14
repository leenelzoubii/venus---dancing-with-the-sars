"""Loading the cached AOI stack, with the checks that make a 9-date series trustworthy.

Every downstream step (QC table, contact sheets, offsets, water masks, web export) needs the same
three things: the list of dates in chronological order, the arrays for one date, and a guarantee
that all dates sit on the *same grid*. Getting the grid wrong is the classic way to manufacture
change that is not there, so the equality check lives here rather than in each script.

Cached layout (written by ``scripts/03_fetch_subset.py``)::

    data/raw/subsets/<aoi>/<date>_<track>-<frame>-<DIR>.json      provenance sidecar
    data/raw/subsets/<aoi>/<date>_<track>-<frame>-<DIR>_HH.npy
    data/raw/subsets/<aoi>/<date>_<track>-<frame>-<DIR>_HV.npy
    data/raw/subsets/<aoi>/<date>_<track>-<frame>-<DIR>_looks.npy
    data/raw/subsets/<aoi>/<date>_<track>-<frame>-<DIR>_mask.npy
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import change
from .config import REPO_ROOT

SUBSET_ROOT = REPO_ROOT / "data" / "raw" / "subsets"
EXPECTED_EPSG = 32636
PROVISIONAL_CRIDS = {"P05023"}
VALIDATED_CRIDS = {"P05036"}


@dataclass(frozen=True)
class Scene:
    """One cached acquisition: its sidecar and the paths to its arrays."""

    date: str
    sidecar: Path
    meta: dict

    @property
    def stem(self) -> str:
        return self.sidecar.stem

    def array_path(self, suffix: str) -> Path:
        return self.sidecar.with_name(f"{self.stem}_{suffix}.npy")

    def array(self, suffix: str) -> np.ndarray:
        return np.load(self.array_path(suffix))

    def power(self, pol: str) -> np.ndarray:
        """gamma-0 linear power for HH or HV."""
        return np.load(self.array_path(pol.upper()))

    def db(self, pol: str, filter_method: str = "median", filter_size: int = 5) -> np.ndarray:
        """gamma-0 power -> dB, then speckle filter (NaN-aware)."""
        return change.speckle_filter(change.power_to_db(self.power(pol)), filter_method, filter_size)

    @property
    def looks(self) -> np.ndarray:
        return self.array("looks")

    @property
    def mask(self) -> np.ndarray:
        return self.array("mask")


def load_scenes(aoi: str) -> list[Scene]:
    """Every complete cached acquisition, oldest first. Incomplete dates are skipped, not guessed."""
    folder = SUBSET_ROOT / aoi
    if not folder.exists():
        raise SystemExit(f"No cached subsets in {folder}. Run scripts/03_fetch_subset.py first.")
    scenes = []
    for sidecar in sorted(folder.glob("*.json")):
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        scene = Scene(date=meta["acquisition_date"], sidecar=sidecar, meta=meta)
        needed = ["HH", "HV", "looks", "mask"]
        if all(scene.array_path(s).exists() for s in needed):
            scenes.append(scene)
    return sorted(scenes, key=lambda s: s.date)


def verify_grid(scenes: list[Scene], pixel_spacing_m: float = 20.0) -> dict:
    """Assert one grid, one CRS, one geometry, one maturity. Returns a summary for the report."""
    if not scenes:
        raise SystemExit("No complete scenes cached.")
    first = scenes[0]
    ref_shape = None
    problems: list[str] = []
    for scene in scenes:
        hh = scene.array_path("HH")
        if not hh.exists():
            problems.append(f"{scene.date}: HH missing")
            continue
        shape = tuple(scene.meta["layers"]["HH"]["shape"])
        ref_shape = ref_shape or shape
        if shape != ref_shape:
            problems.append(f"{scene.date}: shape {shape} != {ref_shape}")
        if tuple(scene.meta["rows"]) != tuple(first.meta["rows"]) or tuple(scene.meta["cols"]) != tuple(
            first.meta["cols"]
        ):
            problems.append(f"{scene.date}: window indices differ from {first.date}")
        if abs(float(scene.meta["pixel_spacing_m"]) - pixel_spacing_m) > 1e-6:
            problems.append(f"{scene.date}: pixel spacing {scene.meta['pixel_spacing_m']} m")
        if scene.meta.get("crs_wkt") != first.meta.get("crs_wkt"):
            problems.append(f"{scene.date}: CRS differs from {first.date}")
        if (scene.meta.get("track"), scene.meta.get("frame")) != (first.meta.get("track"), first.meta.get("frame")):
            problems.append(f"{scene.date}: track/frame differs")
        if str(scene.meta.get("direction", "")).upper()[:4] != str(first.meta.get("direction", "")).upper()[:4]:
            problems.append(f"{scene.date}: direction differs")
        if str(scene.meta.get("crid")) in VALIDATED_CRIDS:
            problems.append(f"{scene.date}: VALIDATED product {scene.meta.get('crid')} in a PROVISIONAL series")
        if str(scene.meta.get("crid")) not in PROVISIONAL_CRIDS:
            problems.append(f"{scene.date}: unexpected CRID {scene.meta.get('crid')}")
    return {
        "n_scenes": len(scenes),
        "first": first.date,
        "last": scenes[-1].date,
        "shape": ref_shape,
        "rows": tuple(first.meta["rows"]),
        "cols": tuple(first.meta["cols"]),
        "problems": problems,
    }
