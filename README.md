# Team Venus: Seeing the Dead Sea through the clouds

**Two places in Jordan, read through radar that works at night and through cloud.**
Live app: **https://leenelzoubii.github.io/venus---dancing-with-the-sars/**

> Venus, the planet of light and love, turns against the current of the other planets, and burns
> brightest in the dark night sky. Named for a goddess, it is the light we steer by.

Venus is wrapped in permanent cloud, and we know its surface only because radar sees through it. We read
Earth the same way. This project began with that idea and then had to earn it.

## What it does

The app shows Sentinel-1 C-band radar (OPERA RTC-S1) over two places in Jordan: the **Dead Sea whole lake**
and **Potash City evaporation ponds**. For each place it loads 6–10 quarterly acquisitions from 2016 to 2026
and displays them as false-colour composites (VV/VH) plus calibrated backscatter in decibels. You can step
through dates, compare the first and last acquisition with a swipe, see where open water is mapped and
how confident that edge actually is, and explore change between dates.

Everything runs from pre-computed files. No backend, no API keys, no build step: open `web/index.html`
and it works.

## Why it matters

The Dead Sea is shrinking, and its shore is where people live, farm and work. The southern basin carries
potash industry: evaporation ponds and salt crust that change because of us, not the climate. Meanwhile
water is the scarce resource in Jordan, and knowing where it is, quarter by quarter, is not academic. Radar is
one of the few instruments that answers that question when the sky is not clear.

## What we found, stated honestly

- **VH is the water channel.** Open water sits near -20 to -22 dB in VH, with good separation from land.
  Every water number we publish is VH. Method B (two-step threshold) is used: first discard VH > -15 dB
  (likely land), then apply Otsu to the remaining histogram. A ±1.5 dB uncertainty band is shown.
- **Shoreline change over a decade is within our detection threshold at 30 m.** The water area for the
  Dead Sea whole lake is ~800 km² on average (method B), with an absolute band of ±~50 km² for the
  threshold. Change smaller than the uncertainty is not called change.
- **A scene-wide offset exists between dates and is removed.** Offsets are measured on land pixels only
  (VH > -15 dB) and removed before any comparison. The value is printed on every change layer.
  Calibration drift and seasonal surface change are both consistent with the pattern; we cannot yet separate them.
- **Potash City evaporation ponds show industrial change.** The ponds expand and contract with production
  cycles, visible in both VV and VH backscatter and in the false-colour composites.

Numbers above come from `web/data/<place>/water_stats.json` and `web/data/<place>/offsets.json`.

## The data

| Item | Value |
|---|---|
| Product | OPERA RTC-S1 (radiometric terrain-corrected gamma-0, 30 m) |
| Maturity | OPERATIONAL (CRID: OPERA) |
| Geometry | Path 21, descending |
| Dates | 2016-05-17 to 2026-10-29 (quarterly, with gap 2018–2026 due to S1A/S1B orbit changes) |
| Source | ASF DAAC, NASA Earthdata |
| Known gap | 2018–2026: S1A/S1B orbit changes reduced coverage over this AOI |

### Series integrity

A **series** is (maturity, CRID, path, direction, polarizations). Series are never mixed: no change
layer, offset, threshold, water-area number or chart line combines two of them. Each series has its own
dates and its own fixed 2nd–98th percentile stretch, pooled over its own dates only.

Data credit: Sentinel-1 data courtesy of ESA, distributed by the Alaska Satellite Facility (ASF DAAC)
and NASA Earthdata via the OPERA project. Basemaps: CARTO dark (OpenStreetMap contributors, CARTO) and
Esri World Imagery with Esri place labels, displayed only, never cached or redistributed. NASA does not
endorse any non-U.S. Government entity or this project.

## How it works

```
Find  ->  Fetch a slice  ->  Clean  ->  Compare dates  ->  Visualise  ->  Share
search      stream only       dB +      offset removal      static WebP    GitHub
the archive the AOI window    multilook  + difference        + JSON/JS      Pages
```

