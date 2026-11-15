# Decisions log

One entry per meaningful choice: **date — decision — reason — alternatives considered**.
Newest at the top. If a decision is reversed, add a new entry rather than editing history.

---

## 2026-11-15 — Pivot to Sentinel-1 OPERA RTC-S1 for the challenge deadline

**Decision.** Replace NISAR L-band with Sentinel-1 C-band OPERA RTC-S1 (CRID: OPERA, OPERATIONAL
maturity) for two places: Dead Sea whole lake (`dead_sea_full`) and Potash City evaporation ponds
(`potash_city`). Quarterly acquisitions 2016-05-17 to 2026-10-29, path 21 descending, VV+VH
polarizations, 30 m native resolution.

**Reason.** NISAR PROVISIONAL data over the Dead Sea has a 12-day cadence but a permanent instrument
gap (2026-07-27 to 2026-08-10) and only 9 dates on one geometry. Sentinel-1 OPERA RTC-S1 provides
a decade of quarterly data on a single geometry (path 21 descending), enabling a true time series
with 10-18 dates per place. The challenge requires "one or more types of surface change" and an
"interactive medium" — a decade of S1 data shows shoreline change and industrial evaporation pond
cycles far better than 9 NISAR dates. OPERATIONAL maturity means the data is fully calibrated.

**Alternatives.** Stay with NISAR (too few dates, instrument gap, only 2 VALIDATED dates on one
track); use S1 but mix geometries (violates same-geometry rule); use S1 GRD instead of OPERA RTC-S1
(not analysis-ready, needs terrain correction).

---

## 2026-11-15 — Two places only: dead_sea_full and potash_city

**Decision.** Trim the 14 configured places to exactly two for the challenge submission:
`dead_sea_full` (whole Dead Sea lake, both shores, including southern evaporation ponds) and
`potash_city` (industrial evaporation ponds near the southern basin).

**Reason.** The challenge asks to "pick a study area" and "track and visualise one or more types of
surface change". Two places give two distinct stories: (1) whole-lake water area and shoreline
change over a decade, and (2) human-driven evaporation pond expansion/contraction. Adding more
places dilutes the narrative and increases data volume. The config remains a named list so places
can be re-enabled later.

**Alternatives.** Keep all 14 places (too much data, unfocused story); add Azraq wetland (third
story but different geometry, would need separate series).

---

## 2026-11-15 — Water method B on VH only; change offsets on land (VH > -15 dB)

**Decision.** Water mapping uses Method B (two-step: discard VH > -15 dB, then Otsu) on VH
polarization only. Scene-wide offset is the median of (date - reference) over land pixels
defined as VH > -15 dB (and finite in both VV and VH), applied per polarization before
differencing.

**Reason.** For S1 C-band, VH is the water-sensitive polarization (open water ~ -20 to -22 dB).
The two-step threshold excludes bright land/salt crust before finding the water mode. Offsets
measured on land avoid bias from the changing water area itself. Per-polarization offsets account
for VV/VH calibration differences.

**Alternatives.** Fixed threshold (fails on seasonal roughness); Method B on VV (poorer water
separation); offset on all pixels (water change biases the correction).

---

## 2026-11-15 — Display chain: native 30 m -> ~17-20 m Web Mercator, pooled 2/98 stretch

**Decision.** Display chain takes native 30 m OPERA RTC-S1 gamma-0 power, reprojects once to
EPSG:3857 with NaN-safe bilinear warp at ~17-20 m (2× native at 31.5° latitude), applies a
pooled 2nd-98th percentile dB stretch over all dates of the place, then false-colour (VV=red,
VH=green, blue=ratio) or grey ramp. 6 px inward edge feather. WebP q82 with alpha.

**Reason.** One warp preserves geometry exactly for Leaflet overlays. Pooled stretch makes every
date directly comparable (same dB = same colour). 2× native keeps layer sizes under budget while
showing more detail than the 90 m analysis grid. The 900 KB budget for dead_sea_full accommodates
its larger window (30×60 km vs 15×30 km for potash_city).

**Alternatives.** Keep analysis resolution for display (90 m, blurry); per-date stretch (breaks
comparison); WebP q60 baseline (quality loss visible).

---

## 2026-11-15 — Size budget 900 KB for dead_sea_full, 700 KB for potash_city

