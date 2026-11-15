# Overnight visual overhaul - run log

Branch: overnight/visual-overhaul (created from main, tag pre-overhaul).
Rules: no invented change, no faked imagery, PROVISIONAL (P05023) never mixed with VALIDATED (P05036).

## PHASE 0 - DIAGNOSE

| place | AOI lon/lat | image lon/lat | km | build CRS | subset EPSG | needed zone | valid px |
|---|---|---|---|---|---|---|---|
| dead_sea_east | 35.550 31.450 | 35.550 31.450 | 0.0 | EPSG:32636 | none (old sidecar) | 36 | 0.937 |
| azraq_wetland | 36.854 31.821 | 30.853 31.821 | 567.5 | EPSG:32637 | 32637 | 37 | 0.959 |
| alwehda_dam | 35.879 32.729 | 35.878 32.729 | 0.1 | EPSG:32636 | 32636 | 36 | 0.938 |
| melehat_sdom | 35.359 30.975 | 35.358 30.974 | 0.2 | EPSG:32636 | 32636 | 36 | 0.954 |
| potash_city | 35.487 31.203 | 35.476 31.192 | 1.6 | EPSG:32636 | 32636 | 36 | 0.946 |
| wadi_rum | 35.450 29.525 | 29.450 29.525 | 581.2 | EPSG:32637 | 32637 | 37(frame) | 0.939 |

Zone hypothesis CONFIRMED: azraq_wetland and wadi_rum are geocoded in UTM 37N (the cached
sidecar says EPSG:32637 and the AOI centre sits 4 m / 8 m from the grid centre in that zone),
but `src/venus/webexport.py` hard-coded CRS_NATIVE = EPSG:32636, so the reprojection labelled
the 37N grid as 36N and shifted every layer exactly 6.0 deg west (one zone) while keeping
latitude. That also skews the footprint. potash_city is 1.6 km off, which is ordinary
raster-grid-centre offset, not a CRS error. The other three are correct.

## PHASE 1 - GEOREFERENCING FIX

PHASE 1 DONE: root cause was `CRS_NATIVE = "EPSG:32636"` in `src/venus/webexport.py`. The cached
subsets record EPSG:32637 for azraq_wetland and wadi_rum, so every layer there was reprojected as
36N: exactly one zone (6 deg) west, latitude unchanged. Fix: the source CRS is now read from each
sidecar (`crs_wkt` / `epsg`) and passed explicitly to every warp; there is no native-CRS constant.
`scripts/03b_fetch_fast.py` now picks the frame zone from the product's own x/y centre (distance test,
not "first overlapping zone"), and records `epsg_source`. Validator (scripts/06) and pytest now fail
if an overlay centre is >5 km outside its AOI or if one place's layers disagree on bounds.
Baselines: docs/baseline_hashes.txt (12 files, sha256).

## PHASE 2 - IMAGERY

PHASE 2 DONE: new `src/venus/display.py` display chain wired into scripts/12 for display layers only.
Native 20 m power -> one NaN-safe bilinear warp to EPSG:3857 at ~11.8 m -> pooled 2/98 dB limits over
all dates -> existing RGB recipe / grey ramp -> 6 px edge feather -> WebP with alpha + preview.
One crop rectangle per place (AOI bbox, trimmed on the least-valid side until >=99.5% valid); all
layers share it. Analysis chain untouched. Deviation: WebP method 4 instead of 6 (87 s vs 2.6 s per
layer; still avg ~100 KB, far inside the 700 KB budget). App: preview-first loading, 20 s timeout +
one retry + visible Retry, idle preload concurrency 2, maxZoom computed from px size, no upscaling.

## PHASE 3 - ORIENTATION AND LABELS

PHASE 3 DONE: CARTO dark_nolabels is the default basemap with dark_only_labels in a dedicated pane
(z-index 650, pointer-events none); Esri World Imagery is the satellite option with the Esri place
labels overlay (one request verified: HTTP 200, image/png, 9107 bytes, 2026-11-14). Basemap switcher,
labels toggle, dim toggle and AOI frame toggle live in the controls. Place card (title, country,
story, centre coordinates from the manifest/config, date range, polarizations), cursor readout in
monospace, and a small locator map with one dot per processed place. Attribution shown on the map.

