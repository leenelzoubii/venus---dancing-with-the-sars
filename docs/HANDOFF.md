# Handoff: day two

## Where it stands

Six places processed and live: Dead Sea east shore (9 dates), Potash City (7), Azraq Wetland (10),
Melehat Sdom (9), Wadi Rum (10), Al-Wehda Dam (9). Each has a false-colour composite per date, calibrated
backscatter, change layers against the first date, and water plus detection band where HV exists.

Gates: `pytest` 63 passing, `06_validate_web_assets.py` 14 passing, `07_check_web.py` 9 passing,
`99_release_check.py` 10 passing.

## Known bugs and rough edges

1. Potash City shows 7 of 9 dates. Two dates were fetched by the old reader and have a different window
   shape, so the builder drops them rather than misalign. Refetch with `--force` to get all 9.
2. Azraq Wetland and Wadi Rum are single-polarization HH. No water series, no dual-pol composite; they
   use the single-pol ramp, which is our approximation of NASA's.
3. About 7 to 8 percent of Dead Sea water pixels sit outside the main lake body (dark terrain or radar
   shadow). Not removed.
4. The scene offset is measured and removed but not explained.
5. The composite shows the place window, not the full satellite frame that ASF Vertex shows.

## Stretch ideas, in priority order

1. **Validated products over a longer series.** CRID P05036 from 2026-10-21. Keep it as its own labelled
   series and never mix it into the provisional one.
2. **Patch hypothesis tests.** The three candidates at 1 dB need optical imagery and, ideally, local
   knowledge. The analyst columns in `docs/patch_log.csv` are still empty.
3. **GUNW/GSLC availability check.** Not yet determined for these track/frame pairs. If available, this
   is the route to subsidence and sinkholes, and it is a different pipeline, not a re-run.
4. **Arabic interface.** Strings are isolated in `web/js/strings.js`; needs a native reader to review.
5. **Remaining eight places.** All have confirmed archive coverage; the config already lists them.

## Regenerate everything

```bash
# per place: search, fetch, build
python scripts/01_search_nisar.py --aoi <place> --out data/interim/scenes_<place>.csv
python scripts/03b_fetch_fast.py --aoi <place> --stack <track/frame/DIR> --all --scenes data/interim/scenes_<place>.csv
python scripts/12_build_place_site.py --aoi <place>

# then the shared files and the gates
python scripts/10_build_places.py
python scripts/13_build_assistant_context.py
python -m pytest -q
python scripts/06_validate_web_assets.py
python scripts/07_check_web.py
python scripts/99_release_check.py
git add -A && git commit && git push origin main
```

Stacks used: dead_sea_east 151/073 DESC, potash_city 100/017 ASC, melehat_sdom 100/017 ASC,
azraq_wetland 50/072 DESC, wadi_rum 50/074 DESC, alwehda_dam 151/072 DESC.
