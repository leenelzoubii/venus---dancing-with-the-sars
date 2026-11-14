# Science notes — plain-language explanations to reuse in the pitch

Written for a general audience. Each note is short on purpose: it should survive being said out loud
in a 30-second pitch. Claims that need a citation are marked **cite**.

## What radar actually does

A camera waits for sunlight and records colour. Radar is the opposite: it **shouts a radio pulse and
listens for the echo**. Because it brings its own energy, it works at night and through cloud — which is
why Venus, permanently cloud-wrapped, was mapped by radar, and why we can read Earth the same way.

## Backscatter, in one paragraph

The strength of the returning echo is called **backscatter**. It depends mainly on two things:

- **Roughness** — a surface rough at the scale of the radar wavelength (L-band ≈ 24 cm) scatters energy
  in many directions, and some comes back to the satellite: **bright**. A surface smooth at that scale
  acts like a mirror and sends the pulse away: **dark**.
- **Dielectric constant** — how strongly the material responds to the electric field. Liquid water has
  a high dielectric constant, so wet ground and vegetation scatter differently from dry ground.

**Consequence for us:** open water is one of the darkest things in a radar image. On a lake, the
shoreline draws itself.

## What "dB" means and why we use it

Backscatter spans several orders of magnitude, so we compress it logarithmically:

```
dB = 10 * log10(power)
```

A change of **3 dB ≈ a factor of 2** in power; **10 dB = a factor of 10**. On our maps, reading a
difference is therefore easy: −3 dB means "half as much echo came back", which is what happens when dry
land becomes water.

**Careful:** NISAR GCOV diagonal terms are already **power** (gamma-0). If you ever feed an *amplitude*
image, the formula changes to `20*log10`. Mixing the two silently doubles every number in dB.

## Polarization, briefly

Radar pulses can be transmitted and received with horizontal (H) or vertical (V) polarization.

- **HH** (send H, receive H) — sensitive to surface roughness and to **double-bounce** geometry
  (e.g. a building or a tree trunk against flat ground). Good for shorelines, infrastructure, water.
- **HV** (send H, receive V) — the cross-polarized channel. Flat surfaces barely depolarize, so HV is
  **dark over open water** and responds to **volume scattering** inside vegetation canopies. Good for
  separating water from wet vegetation and for seeing structure. **cite**

Because the two channels respond to different physics, showing HH and HV side by side is not decoration
— it is an argument.

## Speckle

A radar pixel is not a single measurement but the sum of many small scatterers interfering with each
other. The result looks grainy — **speckle**. Averaging neighbouring pixels (multi-looking) or filtering
(boxcar, median, Lee) reduces it, at the cost of resolution. Rule of thumb for us: smooth enough to read
the pattern, not so much that a 30 m shoreline shift disappears.

## Why "same geometry" is non-negotiable

The satellite looks sideways, at an angle. Two passes with a different track, frame or direction see the
same ground from different angles, so slopes brighten or darken purely because of geometry — hills cast
longer shadows, surfaces tilt toward or away from the beam. Compare those and you will "discover" change
that never happened. So: **same track, same frame, same flight direction, always.**

## Reading the Dead Sea

- **The lake is falling.** The Dead Sea has no outlet; water leaves only by evaporation, and inflow from
  the Jordan River has been reduced. The surface has been dropping roughly a metre per year. **cite**
- **What we should see in radar:** the water is dark and stable; as the shore retreats, a strip that was
  once dark water becomes exposed, rough, salt-crusted ground and turns brighter. A shrinkage of the
  lake should therefore appear as a bright fringe growing along the shore.
- **Honesty check:** a 0.3 m level drop over 3.5 months moves the shoreline by metres to tens of metres —
  which is only a few pixels at 20 m resolution, and steeper shores move less. **Hypothesis:** we will
  see it best on gently sloping mudflats, not against steep cliffs.
- **Sinkholes.** Dissolution of salt layers by fresher groundwater creates cavities that collapse —
  documented along the Ghor Haditha area. At 20 m pixels a single sinkhole is sub-pixel; a cluster may
  show as a small bright/dark speckle change. **Hypothesis, not a finding, until we look.**
- **Salt crusts and wet mud** both complicate the "water = dark" rule: a wet salt crust can be bright,
  and wind ruffles the lake surface and makes open water brighten. Any water mask must be sanity-checked
  against known open-water areas before we quote an area.

## The mission gap we must explain, not hide

NISAR has a documented data gap from `2026-07-27T22:03Z` to `2026-08-10T00:55Z`. Our series therefore
skips from 2026-07-18 to 2026-08-11. The gap is a spacecraft fact, not a bug in our code — and admitting
it is part of being credible.

## NISAR facts worth quoting

- Joint **NASA–ISRO** mission; L-band (NASA) and S-band (ISRO) radars on one platform.
- **12-day** nominal repeat cycle: the same ground track is revisited every 12 days.
- NISAR's L-band penetrates cloud, rain (mostly) and vegetation canopy, and can measure ground motion
  at the centimetre scale (interferometry).
- L-band (≈24 cm wavelength) is longer than Sentinel-1's C-band (≈5.6 cm), so it holds coherence better
  over vegetation and sees deeper into canopies — a key reason NISAR matters for biomass and wetlands.

## Citations to collect before the final pitch

- Dead Sea water-level trend and its drivers. **cite**
- Sinkhole formation along the Jordanian Dead Sea shore (Ghor Haditha). **cite**
- HH vs HV scattering behaviour, from a NASA/ASF SAR primer. **cite**
- NISAR mission parameters (frequency, repeat cycle, resolution). **cite** (user guide / JPL)