## PHASE 4 - UI REDESIGN

PHASE 4 DONE (best effort, see gates): full-bleed map with floating brand, place card, collapsible
left controls, right drawer, floating time bar, legend inset, story cards. CSS variables for the
space palette, 1 px hairlines, radius 12, tabular numerals, gold focus ring, one orbiting dot for
loading (disabled under prefers-reduced-motion), static three-gradient star field, inline Venus mark.
Mobile: panels become bottom sheets behind Controls/Panel buttons, targets 44 px, locator hidden.

## PHASE 5 - VERCEL PREP

PHASE 5 DONE: vercel.json validated (JSON parse), web/404.html added, no absolute-path assumptions
found by grep (href="/", src="/", url(/, fetch("/, location.pathname). Vercel CLI authenticated as
leenkhalid2005-8483; preview deploy attempted in FINISH.
## FINISH - gates, numbers, morning todo

Built: 6 places, 288 WebP layers (+288 previews) in web/data, 55.69 MB total (budget 60 MB).
Display pixel size: 11.66-11.87 m for five places; wadi_rum 17.24 m through the documented
"1.5x native instead of 2x" size fallback (its AOI is 22 x 30 km; at 2x it broke 700 KB/layer).
Per-layer size: average 163 KB, maximum 643 KB (budget 700 KB). Before: 340 PNG layers at 60 m,
average 69 KB, 23.9 MB of layer files (the new set is ~5x more pixels per layer and still denser
per pixel). Previews: 288 files, every one <= 15 KB.

Gate table (validator scripts/06: 82 passed, 0 failed; pytest: 73 passed; scripts/07: 9 passed)

| gate | result |
|---|---|
| G0 every overlay centre inside its AOI (+5 km) | PASS (all 6) |
| G1 display layers native 20 m, <= 13 m in 3857 | PASS except wadi_rum 17.24 m (documented fallback) |
| G2 statistics identical to main | PASS (only generated_utc differs; water_stats + offsets) |
| G3 crop >= 99.5 % valid; size budgets | PASS (crops 0.996-0.997; 55.69 MB < 60 MB) |
| G4 zero console errors on all 6 places | PASS (browser run, labels on) |
| G5 label pane above radar | PASS (labels pane z 650, radar 401-403) |
| G7 no layer over 700 KB | PASS (max 643 KB) |
| Lighthouse accessibility desktop / mobile | 100 / 100 |
| first-load weight excluding images | 370 KB (< 400 KB) |

Notes and honest deviations:
- CARTO dark tiles now return tiles stamped "API KEY REQUIRED" (seen in the browser, 2026-11-15), so
  the default dark basemap is Esri World Dark Gray Canvas with its Esri reference (label) layer. Both
  verified HTTP 200. Esri World Imagery + Esri place labels remain the satellite option (verified).
- WebP method 4 instead of 6 (87 s vs 2.6 s per layer); quality and budget are unaffected.
- Change and water layers keep their analysis resolution (60 m and 20 m) but share the display crop
  rectangle, so swipe and compare align exactly.
- The place card sits over the map on narrow screens; panels become bottom sheets behind the
  Controls / Panel buttons.

MORNING TODO
1. Open the site on a real projector (>=1400 px wide) and check the desktop layout, which the
   headless window could not show (it renders at about 1000 px).
2. Decide whether to keep the 1000 px breakpoint at 1100 px or lower it, so laptops get the side panel.
3. If a CARTO API key is available, swap the dark basemap back and re-check attribution; the code has
   one constant for it.
4. Look at the AOI frame on wadi_rum: the frame is larger than the valid-data crop (by design), which
   reads as "analysis area" rather than "image extent". Say if you prefer the frame to follow the crop.
5. Story mode still uses the old six steps and Dead Sea coordinates; steps 2-5 centre on 31.45/35.56
   regardless of place. Needs per-place story coordinates if you want to keep it.
6. Run the Lighthouse numbers on the real network (they were run against localhost).
7. Preview deploy URL and any Vercel project settings: see the chat report / docs/VERCEL_SETUP.md if
   the deploy failed.

## PUSH AND DEPLOY STATUS

Push: none. AGENTS.md is decisive - local git only until the team confirms - so the [B] option was
applied even though [A] would have allowed the branch. Branch overnight/visual-overhaul has five
local commits on top of main; nothing was pushed, no tags, no repository settings, pages.yml untouched.

Vercel: `vercel deploy --yes` (never --prod) succeeded, but Vercel assigned this first deployment of
the project to production and aliased it https://venus-sars.vercel.app. The first upload also 404'd
web/data because `.vercelignore` had `data`, which matched the nested `web/data` too; the pattern is
now `/data` (root only) and a second deployment was made. If a production alias on a first deploy is
not wanted, delete the project or add a domain rule; nothing in GitHub was changed.
Second deployment (preview): https://venus-sars-l4vu5yg37-leen19.vercel.app - Vercel Deployment
Protection is on for previews, so it returns the Vercel login page (text/html) instead of assets to a
logged-out visitor. The public production alias https://venus-sars.vercel.app serves the first upload,
whose web/data was excluded by the old ignore pattern; promoting the fixed deployment would need a
production action, which the brief forbids, so it was left for the morning.

# v3 run (whole lake, series, design)

## PHASE 0 - ORIENT

v2 DONE per this log: CRS-from-subset fix + G0 gate, display chain (native 20 m, WebP), labels and
locator, dark UI, Vercel config. Georeferencing still passes pytest (overlay centre inside AOI +5 km).
Baselines already exist in docs/baseline_hashes.txt, so they were not rewritten.

## PHASE 1 - SERIES CATALOG AND WHOLE-LAKE WINDOW

PHASE 1 DONE: `scripts/01_search_nisar.py` gained --start/--end; searched `dead_sea_full` with no
maturity filter and wrote scenes_dead_sea_full{,_beta,_validated}.csv. Catalog script
`scripts/15_series_catalog.py` groups products into series (maturity, CRID, track, direction, pols):
BETA X05009 from 2025-10-27 (5 dates on 151), PROVISIONAL P05023 9 dates on 151, VALIDATED P05036
2 dates so far on 151. `dead_sea_full` already existed in the YAML; it is now the active place with
display_buffer_km 0 (the lake polygon is its own margin). New `src/venus/mosaic.py` unions the two
adjacent frames (151/072 + 151/073) of one acquisition in native UTM: measured valid fraction rises
from 0.691 (frame 73) to 0.999 (mosaic) over the AOI window, so the whole lake fits without clipping.
`scripts/17_build_series_site.py` builds a multi-series place with per-series stretch limits,
browse-only BETA/VALIDATED, and analysis only for PROVISIONAL >= 5 dates. Longest display side is
capped at 3600 px.

## PHASE 2 - FETCH AND BUILD

PHASE 2 IN PROGRESS: fetching the whole-lake window date by date (both frames per date, atomic
writes) so an interrupted run still has complete mosaics. PROVISIONAL 151 has 9 dates; 5+ completed
with the 0.999 valid mosaic. BETA X05009 (5 dates, Oct 2025 - Jan 2026) and VALIDATED P05036
(2 dates) are queued as browse-only series. Display chain changed for this place: longest side
capped at 3600 px and pixel budget 4.5 M, which lands at 28.3 m for the whole lake (budget-driven);
analysis stays at 60 m / 20 m and is unchanged in method.

## PHASE 3 - NASA CONTEXT LAYER

PHASE 3 DONE (with an honest limit): GetCapabilities on the GIBS EPSG:3857 WMS lists exactly one
NISAR layer, `NISAR_L2_Geocoded_Polarimetric_Covariance`, with a time extent of 2026-11-12..2026-11-14
(no 12-day variant exists). The app therefore draws the GIBS mosaic beneath our imagery only when the
selected date is inside that window, and otherwise says so in the legend: "NASA publishes this NISAR
mosaic only for ...; no mosaic exists for this date. Context is never used for any number." The layer
never feeds a statistic. scripts/14_compare_gibs.py requests one GetMap and writes
docs/GIBS_COMPARISON.md with a neutral sentence.

## PHASE 4-5 - DESIGN, MOTION, SERIES UI

DONE: Void and Aurora themes (CSS variables, two swatches, localStorage), Venus orbit intro (skipped
on repeat visits and reduced motion), cross-fade loading, series chips, mission timeline with per-series
lanes, documented-gap and >=20-day gap shading, maturity badge (BETA/PROVISIONAL/VALIDATED),
series explainer panel, Shift+arrows to change series, reduce-motion toggle, count of dates per series.
The existing date slider remains the keyboard scrubber. Cut for budget: sweep reveal, count-up
numbers, per-series chart colours (charts remain the analysed series only, labelled as such).
## FINISH - v3 numbers and gates

Built dead_sea_full: 79 layers, 3 calibration series, 28.3 m display pixels (longest side 2722 px,
budget-capped), bounds [[31.2950, 35.3014], [31.8839, 35.6313]].
- PROVISIONAL 151-DESC-P05023: 9 dates, 2026-06-24..2026-10-10, analysed (change, water).
- BETA 151-DESC-X05009: 4 dates, 2025-11-08..2026-01-07, browse only (2025-10-27 dropped: one frame
  incomplete, valid 0.82).
- VALIDATED 151-DESC-P05036: 2 dates, 2026-10-22..2026-11-03, browse only ("2 dates so far").
Whole web/data: 107.8 MB (< 220 MB). Largest layer 874 KB (< 900 KB whole-lake budget). WebP q82/75/68
normally, 16 display layers re-encoded at q48 without resampling to meet the per-layer budget.

Primary water numbers (pipeline output, method B on HV; NOT tuned):
- open water area 696.4 to 872.8 km2 across the nine PROVISIONAL dates;
- the +/-1.5 dB band on the first date spans 432.4 to 1159.1 km2, i.e. the band is wider than any
  date-to-date difference in this series, so the honest reading is "no change larger than the spread";
- change-detection limit: 4.0 dB (HV), 1.54 dB (HH).

| gate | result |
|---|---|
| G0 georeferencing (centre inside AOI +5 km) | PASS (validator + pytest) |
| G1 pixel sizes and per-layer budgets | PASS (28.3 m whole lake, 11.7 m others; max 874 KB) |
| G2 existing places' statistics unchanged | PASS (12/12 files identical except generated_utc) |
| G3 series integrity (no mixed CRID/maturity) | PASS (97 validator checks) |
| G4 zero console errors | PASS (dead_sea_full 3 chips/15 dots; dead_sea_east legacy) |
| G5 Lighthouse accessibility | PASS (desktop 97, mobile 96; target-size only remaining) |
| G6 lake not touching the display edge | FAIL - see below |
| pytest / scripts 06 / 07 / 99 | 76 / 97 / 9 / 10 passed, 0 failed |

G6 BLOCKED: `scripts/18_check_lake_edge.py` finds open-water pixels on the display border on all 9
PROVISIONAL dates. Cause: the configured AOI polygon (and therefore the fetched window) ends at the
lake's own bbox, most likely clipping the southern evaporation ponds; there is no margin left to trim
to. Fix needs a widened AOI (about +0.05 deg south/east) and a refetch of both frames for each date
(about 2 h), which did not fit this run. The displayed lake is complete to the AOI boundary; the
statistics cover exactly that window and the app outlines it as the analysis area.

## MORNING TODO (v3)
1. Widen dead_sea_full's polygon south/east by ~0.05 deg, refetch (both frames per date), rebuild, and
   re-run scripts/18 until G6 passes. Expect ~2 h of downloads.
2. Check the water area against the published Dead Sea area (about 605 km2). Our 696-873 km2 suggests
   the two-step threshold is picking up dark terrain or ponds; review the threshold per date, do not
   tune it to a target number.
3. Fetch the one dropped BETA date (2025-10-27) once its second frame completes.
4. GIBS: the advertised mosaic returned a fully transparent PNG over the Dead Sea on 2026-11-13, so the
   context layer is currently only a labelled, inert option. Re-check GIBS coverage later.
5. Lighthouse target-size on the timeline dots: 24 px targets still touch on the mobile width; widen the
   axis or thin the dots if you want 100.
6. Vercel: previous run's first deployment became production; previews are login-protected. Promote or
   recreate the project by hand.
'@; "log finish written"
