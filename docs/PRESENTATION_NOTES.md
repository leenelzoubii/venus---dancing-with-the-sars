# Presentation notes — talking points and demo script

Draft. Keep the demo under 4 minutes; judges remember one image and one sentence.

## The 20-second opening

> Venus is wrapped in permanent cloud. We only know its surface because radar sees through it.
> Our project reads Earth the same way — and the place we point it at is a lake that is disappearing
> on our doorstep.

## The 30-second science

- Radar brings its own light: it works at night, through cloud and through smoke.
- It measures **roughness** and **wetness**, not colour. Open water answers almost not at all, so it
  goes black; rough, salt-crusted ground answers loudly, so it goes white.
- NISAR revisits the same ground track every 12 days. Same geometry, so a change in brightness is a
  change on the ground — not a change in the viewing angle.

## The demo (in order, ~2.5 minutes)

1. **Map, one date.** "This is the Dead Sea seen by NISAR on <date>. Black is water. That black shape is
   the lake."
2. **Swipe 2026-06-24 → 2026-10-10.** "Watch the shoreline. <state honestly what is visible>."
3. **Change layer.** "Red is where the echo dropped — surfaces that became smoother or wetter.
   Blue is where it rose. The fringe along the shore is the story."
4. **Polarization toggle.** "HH and HV respond to different physics. HV goes dark over water very
   cleanly, which is why we use it for the water mask."
5. **The number.** "The mapped water surface changed by <X> km² between the first and last date —
   with the caveat that wind and salt crusts can move that number by a few percent."
6. **Limitations, said out loud, confidently.** Three dates is not a trend; 20 m pixels cannot resolve a
   single sinkhole; there is a known mission gap in late July/August; PROVISIONAL calibration.

## The "why it matters" close

> The Dead Sea is a closed basin: it only loses water by evaporation. Every metre it falls strands the
> shore, exposes salt, and destabilises the ground people farm and drive on. NISAR will not refill it —
> but a 12-day, all-weather record of where the water actually is turns a slow emergency into something
> you can watch, measure and argue about with evidence.

## Answers to the questions judges will actually ask

- **"Why NISAR and not Sentinel-1?"** L-band, 12-day revisit, designed for exactly this; and it is the
  mission this challenge is about. Different wavelength = different sensitivity to vegetation and
  roughness — we can talk about what that changes.
- **"Is this calibrated?"** PROVISIONAL products, fully calibrated and partially validated; we state the
  CRID and the maturity on every layer.
- **"What is the physical driver?"** Hypothesis: lake-level decline (evaporation exceeds inflow) plus
  industrial pond management. We separate what the data shows from what we infer.
- **"What future applications?"** Water accounting in closed basins, wetland monitoring (Azraq), sinkhole
  early warning, dam/reservoir management, and — the mission's own goal — global, all-weather change
  detection at 12-day cadence.

## Numbers to fill in as soon as they exist

- [ ] exact dates of first/last usable acquisition
- [ ] mapped water area per date (km²), with method and threshold
- [ ] dB range of the change layer, and the threshold used
- [ ] footprint size in km and pixel count
- [ ] the product names (copy verbatim) for the two dates shown
