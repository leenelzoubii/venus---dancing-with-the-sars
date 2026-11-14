"""Configuration handling for the Venus NISAR pipeline.

One source of truth for study areas and search filters: ``config/study_area.yaml``.
Every script accepts ``--aoi <name>`` (a key from that file) or ``--aoi-wkt "POLYGON((...))"``
for a one-off area, so trying a new location never requires touching code.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "study_area.yaml"


@dataclass
class StudyArea:
    """A named area of interest plus the filters used to search for data over it."""

    name: str
    wkt: str
    title: str = ""
    story: str = ""
    search: dict[str, Any] = field(default_factory=dict)
    processing: dict[str, Any] = field(default_factory=dict)

    def as_search_kwargs(self) -> dict[str, Any]:
        """Translate the YAML search block into ``asf_search`` keyword arguments."""
        s = self.search
        kwargs: dict[str, Any] = {
            "dataset": s.get("dataset", "NISAR"),
            "processingLevel": s.get("processing_level", "GCOV"),
            "intersectsWith": self.wkt,
        }
        if s.get("data_maturity"):
            kwargs["dataMaturity"] = s["data_maturity"]
        if s.get("start"):
            kwargs["start"] = s["start"]
        if s.get("end"):
            kwargs["end"] = s["end"]
        return kwargs


def load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_study_area(
    name: str | None = None,
    wkt: str | None = None,
    path: Path | str = CONFIG_PATH,
) -> StudyArea:
    """Resolve a study area from the YAML config, or build one from an ad-hoc WKT."""
    cfg = load_config(path)
    search = cfg.get("search") or {}
    processing = cfg.get("processing") or {}
    aois = cfg.get("aois") or []

    if wkt:
        return StudyArea(
            name="adhoc",
            wkt=wkt,
            title="Ad-hoc AOI",
            search=search,
            processing=processing,
        )

    target = name or cfg.get("active_aoi")
    for entry in aois:
        if entry.get("name") == target:
            return StudyArea(
                name=entry["name"],
                wkt=entry["wkt"],
                title=entry.get("title", ""),
                story=(entry.get("story") or "").strip(),
                search=search,
                processing=processing,
            )

    known = ", ".join(a.get("name", "?") for a in aois)
    raise KeyError(f"Unknown AOI {target!r}. Known AOIs: {known}")


def add_aoi_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach the standard study-area flags to a script's argument parser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--aoi",
        help="Named AOI from config/study_area.yaml (default: the file's active_aoi).",
    )
    group.add_argument(
        "--aoi-wkt",
        help='Ad-hoc AOI, e.g. "POLYGON((35.5 31.3, 35.6 31.3, 35.6 31.5, 35.5 31.3))".',
    )


def short_wkt(wkt: str, max_len: int = 60) -> str:
    """Compact one-line WKT for printing."""
    flat = " ".join(wkt.split())
    return flat if len(flat) <= max_len else flat[: max_len - 3] + "..."


def __main__() -> None:  # pragma: no cover - convenience CLI
    """`python -m venus.config` prints the resolved study area."""
    ap = argparse.ArgumentParser(description="Show the resolved study area.")
    add_aoi_arguments(ap)
    args = ap.parse_args()
    area = load_study_area(args.aoi, args.aoi_wkt)
    print(f"name        : {area.name}")
    print(f"title       : {area.title}")
    print(f"wkt         : {short_wkt(area.wkt)}")
    print(f"search      : {area.as_search_kwargs()}")


if __name__ == "__main__":  # pragma: no cover
    __main__()
