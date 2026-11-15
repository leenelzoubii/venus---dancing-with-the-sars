"""Step 21 - fetch tier 1 for every processed place: its own cached geometry, every maturity.

Reads web/data/places.json at runtime. For each place it takes the track/direction/frames actually
present in data/raw/subsets/<place>/, finds every BETA / PROVISIONAL / VALIDATED acquisition for that
geometry in data/interim/scenes_<place>_all.csv, and fetches the missing dates with 03b (HV only for
dual-pol places, HH for HH-only places). Three workers, 8 min per frame, one retry, resumable, atomic.

    python scripts/21_fetch_tier1.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT  # noqa: E402

PY = sys.executable
SUBSETS = REPO_ROOT / "data" / "raw" / "subsets"
INTERIM = REPO_ROOT / "data" / "interim"
LOG = INTERIM / "fetch.log"
OVERALL_DEADLINE = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
PER_FRAME_TIMEOUT = 480


def log(line: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {line}\n")


def cached_geometry(place: str) -> dict:
    metas = []
    for sidecar in sorted((SUBSETS / place).glob("*.json")):
        try:
            metas.append(json.loads(sidecar.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    track = Counter(int(m.get("track", 0)) for m in metas).most_common(1)[0][0]
    direction = Counter(str(m.get("direction", "")) for m in metas).most_common(1)[0][0]
    frames = Counter(int(m.get("frame", 0)) for m in metas if int(m.get("track", 0)) == track)
    present = set()
    for sidecar in (SUBSETS / place).glob("*.json"):
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        present.add((meta.get("acquisition_date"), int(meta.get("frame", 0))))
    return {"track": track, "direction": direction,
            "frames": [frame for frame, _ in frames.most_common(2)],
            "present": present}


def plan_place(place: str) -> list[dict]:
    geom = cached_geometry(place)
    csv = INTERIM / f"scenes_{place}_all.csv"
    if not csv.exists():
        csv = INTERIM / f"scenes_{place}.csv"
    if not csv.exists():
        log(f"{place}: no scenes CSV, skipped")
        return []
    frame = pd.read_csv(csv, parse_dates=["acquisition_date"])
    frame["day"] = frame["acquisition_date"].dt.strftime("%Y-%m-%d")
    subset = frame[(frame["track"] == geom["track"])
                   & (frame["direction"].str.upper().str[:4] == str(geom["direction"]).upper()[:4])
                   & (frame["frame"].isin(geom["frames"]))
                   & (frame["maturity"].isin(["BETA", "PROVISIONAL", "VALIDATED"]))]
    if subset.empty:
        log(f"{place}: no rows for geometry {geom['track']}/{geom['frames']}/{geom['direction']}")
        return []
    # One row per (date, frame): keep the newest CRID; X05010 supersedes X05009 where both exist.
    subset = subset.sort_values(["crid", "day"]).drop_duplicates(["day", "frame"], keep="last")
    hv_place = "HV" in "".join(frame["polarizations"].dropna().astype(str).unique())
    pol = "HV" if hv_place else "HH"
    tasks = []
    for _, row in subset.iterrows():
        # Skip only a frame that is already cached; a date with one frame missing is fetched again
        # so the mosaic can become complete, or is kept as PARTIAL if the retry fails (R2).
        if (row["day"], int(row["frame"])) in geom["present"]:
            continue
        tasks.append({"place": place, "track": geom["track"], "frame": int(row["frame"]),
                      "direction": geom["direction"], "day": row["day"], "pol": pol,
                      "crid": row["crid"]})
    return tasks


def run_task(task: dict) -> tuple[str, bool]:
    stack = f"{task['track']}/{task['frame']}/DESC" if str(task["direction"]).upper().startswith("D") \
        else f"{task['track']}/{task['frame']}/ASC"
    csv = INTERIM / f"fetch_{task['place']}.csv"
    command = [PY, "-u", "scripts/03b_fetch_fast.py", "--aoi", task["place"], "--scenes", str(csv),
               "--stack", stack, "--dates", task["day"], "--polarizations", task["pol"]]
    for attempt in (1, 2):
        try:
            result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True,
                                    timeout=PER_FRAME_TIMEOUT)
            if result.returncode == 0 and "px in" in (result.stdout + result.stderr):
                return f"{task['place']} {task['day']} {stack} {task['pol']} ok", True
        except subprocess.TimeoutExpired:
            pass
        if attempt == 1:
            time.sleep(20)
    return f"{task['place']} {task['day']} {stack} FAILED", False


def main() -> int:
    places = [p["name"] for p in
              json.loads((REPO_ROOT / "web" / "data" / "places.json").read_text(encoding="utf-8"))["places"]
              if p.get("processed")]
    all_tasks = []
    for place in places:
        tasks = plan_place(place)
        if not tasks:
            continue
        frame = pd.read_csv(INTERIM / f"scenes_{place}_all.csv", parse_dates=["acquisition_date"]) \
            if (INTERIM / f"scenes_{place}_all.csv").exists() else None
        if frame is not None:
            frame.to_csv(INTERIM / f"fetch_{place}.csv", index=False)
        log(f"{place}: {len(tasks)} date(s) to fetch")
        all_tasks.extend(tasks)
    log(f"TOTAL {len(all_tasks)} fetch(es)")
    done = 0
    failures = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(run_task, task): task for task in all_tasks}
        for future in as_completed(futures):
            if datetime.now(timezone.utc) > OVERALL_DEADLINE:
                log("DEADLINE reached, stopping")
                break
            message, ok = future.result()
            done += 1
            failures += 0 if ok else 1
            log(f"[{done}/{len(all_tasks)}] {message}")
    log(f"DONE fetched={done - failures} failed={failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
