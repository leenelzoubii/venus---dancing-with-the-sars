"""Step 11 - fetch every date for several places, unattended and resumable.

One place at a time: search its own geometry, write that place's scene list, then fetch every date as an
AOI window. Each step is already resumable (step 3 skips complete caches and retries failures), so
re-running this script after an interruption continues where it stopped.

Why windows and not full frames: a full GCOV frame is about 2.2 GB for HH+HV, and measured throughput
here is roughly 62 KB/s, so one full-frame date is about ten hours. An AOI window is a few hundred KB.

    python scripts/11_batch_fetch.py
    python scripts/11_batch_fetch.py --places azraq_wetland wadi_rum
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT  # noqa: E402

PYTHON = sys.executable
SCRIPTS = REPO_ROOT / "scripts"
INTERIM = REPO_ROOT / "data" / "interim"

# place -> stack, chosen from the coverage survey (data/interim/coverage_survey.csv).
PLACES = [
    ("potash_city", "100/17/ASC"),
    ("azraq_wetland", "50/72/DESC"),
    ("melehat_sdom", "100/17/ASC"),
    ("wadi_rum", "50/74/DESC"),
    ("alwehda_dam", "151/72/DESC"),
]


def run(command: list[str], label: str) -> bool:
    print(f"\n=== {label}")
    print("   " + " ".join(command))
    started = time.time()
    result = subprocess.run(command, cwd=REPO_ROOT)
    minutes = (time.time() - started) / 60.0
    ok = result.returncode == 0
    print(f"=== {label}: {'OK' if ok else 'FAILED'} in {minutes:.1f} min")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--places", nargs="+", help="Subset of place names.")
    args = ap.parse_args()

    chosen = [p for p in PLACES if not args.places or p[0] in args.places]
    failures = []
    for name, stack in chosen:
        scenes = INTERIM / f"scenes_{name}.csv"
        if not run(
            [PYTHON, str(SCRIPTS / "01_search_nisar.py"), "--aoi", name, "--out", str(scenes)],
            f"search {name}",
        ):
            failures.append(f"{name}: search")
            continue
        if not run(
            [PYTHON, str(SCRIPTS / "03b_fetch_fast.py"), "--aoi", name, "--stack", stack,
             "--all", "--scenes", str(scenes)],
            f"fetch {name} ({stack})",
        ):
            failures.append(f"{name}: fetch")

    print("\n=== batch summary")
    for name, stack in chosen:
        flag = "FAILED" if any(f.startswith(name) for f in failures) else "done"
        print(f"  {name:16s} {stack:14s} {flag}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
