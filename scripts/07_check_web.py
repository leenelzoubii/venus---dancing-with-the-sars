"""Step 7b - check the web app's static structure before opening it in a browser. Exit 1 on any failure.

    python scripts/07_check_web.py

Checks:
  1. every local file referenced by web/index.html (src and href) exists;
  2. every layer file named in web/data/manifest.json exists under web/data/;
  3. every user-visible string key used by the code and the page exists in web/js/strings.js (en block);
  4. every web/data/*.js wrapper is present and assigns to window.VENUS.
"""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus.config import REPO_ROOT  # noqa: E402

WEB = REPO_ROOT / "web"
DATA = WEB / "data"
# file stem -> key used in window.VENUS (the licence file is exposed as "license")
DATA_WRAPPERS = [("manifest", "manifest"), ("water_stats", "water_stats"), ("offsets", "offsets"),
                 ("patches", "patches"), ("places", "places"), ("license_and_attribution", "license")]
KEY_PATTERNS = [
    re.compile(r"""(?<![A-Za-z0-9_])t\(\s*["']([A-Za-z0-9_]+)["']"""),
    re.compile(r"""UI\.t\(\s*["']([A-Za-z0-9_]+)["']"""),
]


class RefCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.i18n_keys: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for name in ("src", "href"):
            value = attributes.get(name)
            if value and not value.startswith(("http://", "https://", "#", "data:", "mailto:")):
                self.refs.append(value)
        for name in ("data-i18n", "data-i18n-label"):
            if attributes.get(name):
                self.i18n_keys.append(attributes[name])


def english_keys() -> set[str]:
    text = (WEB / "js" / "strings.js").read_text(encoding="utf-8")
    block = text[text.index("en: {"):]
    return set(re.findall(r"^\s*([A-Za-z0-9_]+)\s*:", block, flags=re.MULTILINE))


def main() -> int:
    failures: list[str] = []
    passes: list[str] = []

    collector = RefCollector()
    collector.feed((WEB / "index.html").read_text(encoding="utf-8"))

    missing_refs = [ref for ref in collector.refs if not (WEB / ref.split("?")[0]).exists()]
    (failures if missing_refs else passes).append(
        f"local files referenced by index.html exist ({len(collector.refs)} checked)"
        + (f": missing {', '.join(missing_refs)}" if missing_refs else "")
    )

    manifest_paths = sorted(DATA.glob("*/manifest.json"))
    if manifest_paths:
        missing_layers = []
        total = 0
        for manifest_path in manifest_paths:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for layer in manifest["layers"]:
                total += 1
                for key in ("file", "preview"):
                    if not (manifest_path.parent / layer[key]).exists():
                        missing_layers.append(f"{manifest_path.parent.name}/{layer[key]}")
        (failures if missing_layers else passes).append(
            f"every manifest layer and preview file exists ({total} checked)"
            + (f": missing {', '.join(missing_layers[:5])}" if missing_layers else "")
        )
    else:
        failures.append("no web/data/<place>/manifest.json files are present")

    for stem, key in DATA_WRAPPERS:
        path = DATA / f"{stem}.js"
        ok = path.exists() and f'window.VENUS["{key}"]' in path.read_text(encoding="ascii", errors="replace")
        (passes if ok else failures).append(f"data wrapper {stem}.js assigns window.VENUS[\"{key}\"]")

    keys = english_keys()
    used: set[str] = set(collector.i18n_keys)
    for js in sorted((WEB / "js").glob("*.js")):
        if js.name == "strings.js":
            continue
        text = js.read_text(encoding="utf-8")
        for pattern in KEY_PATTERNS:
            used.update(pattern.findall(text))
    # Dynamic keys are built from a step number ("story_" + key + "_title"), so the bare prefix is allowed.
    dynamic = {"story_", "story_title_", "story_body_"}
    unknown = sorted(k for k in used if k not in keys and k not in dynamic)
    (failures if unknown else passes).append(
        f"every string key used in code is in strings.js ({len(used)} used)"
        + (f": unknown {', '.join(unknown)}" if unknown else "")
    )

    for item in passes:
        print(f"PASS  {item}")
    for item in failures:
        print(f"FAIL  {item}")
    print(f"\n{len(passes)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
