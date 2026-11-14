"""One-off availability check: which NISAR product levels exist for each place?

Answers a scoping question before any long download: GSLC, GUNW, RSLC and GCOV are different products,
and the radar pipeline in this repository reads GCOV only. This script only searches; nothing is fetched.

    python scripts/01c_level_availability.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import auth, search  # noqa: E402
from venus.config import REPO_ROOT, load_study_area  # noqa: E402

PLACES = ["potash_city", "azraq_wetland", "melehat_sdom", "wadi_rum", "alwehda_dam"]
LEVELS = ["GCOV", "GSLC", "GUNW", "RSLC"]


def main() -> int:
    auth.login()
    import asf_search as asf

    print(f"{'place':16s} " + " ".join(f"{lvl:>6s}" for lvl in LEVELS))
    for name in PLACES:
        area = load_study_area(name)
        counts = []
        for level in LEVELS:
            kwargs = area.as_search_kwargs()
            kwargs.pop("relativeOrbit", None)
            kwargs.pop("frame", None)
            kwargs.pop("flightDirection", None)
            kwargs["processingLevel"] = level
            try:
                results = asf.search(**kwargs)
                frame = search.dedupe_latest(search.results_to_frame(results))
                counts.append(f"{len(frame):6d}")
            except Exception as exc:  # noqa: BLE001
                counts.append(f"{type(exc).__name__[:6]:>6s}")
        print(f"{name:16s} " + " ".join(counts))
    print("\nCounts are unique acquisitions intersecting the AOI (all tracks, PROVISIONAL).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
