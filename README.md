# Team Venus: Seeing the Dead Sea through the clouds

**Six places in Jordan, read through radar that works at night and through cloud.**
Live app: **https://leenelzoubii.github.io/venus---dancing-with-the-sars/**

> Venus, the planet of light and love, turns against the current of the other planets, and burns
> brightest in the dark night sky. Named for a goddess, it is the light we steer by.

Venus is wrapped in permanent cloud, and we know its surface only because radar sees through it. We read
Earth the same way. This project began with that idea and then had to earn it.

## What it does

The app shows NISAR L-band radar over six places in Jordan: the Dead Sea east shore, Potash City, Azraq
Wetland, Melehat Sdom, Wadi Rum and Al-Wehda Dam. For each place it loads seven to ten satellite dates
and displays them as a false-colour composite in the same style as NASA's own NISAR tools, plus an
analysis view of calibrated backscatter in decibels. You can step through dates, compare the first and
last acquisition with a swipe, and see where the water edge is and how confident that edge actually is.

Everything runs from pre-computed files. No backend, no API keys, no build step: open `web/index.html`
and it works.

## Why it matters

The Dead Sea is shrinking, and its shore is where people live, farm and work. The eastern plain carries
potash industry: evaporation ponds and salt crust that change because of us, not the climate. Meanwhile
water is the scarce resource in Jordan, and knowing where it is, week by week, is not academic. Radar is
one of the few instruments that answers that question when the sky is not clear.

## What we found, stated honestly

- **HV is the water channel, HH is not.** Open water sits near -20.5 dB in HV, with about 7 dB of
  separation from land. In HH, water and land overlap, so no single HH threshold works. Every water
  number we publish is HV. Places whose granules are single-polarization HH have no water series at all,
  and the app says so rather than drawing an empty chart.
- **Shoreline change over about three and a half months is below our detection threshold at 20 m.** The
  water area for the Dead Sea east shore is 138.99 km2 on average (method B, standard deviation 0.77),
  with an absolute band of +/-22.67 km2 for the threshold. The change-detection limit is 2.51 km2. Eleven
  of 36 date pairs exceed it with a stable sign, the largest being +5.59 km2 between 2026-06-24 and
  2026-08-11. We present those as hypotheses, not confirmed change.
- **A scene-wide offset exists between dates and is unexplained.** Between the first and last Dead Sea
  dates the offset is -0.63 dB in HV and +0.61 dB in HH, on water and land alike, so it is not surface
  change. We measure it on land only, remove it before any comparison, and print the value on every
  change layer. Calibration drift and seasonal surface change are both consistent with the pattern; we
  cannot yet separate them.
- **Localized patches on the eastern plain are unexplained.** Under the configured rule (3 dB on two
  consecutive dates) none qualify. At 1 dB three small candidates appear; one darkens for four dates
  about 60 m from water. These are questions, not results, and no field check has been done.

Numbers above come from `data/interim/water_stats.json` and `data/interim/offsets.json`.

## The data

| Item | Value |
|---|---|
| Product | NISAR L2 GCOV (geocoded polarimetric covariance, gamma-0 power) |
| Maturity | PROVISIONAL, CRID P05023 |
| Geometry | one track/frame per place; Dead Sea is track 151, frame 073, descending |
| Dates | 7 to 10 acquisitions per place, 2026-06-17 to 2026-10-19 |
| Source | ASF DAAC, NASA Earthdata |
| Known gap | instrument outage 2026-07-27 to 2026-08-10; the series jumps 07-18 to 08-11 |

VALIDATED products (CRID P05036) were **not** mixed into any series. The validator fails the build if a
layer carries another CRID.

Data credit: NISAR data courtesy of NASA/JPL-Caltech and ISRO, distributed by the Alaska Satellite
Facility (ASF DAAC) and NASA Earthdata. Basemap: Esri World Imagery, displayed only, never cached or
redistributed. NASA does not endorse any non-U.S. Government entity or this project.

## How it works

```
Find  ->  Fetch a slice  ->  Clean  ->  Compare dates  ->  Visualise  ->  Share
search      stream only       dB +      offset removal      static PNGs    GitHub
the archive the AOI window    multilook  + difference        + JSON/JS      Pages
```

Two stages, on purpose. The pipeline runs offline in Python and writes small static assets. The web app
reads only those assets, so the demo cannot fail because of network, authentication or a processing bug.
Fetches use GDAL `/vsicurl/` streaming with merged byte ranges: about 20 seconds per date here, against
about 300 seconds for plain range reads, because the cost was round trips rather than megabytes.

## How to run

Windows (PowerShell), macOS and Linux. Python 3.12.

```bash
git clone https://github.com/leenelzoubii/venus---dancing-with-the-sars
cd venus---dancing-with-the-sars
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q            # 63 tests, no network needed
```

The app needs no build:

```bash
# open directly
web/index.html

# or serve it
python -m http.server 8000 --directory web     # http://localhost:8000/index.html
```

Regenerating data needs a NASA Earthdata login. Credentials are read from `~/.netrc`
(`machine urs.earthdata.nasa.gov login <user> password <pass>`) and are never stored in this repository.

```bash
python scripts/01_search_nisar.py --aoi potash_city --out data/interim/scenes_potash_city.csv
python scripts/03b_fetch_fast.py --aoi potash_city --stack 100/17/ASC --all --scenes data/interim/scenes_potash_city.csv
python scripts/12_build_place_site.py --aoi potash_city
python scripts/10_build_places.py
python scripts/13_build_assistant_context.py
python scripts/06_validate_web_assets.py
python scripts/07_check_web.py
python scripts/99_release_check.py
```

Scripts 01-13 and 99 are documented inline; `scripts/README` order is 01, 03b, 12, 10, 13, then the checks.

## Limitations and honesty notes

- Only one geometry per place. Places on different tracks are separate series and are never compared.
- Data are PROVISIONAL and may be reprocessed, which can move numbers.
- Wind roughens water and brightens it; salt crust can also be bright.
- Every water area carries a threshold band. Change smaller than the uncertainty is not called change.
- About 7 to 8 percent of mapped water pixels at the Dead Sea lie outside the main lake body
  (hypothesis: dark terrain or radar shadow). Not yet removed.
- The false-colour composite follows ASF's published method exactly; the single-polarization ramp is our
  approximation of the one NASA describes, because its exact breakpoints are not published.
- The composite shows each place's window, not the full satellite frame.

## Future work

- Validated products (P05036) over a longer series, kept separate from the provisional series.
- Test the eastern-plain candidates against optical imagery and, if possible, field knowledge.
- GUNW/GSLC interferometry for subsidence and sinkholes. **Availability for these track/frame pairs was
  not checked**; this is future work, not a result.
- Arabic interface, reviewed by a native speaker.

## Team

Team Venus, NASA Space Apps Challenge 2026, challenge "Dancing with the SARs".

## Licence

MIT, see `LICENSE`.
