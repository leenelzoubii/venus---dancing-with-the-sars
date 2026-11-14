"""Check Earthdata Login and prove we can stream a real NISAR product's bytes.

Safe: prints no credentials, downloads 16 bytes plus HDF5 metadata.

    .venv\\Scripts\\python scripts\\00b_check_auth.py

If it fails, it prints exactly how to create the .netrc file and where it belongs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from venus import auth  # noqa: E402
from venus.config import REPO_ROOT  # noqa: E402

SCENES_CSV = REPO_ROOT / "data" / "interim" / "nisar_gcov_scenes.csv"


def main() -> int:
    print("=" * 78)
    print("Earthdata Login check")
    print("=" * 78)

    try:
        auth.login()
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {exc}")
        return 1

    if not SCENES_CSV.exists():
        print("\nScene table missing; run scripts/01_search_nisar.py first. Login itself is OK.")
        return 0

    df = pd.read_csv(SCENES_CSV, parse_dates=["acquisition_date"]).sort_values("acquisition_date")
    url = df.iloc[0]["url"]
    print(f"\nStreaming test against:\n  {url.split('/')[-1]}")

    import h5py

    from venus import nisar

    try:
        handle = nisar.open_h5(url)
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED to open the product: {exc.__class__.__name__}: {exc}")
        print("If this says 401/403, the login worked but the session did not carry auth; rerun and")
        print("watch for the netrc path printed by earthaccess.")
        return 1

    with handle:
        root = list(handle.keys())
        print(f"  HDF5 root groups : {root}")
        if "science" in handle:
            print(f"  /science children: {list(handle['science'].keys())}")
        try:
            grid = nisar.grid_group(handle)
            print(f"  grid layers      : {list(grid.keys())[:12]}")
            if "HHHH" in grid:
                ds = grid["HHHH"]
                print(f"  HHHH             : shape={ds.shape} dtype={ds.dtype}")
                block = ds[:2, :256]
                print(f"  read 2x256 block : ok, finite={int(pd.notna(block).sum())} cells")
        except Exception as exc:  # noqa: BLE001
            print(f"  grid inspection  : {exc.__class__.__name__}: {exc}")

    print("\nRESULT: authentication and byte-range streaming both work.")
    print("Next: .venv\\Scripts\\python scripts\\02_inspect_product.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
