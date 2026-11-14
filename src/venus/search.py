"""Search ASF for NISAR products and organise them into comparable stacks.

The hard rule this module enforces: **only compare scenes with the same track, frame and flight
direction.** Everything else is a different viewing geometry, and geometry differences look exactly
like ground change.

Also handled here, because the archive really contains these:

* duplicate products for the same acquisition (e.g. ``..._001`` and ``..._002``) — keep the most
  recently *processed* one;
* data maturity levels (BETA / PROVISIONAL / VALIDATED) — they are not comparable to each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

# NISAR naming convention (verified against the NISAR Data User Guide, "Naming Conventions"):
#   NISAR_<I><L>_<PT>_<PROD>_<CYL>_<REL>_<P>_<FRM>_<MODE>_<POLE>_<S>_<Start>_<End>_<CRID>_<A>_<C>_<LOC>_<CTR>
#   0     1      2     3      4     5     6   7     8      9      10  11      12    13     14 15  16    17
GRANULE_RE = re.compile(
    r"^(?P<mission>NISAR)_(?P<level>[LS][0-9])_(?P<ptype>[A-Z]{2})_(?P<prod>[A-Z]{4})_"
    r"(?P<cycle>[0-9]{3})_(?P<rel_orbit>[0-9]{3})_(?P<direction>[AD])_(?P<frame>[0-9]{3})_"
    r"(?P<mode>[0-9A-Z]{4})_(?P<pol>[A-Z]{4})_(?P<source>[A-Z])_(?P<start>[0-9T]{15})_"
    r"(?P<end>[0-9T]{15})_(?P<crid>[A-Z][0-9]{5})_(?P<accuracy>[A-Z])_(?P<coverage>[A-Z])_"
    r"(?P<location>[A-Z])_(?P<counter>[0-9]{3})$"
)

# Polarization two-letter codes -> human labels (user guide, "POLE" term).
POL_CODES = {
    "SH": "HH",
    "SV": "VV",
    "DH": "HH+HV",
    "DV": "VV+VH",
    "CL": "LH+LV",
    "CR": "RH+RV",
    "QP": "HH+HV+VV+VH",
    "NA": "-",
}

MATURITY_BY_COLLECTION = {
    "NISAR_L2_GCOV_V1": "VALIDATED",
    "NISAR_L2_GCOV_PROVISIONAL_V1": "PROVISIONAL",
    "NISAR_L2_GCOV_BETA_V1": "BETA",
    "NISAR_L1_RSLC_V1": "VALIDATED",
    "NISAR_L1_RSLC_PROVISIONAL_V1": "PROVISIONAL",
    "NISAR_L1_RSLC_BETA_V1": "BETA",
}


@dataclass
class Stack:
    """All acquisitions sharing one viewing geometry, sorted in time."""

    track: int
    frame: int
    direction: str
    dates: list[pd.Timestamp] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.track}/{self.frame:03d}/{self.direction}"

    def __str__(self) -> str:
        return f"{self.key:<18} {len(self.dates):>2} date(s)"


def parse_granule_name(name: str) -> dict[str, Any]:
    """Split a NISAR granule name into its named fields. Returns {} if it does not parse."""
    m = GRANULE_RE.match(name)
    if not m:
        return {}
    d = m.groupdict()
    pol_code = d["pol"]
    d["polarizations"] = "+".join(
        POL_CODES.get(pol_code[i : i + 2], pol_code[i : i + 2]) for i in (0, 2)
    )
    d["acquisition_date"] = pd.to_datetime(d["start"], format="%Y%m%dT%H%M%S", utc=True)
    d["track"] = int(d["rel_orbit"])
    d["frame_num"] = int(d["frame"])
    d["direction_word"] = "DESCENDING" if d["direction"] == "D" else "ASCENDING"
    return d


def maturity_from_url(url: str) -> str:
    """Data maturity implied by the Earthdata Cloud collection in the download URL."""
    for collection, maturity in MATURITY_BY_COLLECTION.items():
        if f"/{collection}/" in url:
            return maturity
    if "PROVISIONAL" in url:
        return "PROVISIONAL"
    if "BETA" in url:
        return "BETA"
    return "UNKNOWN"


def _first(props: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present, non-empty property among ``keys``."""
    for k in keys:
        if k in props and props[k] not in (None, "", []):
            return props[k]
    return default