**Decision.** Per-layer WebP budget is 900 KB for dead_sea_full (whole lake, larger window) and
700 KB for potash_city. Quality falls back from q82 -> q75 -> q68 -> q60 to meet budget.

**Reason.** dead_sea_full's display window is ~30×60 km at ~17 m = ~1760×3500 px (~6 M pixels);
even at q82 it exceeds 700 KB. potash_city is ~15×30 km = ~880×1750 px (~1.5 M pixels), well
inside 700 KB at q82. The budget increase is documented in the layer metadata
(`resolution_fallback` or `webp_quality`).

**Alternatives.** Downsample display resolution for dead_sea_full (loses detail); split into tiles
(adds complexity, not static-file-friendly).

---

## 2026-11-13 — Water thresholds are derived per image (Otsu), never taken from the literature

**Decision.** The water mask uses a two-class Otsu threshold computed on each filtered dB image.
`change.water_mask(db, threshold)` still accepts a fixed number for experiments, but the pipeline
default is `auto`, and every reported area carries a ±1.5 dB sensitivity band.

**Reason.** Measured on real data: the Dead Sea's open water sits at **−13.7 dB in HH** and **−20.5 dB
in HV**, not the −20 dB a textbook rule suggests. A fixed −17 dB threshold found **0 km² of water** in a
window that is visibly half lake. Worse, the June and October images differ by a scene-wide offset
(≈ −0.8 dB in HV, ≈ +0.4 dB in HH) that shifts every mode, so one fixed number cannot serve both dates:
the same threshold gave water areas from 34 km² to 149 km² depending on where it was placed. Per-image
thresholds made the two dates comparable and dropped the disagreement between channels to ±2 km².

**Alternatives.** Fixed literature threshold (demonstrably wrong here); fixed threshold plus a manual
per-date fudge (not reproducible); a speckle-model (K-distribution) classifier (better science, too much
for tonight).

---

## 2026-11-13 — Change maps are multi-looked in power, and the scene-wide offset is removed

**Decision.** Difference products average 3×3 blocks **in linear power** before the dB conversion
(20 m → 60 m), and the scene median of the difference is subtracted and stated in the title/JSON.

**Reason.** At 20 m a raw difference image is almost pure speckle. Averaging in power is the
radiometrically correct order — averaging dB under-estimates the mean because log is concave. Subtracting
the scene median removes the acquisition-to-acquisition offset described above so the map shows spatial
structure rather than a global tint. Both choices are labelled on the image and in the metadata.

**Alternatives.** No filtering (unreadable); stronger 5×5 averaging (hides the very shoreline signal we
want); Lee filter before differencing (fine, but slower and not yet justified by these two dates).

---

## 2026-11-13 — The shoreline trend is reported as *below detection*, not as a number

**Decision.** With two dates the app says the lake area is 137–141 km² and that the change between
2026-06-24 and 2026-10-10 is **smaller than the method's uncertainty** (±15 km² across a ±1.5 dB
threshold band; HH and HV disagree in sign at the ±2 km² level). No retreat rate is quoted until the
full series is processed.

**Reason.** Honesty requirement in the brief, and a practical one: the Dead Sea has been dropping about
a metre per year, so 3.5 months is roughly 0.3 m of level — metres to tens of metres of horizontal
shoreline shift, i.e. a few 20 m pixels on gentle mudflats. A confident trend line from two dates would be
wrong and a judge who knows the lake would catch it.

---

## 2026-11-13 — Placeholder AOI: `dead_sea_east`

**Decision.** Tonight's Gate-1 AOI is the Jordanian east shore between Suweimeh and Ghor Haditha:

```
POLYGON((35.500 31.340, 35.600 31.340, 35.600 31.560, 35.500 31.560, 35.500 31.340))
```

≈ 11 × 24 km ≈ 550 × 1200 pixels at 20 m GCOV spacing.

