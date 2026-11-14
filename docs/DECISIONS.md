# Decisions log

One entry per meaningful choice: **date — decision — reason — alternatives considered**.
Newest at the top. If a decision is reversed, add a new entry rather than editing history.

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