Two stages, on purpose. The pipeline runs offline in Python and writes small static assets. The web app
reads only those assets, so the demo cannot fail because of network, authentication or a processing bug.

Two imaging chains share one crop rectangle per place. The **analysis chain** keeps the 90 m multilook
(3×3 in power) and median filter that the statistics were computed on. The **display chain** takes the native
30 m OPERA RTC-S1 power, reprojects it once to Web Mercator at ~17–20 m with a NaN-safe bilinear warp on
linear power, clips each band at a dB range pooled over every date of the place, and only then applies the
false-colour recipe (VV = red co-pol, VH = green cross-pol, blue = ratio).

The source CRS is always read from the cached subset's recorded projection, and the validator fails
the build if an overlay centre is more than 5 km outside its AOI.

## How to run

Windows (PowerShell), macOS and Linux. Python 3.12 or newer: verified on 3.12 and 3.13.

```bash
git clone https://github.com/leenelzoubii/venus---dancing-with-the-sars
cd venus---dancing-with-the-sars
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q            # 79 tests, no network needed
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
python scripts/30_s1_fetch.py --place dead_sea_full --start 2016-01-01
python scripts/30_s1_fetch.py --place potash_city --start 2016-01-01
python scripts/31_build_s1_site.py --all
python scripts/06_validate_web_assets.py
python scripts/07_check_web.py
python scripts/99_release_check.py
```

Scripts 30, 31 and the checks are documented inline.

## Echo, the in-app guide

The **Echo** button in the header opens a panel that answers questions about whatever is on screen.
It has two answering paths:

- **Live.** `api/chat.js` is a Vercel serverless function. It holds the OpenAI key server-side, receives
  only the facts of the current view (place, date, layer, polarization, thresholds, water numbers,
  resolution), and returns a short answer. The key never reaches the browser.
- **Built-in.** If the function is missing, offline, rate-limited or slow, Echo answers from a small
  set of hand-written answers in `js/strings.js`. Those cover what the layer shows, why water is dark,
  VV vs VH, the change map, the uncertainty band, resolution, dates, data provenance, deformation
  (not in this app) and limits. The answer is labelled "Offline answer" so nobody mistakes it for the
  model.

To enable the live path on Vercel:

```text
Project → Settings → Environment Variables → OPENAI_API_KEY = sk-...
Optional: OPENAI_MODEL (default gpt-4o-mini), CHAT_ALLOWED_ORIGINS (comma-separated hosts)
```

Redeploy after adding it. `GET /api/chat` reports `{ ok, configured }`, so you can check whether the
key was picked up without spending a token. Per-instance rate limit: 12 requests per minute per IP;
answers are capped at 340 output tokens.

Echo sends metadata only — never the map image, never any user identity, never anything typed outside
the chat box. The browser sends the transcript of the current conversation (last 8 turns) so follow-up
questions work.

## Limitations and honesty notes

- Only one geometry per place (path 21 descending). Places on different tracks are separate series and are never compared.
- Data are OPERATIONAL but may be reprocessed, which can move numbers.
- Wind roughens water and brightens it; salt crust can also be bright.
- Every water area carries a threshold band. Change smaller than the uncertainty is not called change.
- The false-colour composite follows the NISAR/ASF method adapted for VV/VH; the single-polarization ramp is our
  approximation of the one NASA describes, because its exact breakpoints are not published.
- The composite shows each place's window, not the full satellite frame.
- Large gap 2018–2026 due to S1A/S1B orbit changes; coverage is partial for Dead Sea whole lake due to its size.

## Future work

- Longer S1 time series with more recent acquisitions.
- Test the evaporation pond changes against optical imagery and production data.
- NISAR L-band data when more acquisitions become available over the AOI.
- Arabic interface, reviewed by a native speaker.

## Team

Team Venus, NASA Space Apps Challenge 2026, challenge "Dancing with the SARs".

## Licence

MIT, see `LICENSE`.