def results_to_frame(results: Iterable[Any]) -> pd.DataFrame:
    """Convert an ``asf_search`` result list into a tidy DataFrame (one row per product file)."""
    rows: list[dict[str, Any]] = []
    for product in results:
        props: dict[str, Any] = dict(getattr(product, "properties", {}) or {})
        name = _first(props, "granuleName", "productName", "fileID", default="") or ""
        parsed = parse_granule_name(name)

        # Some NISAR products are exposed with zero-padded track/frame as strings; trust the
        # granule name when it parsed, otherwise fall back to the metadata fields.
        track = parsed.get("track") or _first(props, "pathNumber", "trackNumber")
        frame = parsed.get("frame_num") or _first(props, "frameNumber")
        direction = parsed.get("direction_word") or _first(props, "flightDirection")

        url = _first(props, "url", "downloadUrl", default="") or ""
        size_mb = _first(props, "bytes", "sizeMB")
        if isinstance(size_mb, (int, float)) and size_mb > 1e5:  # bytes -> MB
            size_mb = round(size_mb / (1024 * 1024), 2)

        rows.append(
            {
                "granule": name,
                "acquisition_date": parsed.get("acquisition_date") or _first(props, "startTime"),
                "track": int(track) if track is not None else None,
                "frame": int(frame) if frame is not None else None,
                "direction": direction,
                "polarizations": parsed.get("polarizations") or _first(props, "polarization"),
                "product_type": _first(props, "processingLevel", "productType"),
                "maturity": maturity_from_url(url) if url else "UNKNOWN",
                "crid": parsed.get("crid"),
                "size_mb": size_mb,
                "processing_date": _first(props, "processingDate"),
                "url": url,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["acquisition_date"] = pd.to_datetime(df["acquisition_date"], utc=True, errors="coerce")
    df["processing_date"] = pd.to_datetime(df["processing_date"], utc=True, errors="coerce")
    df["acq_day"] = df["acquisition_date"].dt.strftime("%Y-%m-%d")
    return df


def dedupe_latest(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one product per (track, frame, direction, acquisition day).

    Reprocessed duplicates share the acquisition timestamp but differ in ``processing_date``;
    the most recently processed file is the one we want.
    """
    if df.empty:
        return df
    ordered = df.sort_values(["track", "frame", "direction", "acq_day", "processing_date"])
    deduped = ordered.drop_duplicates(
        subset=["track", "frame", "direction", "acq_day"], keep="last"
    )
    return deduped.sort_values(["track", "frame", "direction", "acquisition_date"]).reset_index(
        drop=True
    )


def summarise_stacks(df: pd.DataFrame) -> list[Stack]:
    """Group a deduped frame into comparable stacks, sorted by date."""
    stacks: list[Stack] = []
    if df.empty:
        return stacks
    for (track, frame, direction), group in df.groupby(["track", "frame", "direction"]):
        stacks.append(
            Stack(
                track=int(track),
                frame=int(frame),
                direction=str(direction),
                dates=sorted(group["acquisition_date"].dropna().tolist()),
            )
        )
    stacks.sort(key=lambda s: (-len(s.dates), s.key))
    return stacks


def pick_stack(df: pd.DataFrame, track: int, frame: int, direction: str) -> pd.DataFrame:
    """Restrict a frame to exactly one geometry; raises if that geometry is absent."""
    direction = direction.upper()
    mask = (df["track"] == track) & (df["frame"] == frame) & (df["direction"] == direction)
    subset = df[mask]
    if subset.empty:
        available = sorted({f"{r.track}/{r.frame:03d}/{r.direction}" for r in summarise_stacks(df)})
        raise ValueError(
            f"No products for {track}/{frame:03d}/{direction}. Available stacks: {available}"
        )
    return subset.sort_values("acquisition_date").reset_index(drop=True)
