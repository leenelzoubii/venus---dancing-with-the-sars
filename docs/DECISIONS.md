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
