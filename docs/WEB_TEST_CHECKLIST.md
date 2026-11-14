# Web app test checklist

Status key: **[x]** done and seen working, **[~]** partly checked, **[ ]** not done. Each item says how it was
checked. Run this again after any change to `web/`.

## Automatic

- [ ] `python scripts/07_check_web.py` exits 0 (local references, manifest layer files, data wrappers, string keys)
- [ ] `python -m pytest -q` passes
- [ ] `python scripts/06_validate_web_assets.py` exits 0 (PNG sizes, bounds, json and js twins, provisional only)

## Opening the page

- [ ] Double-click `web\index.html`: the map, layers and charts appear with no server (file://)
- [ ] `python -m http.server 8000 --directory web`, then `http://localhost:8000/index.html`: same result
- [ ] Console has no errors or warnings on load (both modes)

## Swipe

- [ ] Turn on "Compare two states", drag the divider at the shoreline: the left and right dates swap cleanly
- [ ] Move the divider with the keyboard (focus it, Left and Right arrows, Shift for larger steps, Home and End)
- [ ] Pan and zoom with the divider in place: the split stays on the same screen position relative to the imagery
- [ ] Date labels on the left and right name the right dates and layers
- [ ] Legend shows both sides; layer information shows left and right rows

## Time slider and play

- [ ] Drag the time slider through all dates; the labels and the date select stay in step
- [ ] Play: the whole series runs in about 12 s; Pause stops it; `aria-pressed` changes
- [ ] Loop on: playback restarts from the first date; Loop off: playback stops at the last date
- [ ] Stepping across the outage (18 Jul to 11 Aug) shows the outage note; the outage tick is marked on the scale
- [ ] With reduced motion enabled in the OS, nothing starts playing on its own

## Change layer and detection limit

- [ ] Change map on the reference date shows the "no change to show" note
- [ ] Change legend reads weaker echo (blue) / no change / stronger echo (orange) with the manifest limits
- [ ] The offset note links to the offset panel (opens it) and says the cause is not understood
- [ ] Water mask on, "Show detection limit" on: amber band appears; caption numbers match `water_stats.js`

## Charts

- [ ] Area chart: band drawn as a shaded range; HH dashed; axis labelled as not starting at zero; outage shaded
- [ ] Area chart: the values table lists each date; the verdict sentence matches `water_stats.js`
- [ ] Offset chart: HH and HV lines; outage shaded; sentence says the cause is unresolved

## Patches

- [ ] Show candidate patches: with no patches, the note says so and nothing is drawn
- [ ] With a sensitivity-run export (`05_export_web_assets.py --patches-tag _sensitive`), clicking a numbered marker opens the patch panel
- [ ] Patch panel: area, first date, dates changed, sparkline with the outage marked
- [ ] Any hypothesis is prefixed "Hypothesis:" and shows a confidence word; empty human fields say "Not yet assessed"

## Keyboard only

- [ ] Tab order reaches every control; focus outlines are visible
- [ ] Layer, polarization and date controls operate with the keyboard
- [ ] The play button toggles with Enter or Space
- [ ] The skip link jumps to the map

## Narrow window and touch

- [ ] Below 1100 px the layout stacks: map, controls, panels
- [ ] Below 600 px the map and sliders remain usable; the PROVISIONAL badge stays visible
- [ ] Divider and sliders work by touch (pointer events) - not tested on a real touch device

## URL state

- [ ] After changing controls, the hash shows date, layer, pol (and swipe, split, band, patches when set)
- [ ] Reloading the page with that hash restores the same view
- [ ] Nothing sensitive appears in the hash

## Not yet checked in this session

- Real touch device: not available.
- Real offline run (network off): only the basemap error handler was exercised.
- Google Fonts offline: system fallbacks are set but not tested.
- GitHub Pages sub-path: relative paths only; not deployed.
