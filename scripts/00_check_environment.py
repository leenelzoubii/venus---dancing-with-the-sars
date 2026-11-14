"""Smoke test: import every dependency, print versions, exit non-zero on failure.

Run from the repo root:
    .venv\\Scripts\\python scripts\\00_check_environment.py

A green run means the environment is ready for the NISAR pipeline.
"""

from __future__ import annotations

import platform
import sys
import traceback
from importlib import import_module

# (module to import, display name)
PACKAGES: list[tuple[str, str]] = [
    ("asf_search", "asf_search"),
    ("earthaccess", "earthaccess"),
    ("fsspec", "fsspec"),
    ("aiohttp", "aiohttp"),
    ("h5py", "h5py"),
    ("h5netcdf", "h5netcdf"),
    ("netCDF4", "netCDF4"),
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("xarray", "xarray"),
    ("rioxarray", "rioxarray"),
    ("rasterio", "rasterio"),
    ("skimage", "scikit-image"),
    ("pandas", "pandas"),
    ("geopandas", "geopandas"),
    ("shapely", "shapely"),
    ("pyproj", "pyproj"),
    ("matplotlib", "matplotlib"),
    ("PIL", "pillow"),
    ("yaml", "pyyaml"),
    ("tqdm", "tqdm"),
    ("jupyterlab", "jupyterlab"),
    ("ipykernel", "ipykernel"),
    ("folium", "folium"),
]

# Things the pipeline needs to be able to do, not just import.
CHECKS: list[tuple[str, str]] = []


def check_gdal_driver() -> tuple[str, str]:
    """GDAL version shipped inside rasterio, and whether HDF5 reading is available."""
    import rasterio

    gdal = rasterio.__gdal_version__
    drivers = rasterio.drivers()
    names = sorted({name.split(" ")[0] for name in drivers.values()}) if isinstance(drivers, dict) else []
    have = [d for d in ("HDF5", "netCDF", "GTiff", "COG") if d in names]
    major_minor = tuple(int(p) for p in gdal.split(".")[:2])
    note = ""
    if "HDF5" not in names:
        note = "  <-- WARNING: no HDF5 driver; use NETCDF: prefix for /vsicurl/ reads"
    elif major_minor < (3, 13):
        note = "  <-- note: GDAL < 3.13, use NETCDF: prefix for NISAR /vsicurl/ reads"
    return f"GDAL {gdal} (rasterio {rasterio.__version__}), drivers: {', '.join(have)}{note}", ""


CHECKS.append(("gdal", ""))


def main() -> int:
    print("=" * 78)
    print("Team Venus - environment check")
    print("=" * 78)
    print(f"python    : {sys.version.split()[0]}  ({platform.python_implementation()})")
    print(f"executable: {sys.executable}")
    print(f"platform  : {platform.platform()}")
    print("-" * 78)

    failures: list[str] = []

    for module_name, label in PACKAGES:
        try:
            mod = import_module(module_name)
            version = getattr(mod, "__version__", None) or getattr(mod, "version", None) or "?"
            if not isinstance(version, str):
                version = getattr(version, "__version__", "?")
            print(f"  ok   {label:<14} {version}")
        except Exception as exc:  # noqa: BLE001 - we want the message, not a traceback
            failures.append(f"{label}: {exc.__class__.__name__}: {exc}")
            print(f"  FAIL {label:<14} {exc.__class__.__name__}: {exc}")

    print("-" * 78)
    try:
        msg, _ = check_gdal_driver()
        print(f"  ok   {msg}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"gdal: {exc.__class__.__name__}: {exc}")
        print(f"  FAIL gdal: {exc.__class__.__name__}: {exc}")

    print("-" * 78)
    if failures:
        print(f"RESULT: FAILED ({len(failures)} problem(s))")
        for f in failures:
            print(f"  - {f}")
        print()
        print("Smallest next step: check the pip output above for the failing wheel, then try")
        print("  .venv\\Scripts\\python -m pip install --only-binary=:all: <package>")
        return 1

    print("RESULT: OK - environment is ready.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # pragma: no cover
        traceback.print_exc()
        sys.exit(2)