**Reason.** Verified live against the ASF archive: three independent repeat stacks cover it
(151/073 descending, 172/017 and 172/018 ascending), so a failed stack is not fatal. It is entirely
on the Jordanian shore (the team's local link), and it holds two stories in one frame: shoreline
retreat as the lake level falls, and the sinkhole belt on the Ghor Haditha plain. The subset is small
enough to stream quickly.

**Alternatives.** Whole Dead Sea (bigger, slower, drags in the Israeli shore and border sensitivity);
south evaporation ponds near Safi (strongest dB contrast, but the team had not decided on the story);
Azraq wetland (most data, 47 provisional files, but the oasis features are small relative to 20 m
pixels, so a risky headline).

**Note.** The AOI is a config value, not code: `config/study_area.yaml` holds a **named list**, and
every script accepts `--aoi <name>` / `--aoi-wkt`. Adding a second Jordanian location is a YAML edit.

---

## 2026-11-13 — Sensitivity: how we name and frame the Dead Sea

**Decision.** Frame the study area as "the Dead Sea, seen from the Jordanian shore". Keep basemap
labelling neutral, and do not draw border or sovereignty claims in our own layers.

**Reason.** The Dead Sea is shared between Jordan, Israel and Palestine; borders are politically
sensitive and are not our subject. Our subject is water, salt and ground.

---

## 2026-11-13 — Data standard: NISAR L2 GCOV, PROVISIONAL, descending 151/073

**Decision.** The change series uses **NISAR L2 GCOV, PROVISIONAL maturity**, descending track 151 /
frame 073, acquisitions **2026-06-24 → 2026-10-10** (9 dates). VALIDATED products (from 2026-10-21)
may appear only as a separately labelled "latest state", never inside the same comparison.

**Reason.** The NISAR Data User Guide states PROVISIONAL covers acquisitions 2026-06-17 → part of
2026-10-23 (CRID P05023) and VALIDATED starts 2026-10-21 (CRID P05036), and explicitly warns that
mixing maturities in one workflow can make processing differences look like ground change.
PROVISIONAL is the only way to get a series with more than two dates today.

**Alternatives.** VALIDATED only (only 2 dates for 151/073: 2026-10-22 and 2026-11-03) — too short for
a time slider. BETA (2025-10 → 2026-01) — different calibration, not comparable.

---

## 2026-11-13 — Same-geometry rule is a hard constraint

**Decision.** Never compare scenes from different track/frame/flight direction. Group by
(track, frame, direction) and compare only within a group.

**Reason.** Different look geometry changes incidence angle and layover/shadow, producing apparent
backscatter change where nothing changed on the ground.

---

## 2026-11-13 — Products: GCOV (backscatter), not GSLC or interferometry

**Decision.** MVP uses GCOV only. GSLC/GUNW are listed but not promised.

**Reason.** GCOV is analysis-ready, terrain-corrected gamma-0 power in UTM, directly usable as
backscatter. Interferometric products need pair selection and much more validation before we can claim
displacement; that stays a stretch goal.

---

## 2026-11-13 — Environment: Python 3.12 in `.venv`

**Decision.** Local virtual environment on Python 3.12; dependencies in `requirements.txt`; exact
resolved versions frozen to `requirements.lock.txt` after a successful install.

**Reason.** Python 3.12 has the widest Windows wheel coverage for the geo stack (rasterio, h5py,
netCDF4, geopandas). `requirements.txt` states intent, the lock file makes the build reproducible.

**Alternatives.** Python 3.13 (the machine default; slightly higher wheel risk), 3.11 (older),
conda/mamba (not installed, one more failure mode on the morning of a hackathon).

---

## 2026-11-13 — Repository and git policy

**Decision.** Clone the existing empty public remote
(`leenelzoubii/venus---dancing-with-the-sars`) into the working folder, commit locally, **do not push**
until the team confirms.

**Reason.** The team created the remote already; a clone keeps `origin` correct with no manual step.
The briefing requires explicit confirmation before publishing.

---

## 2026-11-13 — Two-stage architecture (offline pipeline → static app)

**Decision.** All data processing happens offline in Python and is exported as small static assets
(COG/GeoTIFF, PNG + bounds JSON, metadata JSON). The web app is plain HTML/CSS/JS + one mapping
library, with no backend, no API keys and no build step.

**Reason.** The live demo cannot fail because of network, authentication or a processing bug; the same
folder works on GitHub Pages and offline from disk.

---

## 2026-11-14 - Water threshold: compare four estimators, recommend two-step Otsu (method B)

**Decision.** Compute water area four ways on offset-corrected HV and publish the comparison, not
one number. Method A = one pooled histogram-valley threshold for the whole series (-18.35 dB).
Method B = discard HV above -15 dB, then Otsu on the remainder, per date. Method C = two-component
Gaussian mixture, threshold where posteriors cross, per date. Method D = the previous per-image Otsu
on the whole window, kept for comparison only. Primary method for the app: **B**, pending Leen.

**Reason.** Across nine dates (sd of area, range, and band at +/-1.5 dB):

| method | mean km2 | sd km2 | range km2 | band +/- km2 | km2 per dB |
|---|---|---|---|---|---|
| A | 137.64 | 1.65 | 5.59 | 31.8 | 11.8 |
| B | 138.99 | 0.77 | 2.06 | 22.7 | 12.9 |
| C | 132.65 | 0.73 | 2.67 | 60.2 | 9.1 |
| D | 147.17 | 1.54 | 4.95 | 20.7 | 18.3 |

No method shows a change larger than its band, so we publish "not detectable yet", not a trend. B has
the smallest range among the per-date methods and a band half the size of C's, whose threshold sits on
the steepest part of the curve. D is worst on both range and sensitivity, which is the land-bias effect
we predicted.

**Alternatives rejected.** A single fixed threshold (too sensitive to the one-day wind state that
produced the pooled histogram); C alone (best stability but its band is +/-60 km2, so it cannot support
any claim); D (biased by land dominating the pixel count).

---

## 2026-11-14 - Offsets estimated on land only, and applied only explicitly

**Decision.** The scene-wide offset is the median of (date minus reference) over pixels defined as land:
HV > -15 dB, numberOfLooks >= 4, finite in both HH and HV. 23.9 percent of the window, 16429 pixels.
Reference date 2026-06-24. Written to ``data/interim/offsets.json`` and applied only by scripts that
name it in their log output.

**Reason.** Water is the population that actually changes; including it would let a drying lake move the
correction that is supposed to remove everything except change. Low-look pixels are the noisiest and are
excluded for the same reason. HH offsets rise smoothly (+0.12 to +0.61 dB) while HV offsets are jumpy
(-0.53 to +0.26 dB); a smooth monotonic drift is consistent with a real seasonal surface change, while
jumpiness is more consistent with calibration. Labelled a hypothesis, not a finding.

---

## 2026-11-14 - The GCOV mask is a subswath number, not a 0/1 flag

**Decision.** Never threshold ``mask == 1`` as if it were "valid". Read the product attribute instead:
the mask holds the subswath number for valid GCOV samples, 0 where at least one radar sample in the
averaging set was partially focused or invalid, and 255 outside the radar acquisition extent.

**Reason.** Verified from the mask dataset's own ``description`` attribute in the archive, not from
memory. On this AOI 99.996 percent of pixels are mask == 1, i.e. valid subswath-1 data, which matches
the measured NaN fraction of 0.004 percent.

---

## 2026-11-14 - Primary water method B; change-detection limit kept separate from the area band

**Decision.** Method B (two-step: drop HV above -15 dB, then Otsu) is primary. The +/-1.5 dB band is the
absolute area uncertainty for one date. The change-detection limit is a different quantity: the area
equivalent of the offset uncertainty (offset MAD plus land-definition sensitivity, times the measured
km2 per dB). A date-to-date change counts only if its sign is robust across thresholds -0.5 to +0.5 dB
AND its median difference exceeds that limit.

**Result (method B).** Offset uncertainty 0.27 dB, which is 2.51 km2. 11 of 36 date pairs clear the
limit with a robust sign; the largest is 2026-06-24 to 2026-08-11 at +5.59 km2. Every such pair is a
hypothesis until checked against imagery and the mission record.

**Reason.** The +/-1.5 dB band says nothing about whether two dates differ. Using it as the change limit
would hide real differences; using the offset alone would ignore the threshold. Both checks are needed.

**Alternatives.** Use the area band as the change limit (rejected: too wide, 22.7 km2); report a trend
only (rejected: a trend fit does not give a limit).

---

## 2026-11-14 - Candidate patches: persistence rule, 60 m, water and low-look exclusion

**Decision.** A patch is a connected blob (8-connectivity) of pixels whose |delta| versus the reference
exceeds 3 dB on at least 2 consecutive dates, at 60 m, at least 20 px, outside water (method B union) and
below the 10th percentile of numberOfLooks (6.15 at 60 m).

**Result.** 0 patches at the configured rule. 1 dB gives 3 patches at 10 px. Sensitivity is in the
04b output. The 3 sensitive candidates are logged in docs/patch_log_sensitive.csv for Leyan.

**Reason.** Speckle is uncorrelated between dates, so persistence is the cheapest protection. We report
the zero honestly rather than lowering the threshold to make a nicer map.

---

## 2026-11-14 - Web export: EPSG:3857 layers, fixed scales, .json and .js twins

**Decision.** Every raster is reprojected from EPSG:32636 to EPSG:3857 with rasterio.warp (bilinear for dB,
nearest for masks). Bounds are the Web Mercator rectangle converted back to lon/lat corners; the native
grid is widened by half a pixel first. Backscatter and change are displayed at 60 m; water and the
detection-limit band at 20 m. Data files are written twice, as .json for humans and as a .js that
assigns to window.VENUS for file:// use.

**Reason.** Leaflet stretches an image linearly across its bounds in Web Mercator space, so a rectangle in
EPSG:3857 is the only way the overlay is geometrically exact. A geometry check on the 2026-10-10 water
layer gives 140.2 km2 against 139.8 km2 in the stats file (0.3 percent, nearest-neighbour resampling).

**Alternatives.** Keep UTM and let Leaflet approximate (rejected: visible shift at the edges); serve JSON
over fetch (rejected: fails on file://).

**Open.** The old web/assets folder from Gate 1 is still present and still loaded by app.js. Migrating the
app to web/data is Hour 3.

---

## 2026-11-14 - Validator named 06_validate_web_assets.py despite the existing 06_qc_table.py

**Decision.** Keep the name requested in the brief, although two scripts now share the 06 prefix.

**Reason.** The brief named it exactly, and the names are distinct. Renumbering later is cheap; a
mismatch with the brief is not.

---

## 2026-11-14 - Web app v0: plain HTML/JS, classic scripts, data via window.VENUS, Leaflet 1.9.4 vendored

**Decision.** The app is static HTML, CSS and vanilla JavaScript split into index.html, css/app.css,
js/strings.js (all text), js/ui.js (panels and controls) and js/app.js (map and layers). Data are read from
the web/data/*.js wrappers (window.VENUS), never fetch(). Leaflet 1.9.4 is vendored in web/vendor/leaflet/.

**Reason.** Double-click (file://) must work, and GitHub Pages serves the same files under a sub-path. Classic
scripts and relative paths satisfy both. Leaflet is the simplest mapping library that supports image overlays
in Web Mercator.

**Alternatives.** A framework (rejected: build step); fetch() of JSON (rejected: fails on file://).

## 2026-11-14 - Overlay rules: manifest bounds only, fade in after load, drop stale loads

**Decision.** Each radar image is an L.imageOverlay placed at the manifest bounds; the app never recomputes
bounds. A new image fades in only after it has loaded, a load that is no longer wanted is discarded, and only
the visible image and its two neighbours are requested.

**Reason.** Keeps alignment exact, avoids empty flashes, prevents a stale date from appearing after a fast step,
and keeps page weight low (about 0.3 MB on first load; 3.7 MB of layers exist, but a view fetches at most about
0.42 MB: the visible change image plus its two neighbours, 3 x 140 KB).

## 2026-11-14 - Alignment check: numbers, and one explained discrepancy

**Decision.** Alignment is judged by comparing the eastern water edge in the 20 m water layer with the dark edge in
the 60 m backscatter layer, both converted to lon/lat, and by a visual check at the middle row.

**Result (2026-10-10).** North (lat 31.540): 40 m apart. South (lat 31.361): 0 m. Middle (lat 31.450): 361 m apart.
The visual check at the middle row shows the apparent shoreline point sits on an inland dark patch that is not
lake. So the middle difference is a false-positive blob in the water mask, not a bounds error.

**Open.** About 7 to 8 percent of mapped water pixels sit outside the largest water body (06-24: 6.9 percent;
10-10: 7.9 percent). Hypothesis: dark terrain or radar shadow on slopes. Next step: an elevation or lake-polygon
constraint, decided with Leen. Not yet in the stats files, so it is not shown in the app.

## 2026-11-14 - Esri World Imagery as the basemap, pending the team's terms check

**Decision.** Use Esri World Imagery for the satellite basemap, displayed only, with on-screen attribution and an
offline fallback. Recorded in docs/DATA_SOURCES.md. Team must confirm the full terms before public launch.

**Alternative.** OpenStreetMap tiles.

---

## 2026-11-14 - Patch log is validated, not trusted; nothing merged when it is empty

**Decision.** `05_export_web_assets.py --patch-log` now validates the analyst CSV before merging: UTF-8,
required columns, `confidence` in low/medium/high, `use_in_pitch` in yes/no, no duplicate ids. Errors abort
the export; unusual values (a free-text `behaviour`) are warnings. A hypothesis without a confidence word is
flagged. Only `use_in_pitch == yes` features the patch in the app.

**State at Hour 5.** `docs/patch_log.csv` contains the header row only: Leyan has not filled it yet. The merge
therefore carried 0 human rows, and the Featured list says so in the app instead of inventing content.

**Also.** The patch layer shown in the app is the sensitivity run (`--patches-tag _sensitive`, 1 dB and 10 px),
labelled as such in `patches.js` (`detection_rule`) and in the legend. The configured 3 dB rule finds 0 patches.

---

## 2026-11-14 - Story mode drives the same state as the controls

**Decision.** The six story steps set the same `state` fields the controls set, then call `applyStateToControls()`
and `render()`. There is no second rendering path, so the story and the controls cannot disagree.

**Reason.** Duplicate logic is how a demo drifts away from what the controls show. Step 4 compares the water
mask at the first and last dates with the detection band on, because the band is only meaningful with the water
layer; an earlier draft put the band over the change layer, where it cannot render.

---

## 2026-11-14 - Pages deployment: workflow build type, action versions verified

**Decision.** `.github/workflows/pages.yml` publishes only `web/` with
`actions/checkout@v7`, `actions/configure-pages@v6`, `actions/upload-pages-artifact@v5`, `actions/deploy-pages@v5`.
Versions verified against the GitHub releases API on 2026-11-14 (v7.0.1, v6.0.0, v5.0.0, v5.0.1). The site source
was set to "GitHub Actions" with `gh api -X POST .../pages -f build_type=workflow`.

**Result.** Run 43584265357 succeeded on the first attempt. Live at
https://leenelzoubii.github.io/venus---dancing-with-the-sars/ with HTTP 200 for the page, an overlay PNG and
`data/manifest.js`.

**Note.** Only `web/` is published; pipeline code, raw data and docs are not part of the site.

---

## 2026-11-14 - Overlay slots hold at most one in-flight image

**Decision.** Replacing a slot cancels any pending load for that slot before starting the next one.

**Reason.** A story run left 7 images in the DOM: an image superseded mid-load was never removed. After the fix a
full story run leaves 1 overlay, verified in the browser.

---

## 2026-11-14 - Fourteen places, coordinates corrected, no imagery invented

**Decision.** All fourteen study areas the team supplied are in `config/study_area.yaml` and selectable in the
app. Each carries a `coord_note` recording whether it was corrected.

**Coordinate correction.** Eleven of the fourteen polygons had longitudes around -322 to -325 instead of +35 to
+38. A longitude of -324 is not a valid Earth coordinate, and every bad value is exactly 360 too small
(-323.1918 + 360 = 36.8082, Azraq). The correction is a plain +360 with no reshaping. It is checked visually:
the corrected whole-lake polygon traces the real shoreline on the satellite basemap.

**Coverage.** `scripts/01b_coverage_survey.py` searched the archive for every place without a fixed track or
frame, so coverage could not be hidden by geometry filters. All fourteen have PROVISIONAL GCOV coverage,
9 or 10 dates each, on five different geometries (100/17 ASC, 151/73 DESC, 151/72 DESC, 50/72 DESC, 50/74 DESC).
Results in `data/interim/coverage_survey.csv`.

**What the app shows.** Only `dead_sea_east` has processed imagery. For the other thirteen the app draws the
place outline, states the real archive coverage (dates and track/frame), and says the subsets have not been
processed. It never shows another place's imagery, and it never fabricates a layer.

**Why not process them now.** Each place needs its own subset fetch: about 4 to 5 minutes per date, 9 or 10
dates per place, so roughly 8 to 10 hours of unattended downloading for the remaining thirteen. That does not
fit the remaining hour. The command is ready and unattended:
`03_fetch_subset.py --aoi <name> --all` followed by `06`/`08`/`09`/`05` for that AOI.

**Consequence for comparisons.** Places on different tracks are separate series. The app must never compare
across places, and this rule is enforced by each place having its own manifest.

---

## 2026-11-14 - Six places processed; GDAL streaming replaces h5py for fetching

**Decision.** Fetch with `scripts/03b_fetch_fast.py` (GDAL `/vsicurl/` streaming) instead of h5py over
fsspec. Build each place into its own `web/data/<place>/` bundle with `scripts/12_build_place_site.py`.

**Measured.** Same 1231x505 window: h5py 300 s per date, GDAL 21 s (HH) + 12 s (HV). The five requested
places fetched in **32.6 minutes total** (potash 7.9, azraq 6.1, melehat 3.6, wadi_rum 10.4, alwehda 4.6)
against an earlier estimate of ~6.5 hours. The bottleneck was round trips, not bytes.

**Result.** Processed: dead_sea_east 9 dates, potash_city 7, azraq_wetland 10, melehat_sdom 9,
wadi_rum 10, alwehda_dam 9. HH+HV on four places; azraq and wadi_rum are HH only.

**Alternatives.** Harmony (Earthdata) does server-side GCOV subsetting and reprojection to COG, listed
complete Nov 2026. That is the better route at scale, but it needs a job API integration that did not fit
the remaining hour.

---

## 2026-11-14 - Things that broke, and the rule each one produced

1. **UTM zone is per frame.** The Dead Sea frame is EPSG:32636; a Wadi Rum frame is a different zone.
   Assuming one zone produced empty windows. Rule: resolve the zone by testing which candidate actually
   overlaps the product's own coordinates; stop rather than guess.
2. **Some GCOV granules are single-polarization** (`SHSH`, HH only), so HVHV may not exist. Rule: read
   what is there, record `polarizations_present`, and only compare a polarization present on every date.
3. **Mixing readers mixes grids.** Two potash dates fetched by the old path had a different window shape.
   Rule: keep only the largest group of dates sharing one shape and report what was dropped.
4. **A mostly-water AOI can have no land above the -15 dB cut**, which made every offset NaN.
   Rule: fall back to all finite pixels and record that the offset is weaker.
5. **An HH-only place has no water series.** Rule: default the polarization to what exists, and say why
   the water chart is empty instead of drawing a NaN path.

---

## 2026-11-14 - Assistant context recorded, assistant deliberately not built

**Decision.** `scripts/13_build_assistant_context.py` writes `web/data/assistant_context.json`/`.js`:
per-place facts, definitions, known limits, questions the data cannot answer, and suggested assistant
behaviour. No chat feature is implemented and no model is wired in.

**Reason.** Leen asked for the groundwork to be logged for a future navigation/explanation assistant.
Recording verified facts now prevents that assistant from inventing numbers later, which is the main risk
in a project whose whole credibility rests on not overstating the data.

---

## 2026-11-14 - The site now shows the standard NISAR false-colour decomposition

**Why this changed.** The team compared our site with ASF Vertex and the images did not look alike. Vertex
shows a false-colour composite (magenta, green, white); the site showed one grey dB channel per polarization.
Both were correct for what they were, but they were different pictures, so the comparison was impossible.

**What the reference method is.** Verified from the source of ASF's `nisar-py` (`gcov_rgb.py`, adapted from
hyp3-lib `rtc2color`) and from NASA's Worldview and SVS documentation: red = HH co-pol, green = HV cross-pol,
blue = a function of their ratio, computed from linear gamma-0 power on a fixed absolute scale.

**What we changed.**
- `src/venus/webexport.py` now has `rgb_decomposition`, a line-for-line port of the reference formulas, with
  three unit tests (invalid pixels black; calm-water case blue-dominant; absolute scale, not a per-image stretch).
- `scripts/12_build_place_site.py` writes one `rgb_HHHV_<date>.png` per date for every place with HH and HV.
- The composite is the default layer. The grey dB layers stay as analysis views.

**What the composite shows on this scene (measured, not tuned).** Vegetation and the plain render green to
yellow-orange, as in Vertex. The Dead Sea lake renders olive, not blue. Mechanism: the reference assigns blue only
where cross-pol return is below -24 dB; the lake's HV is about -20 dB (QC table, Hour 1), above that floor. The
legend now says so. We did not change the formula to make the lake look bluer.

**Still different from Vertex, on purpose.** Vertex shows the full scene frame; we show only the place's window
(the outline on the map). Vertex's browse may use a different resampling; ours is nearest neighbour on the 60 m grid.

**Not yet verified.** A side-by-side against an exact Vertex browse of the same granule. The reference images
were not downloaded, so the match is by method, not by pixel.

**Known gap.** Azraq Wetland and Wadi Rum are HH-only, so they have no composite (the method needs cross-pol) and
no water series.

---

## 2026-11-14 - Not pushed

Committed locally only. The standing rule requires the exact phrase `PUSH APPROVED` in the message that asks for a push.

## 2026-11-14 late - Imagery, CRS and basemaps

**CRS root cause.** `webexport.py` hard-coded EPSG:32636, but NISAR geocodes each frame in the zone
chosen for that frame: Azraq and Wadi Rum are 37N. Every layer of those places was therefore drawn
exactly 6 degrees (one zone) west. The source CRS is now always the cached subset's recorded
projection (`epsg`/`crs_wkt`), never a constant; `03b` picks the zone from the product's own x/y
coordinates rather than from an assumed zone. G0 in the validator fails the build if an overlay
centre is more than 5 km outside its AOI.

**Two chains.** The 60 m multilook + median analysis chain is untouched and still produces every
number. A new display chain (`src/venus/display.py`) uses native 20 m power, one NaN-safe bilinear
warp to EPSG:3857 at about 10-12 m, and pooled 2-98 % dB limits; the RGB recipe itself is unchanged.

**One crop rectangle per place.** The AOI bbox (+5 % margin when it is already valid) is trimmed on
whichever side is least valid until at least 99.5 % of the rectangle is valid, and every layer of
the place uses that rectangle, so swipe and compare align and there are no transparent corners.

**Basemaps.** Default dark = Esri World Dark Gray Canvas with the Esri reference (label) layer in a
dedicated pane above the radar; optional Esri World Imagery with the Esri place-label overlay (all
three endpoints verified 200 on 2026-11-15). The brief's first choice, CARTO dark_nolabels, now
returns tiles stamped "API KEY REQUIRED" without an account, so it is not used. WebP encoding uses
method 4, not 6: method 6 took 87 s per layer and method 4 stays far inside budget. Wadi Rum's
display resolution uses the documented 1.5x-native fallback (17.2 m) to keep its layers under
700 KB; every other place is at 2x native (11.7 m).

## 2026-11-15 - Whole lake, series, context and themes (v3)

**Series is the unit of comparison.** (maturity, CRID, track, direction, polarizations). Layers carry
their series id; the validator refuses a layer whose CRID differs from its series. BETA (X05009) is
browse-only, PROVISIONAL (P05023) is analysed with >= 5 dates, VALIDATED (P05036) is browse until it has
5 dates. Statistics are computed once, for one series, and `water_stats.json` names it.

**Whole-lake window.** dead_sea_full (the configured lake polygon) is the default place. One frame
leaves ~31 % of the AOI outside the swath; frames 151/072 and 151/073 of the same acquisition are
mosaicked in native UTM (mean where both valid), which raises valid coverage to 99.9 %. The display
chain caps the longest side at 3600 px and the pixel budget at 4.5 M, landing at 28.3 m for this place;
analysis stays at 60 m / 20 m with the unchanged method. Display and analysis-derived layers now share
the SAME rectangle so swipe and compare cannot drift.

**NASA context.** GIBS publishes one NISAR GCOV layer, a 3-day best-available mosaic (2026-11-12..14 at
the time of writing). The context layer is drawn only inside that window and never feeds a number; for
any other date the legend says so plainly. No historical GIBS mosaic exists to compare against our
series.

**Themes and motion.** Void (amber/cyan) and Aurora (mint/violet) via CSS variables with localStorage;
prefers-reduced-motion and an explicit toggle disable the intro, cross-fade sweep, fly-to and twinkle.
The mission timeline is one lane per series with the documented instrument gap shaded.
