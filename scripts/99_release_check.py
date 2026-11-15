"""Release gate. Exits non-zero if anything a public repository must not ship is present, or if a
documented check fails. Prints an ASCII summary only.

    python scripts/99_release_check.py

Checks
  1. no credentials, venv, raw HDF5 or interim arrays tracked (working tree AND history)
  2. pytest passes
  3. web asset validator passes
  4. web structure check passes
  5. total published web size under budget
  6. digits in user-visible strings listed for manual review (they must trace to data files)
  7. no non-ASCII in Python print statements (Windows console safety)
  8. README links resolve, LICENSE present
  9. every layer reports the PROVISIONAL CRID
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT  # noqa: E402

PY = sys.executable
WEB = REPO_ROOT / "web"
BUDGET_MB = 220.0
FORBIDDEN_TRACKED = re.compile(
    r"(\.netrc$|_netrc$|\.venv/|\.env$|\.h5$|\.hdf5$|\.npy$|\.tif$|\.tiff$|data/raw/|data/interim/)"
)
VALID_CRIDS = {"P05023", "P05036", "OPERA"}


def run(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def git(*args: str) -> str:
    code, out = run(["git", *args])
    return out if code == 0 else ""


def main() -> int:
    failures: list[str] = []
    passes: list[str] = []

    def check(ok: bool, message: str) -> None:
        (passes if ok else failures).append(message)

    # 1. nothing forbidden in the working tree or the history
    tracked = [p for p in git("ls-files").splitlines() if FORBIDDEN_TRACKED.search(p) and not p.endswith(".gitkeep")]
    check(not tracked, f"no credentials/data/venv tracked ({tracked[:3] or 'clean'})")
    history = git("log", "--all", "--pretty=format:", "--name-only").splitlines()
    bad_history = sorted({p for p in history if FORBIDDEN_TRACKED.search(p) and not p.endswith(".gitkeep")})
    check(not bad_history, f"no credentials/data ever committed ({bad_history[:3] or 'clean'})")

    # 2-4. the three suites
    code, out = run([PY, "-m", "pytest", "-q"])
    check(code == 0, "pytest passes" if code == 0 else f"pytest FAILED: {out.splitlines()[-1] if out else ''}")
    code, out = run([PY, "scripts/06_validate_web_assets.py"])
    check(code == 0, "web asset validator passes" if code == 0 else "web asset validator FAILED")
    code, out = run([PY, "scripts/07_check_web.py"])
    check(code == 0, "web structure check passes" if code == 0 else "web structure check FAILED")

    # 5. size
    total_mb = sum(f.stat().st_size for f in WEB.rglob("*") if f.is_file()) / 1e6
    check(total_mb < BUDGET_MB, f"published web size {total_mb:.1f} MB < {BUDGET_MB:.0f} MB")

    # 6. digits in user-visible strings, for manual tracing
    strings = (WEB / "js" / "strings.js").read_text(encoding="utf-8")
    with_digits = [
        line.strip()[:110] for line in strings.splitlines()
        if re.search(r"\d", line) and ":" in line
    ]

    # 7. ASCII-only Python output
    offenders = []
    for script in sorted((REPO_ROOT / "scripts").glob("*.py")):
        text = script.read_text(encoding="utf-8")
        for line in text.splitlines():
            if re.search(r"(print|log|warn)\(", line) and re.search(r"[^\x00-\x7f]", line):
                offenders.append(script.name)
                break
    check(not offenders, f"Python print statements are ASCII ({sorted(set(offenders)) or 'clean'})")

    # 8. README links and licence
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    local_links = re.findall(r"\]\((?!https?://|#)([^)]+)\)", readme)
    missing = [link for link in local_links if not (REPO_ROOT / link.split("#")[0]).exists()]
    check(not missing, f"README local links resolve ({missing[:3] or 'all ok'})")
    check((REPO_ROOT / "LICENSE").exists(), "LICENSE present")

    # 9. valid CRID
    wrong = []
    for manifest in (WEB / "data").glob("*/manifest.json"):
        import json
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("crid") not in VALID_CRIDS:
            wrong.append(f"{manifest.parent.name}:{data.get('crid')}")
    check(not wrong, f"every place manifest has valid CRID ({VALID_CRIDS}) ({wrong or 'all ok'})")

    for item in passes:
        print(f"PASS  {item}")
    for item in failures:
        print(f"FAIL  {item}")

    if with_digits:
        print("\nREVIEW these user-visible strings containing digits (must trace to data files):")
        for line in with_digits:
            print(f"  {line}")

    print(f"\n{len(passes)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
