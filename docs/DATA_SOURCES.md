# Data sources and product facts

Everything here was **verified** against the ASF search API and the NISAR Data User Guide
(<https://nisar-docs.asf.alaska.edu/>) on 2026-11-13. Anything still unverified is marked **TO VERIFY**.

## Mission and archive

| Item | Value |
|---|---|
| Mission | NISAR — joint NASA / ISRO synthetic aperture radar, launched 2025-07-30 |
| Sensors | L-band (NASA, primary here) and S-band (ISRO, distributed via ISRO Bhoonidhi) |
| Archive / DAAC | Alaska Satellite Facility (ASF), hosted in NASA Earthdata Cloud (AWS) |
| Access | NASA Earthdata Login (EDL) required; free account |
| Licence | NASA open data policy — freely and openly available |
| Citation (guide) | Kristenson et al. (2026), *NISAR Data User Guide*, doi:10.5281/ZENODO.20075813 |

## Product used: L2 GCOV (Geocoded Polarimetric Covariance)

Verified on the GCOV page of the user guide:

- **What it is:** calibrated backscatter, radiometrically terrain corrected (area-based RTC against
  Copernicus 30/90 m DEM), geocoded to the local **UTM** zone, presented as **gamma-0 power**.
- **Pixel spacing:** 10, 20 or 80 m depending on range bandwidth. Our products carry mode code `2005`
  (20 MHz primary L-band) → **20 m**.
- **Layers** (frequency A = L-band):

  | Path | Meaning |
  |---|---|
  | `/science/LSAR/GCOV/grids/frequencyA/HHHH` | HH covariance diagonal — real-valued gamma-0 **power** |
  | `/science/LSAR/GCOV/grids/frequencyA/HVHV` | HV covariance diagonal — real-valued gamma-0 **power** |
  | `/science/LSAR/GCOV/grids/frequencyA/HVHH` … | off-diagonal terms — complex, **quad-pol only** (not ours) |
  | `/science/LSAR/GCOV/grids/frequencyA/mask` | mask describing the averaging ensemble of radar samples |
  | `/science/LSAR/GCOV/grids/frequencyA/numberOfLooks` | number of looks used per sample |
  | `/science/LSAR/GCOV/grids/frequencyA/rtcGammaToSigmaFactor` | factor converting gamma-0 to sigma-0 |

- **Units rule:** diagonal terms are **power**, so display dB = `10 * log10(power)`. Never `20 * log10`.
- **Dtype:** 32-bit float (confirmed by the guide's `gdalinfo` example).
- **TO VERIFY (tonight, script 02):** exact HDF5 tree of one real Dead Sea file, dtype/units/`long_name`
  attributes, the UTM EPSG code and geotransform, the numeric encoding of `mask`, and whether a
  `frequencyB` (S-band) group exists in these L-band products.

## Data maturity (critical — do not mix)

| Maturity | Collection | CRID | Acquisitions covered |
|---|---|---|---|
| BETA | `NISAR_L2_GCOV_BETA_V1` | X05009/X05010 | 2025-10-17 → 2026-01-20 (pre-calibration) |
| **PROVISIONAL** | `NISAR_L2_GCOV_PROVISIONAL_V1` | P05023 | **2026-06-17 → part of 2026-10-23** |
| **VALIDATED** | `NISAR_L2_GCOV_V1` | P05036 | **from 2026-10-21** onward |

The guide warns that differences between maturity levels may come from the processing software, not
from the ground. Our series therefore uses PROVISIONAL end-to-end.

## Verified availability over the Dead Sea AOI

Queried via `https://api.daac.asf.alaska.edu/services/search/param` (platform=NISAR,
processingLevel=GCOV) on 2026-11-13. Dates are the acquisitions returned; file size in parentheses is
the reported product size.

**Primary stack — track 151, frame 073, DESCENDING** (acquisition ≈ 16:25 UTC, ~18:25 local)

PROVISIONAL (9 dates):
`2026-06-24`, `2026-07-06`, `2026-07-18`, `2026-08-11`, `2026-08-23`, `2026-09-04` (two products,
`_001` and `_002` — **dedupe by date, keep the later processingDate**), `2026-09-16`, `2026-09-28`,
`2026-10-10`

VALIDATED: `2026-10-22`, `2026-11-03`

**Other stacks over the AOI** (usable as cross-checks or fallbacks, never mixed into the series)

| Track/frame/direction | Time (UTC) | PROVISIONAL dates (2026) |
|---|---|---|
| 172 / 017 / ASC | ~02:51 | 06-26, 07-08, 07-20, 08-13, 08-25, 09-06, 09-18, 09-30, 10-12 (VALIDATED: 10-24) |
| 172 / 018 / ASC | ~02:51 | subset of 172/017 above |
| 100 / 017 / ASC | ~02:59 | 06-21, 07-03, 07-15, 07-27, 08-20, 09-01, 09-13, 10-07, 10-19 |

**Product size:** ≈ 1.78–1.93 GB per GCOV file. We therefore **stream/subset** rather than download
full frames.

## Known mission artefacts that affect our story

- **Permanent instrument data gap:** `2026-07-27T22:03:25Z` → `2026-08-10T00:55:27Z`. This is why the
  151/073 series jumps from 2026-07-18 to 2026-08-11. It is a known mission fact, not a processing bug.
- **Reprocessing:** the validated reprocessing campaign for pre-2026-10-21 data is expected in **2027**;
  PROVISIONAL products will eventually be superseded. Record the exact product names used.
- Repeated products for one date (see 2026-09-04) — always dedupe by acquisition date.
- **TO VERIFY:** whether `frequencyB` exists in these products, and whether the SLC-derived L1 products
  (GSLC/GUNW) are available for 151/073 — needed only for the interferometry stretch goal.

## Access recipes (documented by the guide)

1. **GDAL `/vsicurl/` with `.netrc`** — read only the window you need, no full download.
   Requires GDAL ≥ 3.13 for the HDF5 driver; older GDAL needs the `NETCDF:` prefix.
2. **`fsspec` + `h5netcdf` / `h5py`** — byte-range streaming with EDL credentials.
3. **`asf_search`** — `asf.search(dataset='NISAR', processingLevel='GCOV', dataMaturity='PROVISIONAL',
   intersectsWith=<WKT>)`, then `.download(path=..., session=...)`.

On Windows, `.netrc` lives at `C:\Users\<user>\.netrc` (some GDAL builds expect `_netrc`).
