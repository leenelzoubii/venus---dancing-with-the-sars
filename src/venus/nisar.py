"""Reading NISAR GCOV products.

GCOV is an HDF5 file. The parts we need are small:

    /science/LSAR/GCOV/grids/frequencyA/HHHH    real-valued gamma-0 power
    /science/LSAR/GCOV/grids/frequencyA/HVHV    real-valued gamma-0 power
    /science/LSAR/GCOV/grids/frequencyA/mask
    /science/LSAR/GCOV/grids/frequencyA/numberOfLooks
    /science/LSAR/GCOV/grids/frequencyA/rtcGammaToSigmaFactor

The file is ~1.9 GB, so we never read it whole: we open it over HTTPS with byte-range access and
read only a window of rows/columns. `h5py` needs a seekable file object; fsspec provides one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np

GCOV_BASE = "/science/LSAR/GCOV/grids"
POL_TO_DATASET = {"HH": "HHHH", "HV": "HVHV", "VV": "VVVV", "VH": "VHVH"}


@dataclass
class DatasetInfo:
    path: str
    shape: tuple[int, ...]
    dtype: str
    attrs: dict[str, Any]


def open_h5(url_or_path: str):
    """Open a NISAR HDF5 product, locally or by streaming over HTTPS (Earthdata auth)."""
    import h5py

    if url_or_path.startswith(("http://", "https://")):
        from venus import auth

        return h5py.File(auth.open_remote(url_or_path), "r")
    return h5py.File(url_or_path, "r")


def walk(node: Any, prefix: str = "/") -> Iterator[DatasetInfo]:
    """Yield every HDF5 dataset with its shape, dtype and attributes (bounds the output sensibly)."""
    import h5py

    for name, item in node.items():
        path = f"{prefix}{name}"
        if isinstance(item, h5py.Dataset):
            yield DatasetInfo(path, item.shape, str(item.dtype), dict(item.attrs))
        elif isinstance(item, h5py.Group):
            yield from walk(item, path + "/")


def group_info(node: Any) -> dict[str, Any]:
    return dict(node.attrs) if node is not None else {}


def grid_group(h5file: Any, frequency: str = "A") -> Any:
    """Return the ``grids/frequency<X>`` group, or raise with the groups that do exist."""
    base = f"{GCOV_BASE}/frequency{frequency}"
    if base not in h5file:
        available = list(h5file[GCOV_BASE].keys()) if GCOV_BASE in h5file else []
        raise KeyError(f"{base} not present. Available: {available}")
    return h5file[base]


def polarizations(h5file: Any, frequency: str = "A") -> list[str]:
    """Which backscatter layers this product actually contains."""
    grid = grid_group(h5file, frequency)
    present = [p for p, ds in POL_TO_DATASET.items() if ds in grid]
    return present


def projection(h5file: Any, frequency: str = "A") -> dict[str, Any]:
    """CRS and grid coordinates, as stored by the product (no guessing)."""
    grid = grid_group(h5file, frequency)
    out: dict[str, Any] = {}
    proj = grid.get("projection")
    if proj is not None:
        out["projection_attrs"] = dict(proj.attrs)
        for key in ("spatial_ref", "crs_wkt", "GeoTransform", "epsg_code", "grid_mapping_name"):
            if key in proj.attrs:
                value = proj.attrs[key]
                out[key] = value.decode() if isinstance(value, bytes) else value
        for name in proj:
            item = proj[name]
            if hasattr(item, "shape"):
                out[f"projection/{name}"] = {"shape": item.shape, "dtype": str(item.dtype)}
    for axis in ("xCoordinates", "yCoordinates", "xCoordinateSpacing", "yCoordinateSpacing"):
        if axis in grid:
            item = grid[axis]
            if hasattr(item, "shape") and len(item.shape) > 0:
                out[axis] = {
                    "shape": item.shape,
                    "first": float(item[0]),
                    "last": float(item[-1]),
                }
            else:
                out[axis] = float(item[()])
    return out


def read_window(
    h5file: Any,
    dataset: str,
    row_slice: slice,
    col_slice: slice,
    frequency: str = "A",
) -> np.ndarray:
    """Read a rectangular window from one layer, without touching the rest of the file."""
    grid = grid_group(h5file, frequency)
    return np.asarray(grid[dataset][row_slice, col_slice])


def window_to_indices(
    h5file: Any,
    bbox_wgs84: tuple[float, float, float, float],
    frequency: str = "A",
) -> tuple[slice, slice]:
    """Convert a lon/lat box into row/column slices of the UTM GCOV grid.

    The product grid is a regular UTM raster; we project the bbox corners into the product CRS with
    pyproj, then convert metres to pixel indices using the stored coordinate vectors.
    """
    from pyproj import CRS, Transformer

    grid = grid_group(h5file, frequency)
    proj_attrs = dict(grid["projection"].attrs) if "projection" in grid else {}
    wkt = proj_attrs.get("crs_wkt") or proj_attrs.get("spatial_ref")
    if isinstance(wkt, bytes):
        wkt = wkt.decode()
    if not wkt:
        raise KeyError("No CRS found in the product's projection group; cannot window by lon/lat.")

    xs = np.asarray(grid["xCoordinates"][:])
    ys = np.asarray(grid["yCoordinates"][:])

    transformer = Transformer.from_crs(CRS.from_user_input("EPSG:4326"), CRS.from_user_input(wkt), always_xy=True)
    west, south, east, north = bbox_wgs84
    lons, lats = [west, east, east, west], [south, south, north, north]
    px, py = transformer.transform(lons, lats)

    # yCoordinates typically run north -> south.
    descending_y = ys[0] > ys[-1]
    x0 = int(np.searchsorted(xs, max(min(px), xs.min())))
    x1 = int(np.searchsorted(xs, min(max(px), xs.max())))
    if descending_y:
        y0 = int(np.searchsorted(-ys, -min(max(py), max(ys[0], ys[-1]))))
        y1 = int(np.searchsorted(-ys, -max(min(py), min(ys[0], ys[-1]))))
    else:
        y0 = int(np.searchsorted(ys, max(min(py), ys.min())))
        y1 = int(np.searchsorted(ys, min(max(py), ys.max())))

    return slice(min(y0, y1), max(y0, y1) + 1), slice(min(x0, x1), max(x0, x1) + 1)
