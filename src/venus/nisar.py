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


def as_python(value: Any) -> Any:
    """h5py hands back numpy/bytes scalars; make them readable in JSON and print statements."""
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray) and value.shape == ():
        return as_python(value[()])
    return value


def crs_of(h5file: Any, frequency: str = "A") -> Any:
    """The product's CRS as a pyproj CRS, taken from the file itself.

    Verified shape of ``grids/frequencyA/projection`` in real NISAR GCOV products: it is a **scalar
    uint32 dataset whose value is the EPSG code** (32636 = WGS 84 / UTM zone 36N for the Dead Sea),
    and the CRS details live in its attributes (``spatial_ref`` WKT, ``grid_mapping_name``,
    ``epsg_code``, ...). It is not a group, so it must never be iterated over.
    """
    from pyproj import CRS

    grid = grid_group(h5file, frequency)
    if "projection" not in grid:
        raise KeyError(f"No 'projection' dataset in {GCOV_BASE}/frequency{frequency}")

    proj = grid["projection"]
    attrs = {key: as_python(value) for key, value in proj.attrs.items()}

    for key in ("spatial_ref", "crs_wkt"):
        wkt = attrs.get(key)
        if wkt:
            return CRS.from_user_input(wkt)

    epsg = attrs.get("epsg_code")
    if epsg is None and getattr(proj, "shape", None) == ():
        epsg = as_python(proj[()])
    if epsg is not None:
        return CRS.from_epsg(int(epsg))

    raise KeyError("Projection dataset has neither spatial_ref/crs_wkt nor an EPSG code.")


def projection(h5file: Any, frequency: str = "A") -> dict[str, Any]:
    """CRS and grid coordinates, as stored by the product (no guessing)."""
    grid = grid_group(h5file, frequency)
    out: dict[str, Any] = {}
    proj = grid.get("projection")
    if proj is not None:
        attrs = {key: as_python(value) for key, value in proj.attrs.items()}
        out["projection_attrs"] = attrs
        out["projection_value"] = as_python(proj[()]) if getattr(proj, "shape", None) == () else None
        for key in ("spatial_ref", "crs_wkt", "grid_mapping_name", "epsg_code", "utm_zone_number"):
            if key in attrs:
                out[key] = attrs[key]
        try:
            out["crs"] = crs_of(h5file, frequency).to_string()
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            out["crs"] = f"unavailable ({exc.__class__.__name__}: {exc})"
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


def _coverage_slice(coords: np.ndarray, low: float, high: float) -> slice:
    """Pixel slice covering [low, high] along one axis, whatever direction the axis runs.

    In real NISAR products ``xCoordinates`` ascends eastwards and ``yCoordinates`` descends from
    north to south, the values are pixel **centres**, and the spacing is 20 m. We therefore widen the
    request by half a pixel so the box we asked for is completely inside the window we read.
    """
    if low > high:
        low, high = high, low
    ascending = coords[0] <= coords[-1]
    axis = np.asarray(coords if ascending else coords[::-1], dtype="float64")
    step = float(np.median(np.diff(axis))) if axis.size > 1 else 0.0
    low -= abs(step) / 2.0
    high += abs(step) / 2.0

    start = int(np.searchsorted(axis, low, side="left"))
    stop = int(np.searchsorted(axis, high, side="right"))
    start = max(0, min(start, axis.size - 1))
    stop = max(start + 1, min(stop, axis.size))

    if ascending:
        return slice(start, stop)
    return slice(axis.size - stop, axis.size - start)


def window_to_indices(
    h5file: Any,
    bbox_wgs84: tuple[float, float, float, float],
    frequency: str = "A",
) -> tuple[slice, slice]:
    """Convert a lon/lat box into row/column slices of the projected GCOV grid.

    All four corners are reprojected, because a lon/lat box is a curved quadrilateral in UTM, and the
    result is mapped to pixel indices through the product's own coordinate vectors.
    """
    from pyproj import CRS, Transformer

    grid = grid_group(h5file, frequency)
    xs = np.asarray(grid["xCoordinates"][:], dtype="float64")
    ys = np.asarray(grid["yCoordinates"][:], dtype="float64")

    transformer = Transformer.from_crs(
        CRS.from_epsg(4326), crs_of(h5file, frequency), always_xy=True
    )
    west, south, east, north = bbox_wgs84
    px, py = transformer.transform([west, east, east, west], [south, south, north, north])

    rows = _coverage_slice(ys, min(py), max(py))
    cols = _coverage_slice(xs, min(px), max(px))
    return rows, cols
