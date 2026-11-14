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
image, the formula changes to `20*log10`. Mixing the two silently doubles every number in dB. Our
products state the rule themselves: `outputBackscatterDecibelConversionFormula = 10*log10(<GCOV_TERM>)`.

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

## What we measured (Dead Sea, 2026-06-24 and 2026-10-10)

These numbers are measured, not assumed, and they contradicted the textbook on the first try — which
makes them a good story rather than a problem.

**1. Water is not as dark as the textbook says.** L-band gamma-0 over the open lake:

| channel | open water | shore / salt crust | separation |
|---|---|---|---|
| HH | ≈ −13.7 dB | −13 … −5 dB | ~6 dB, and the water mode touches the dark end of the land mode |
| HV | ≈ −20.5 dB | −18 … −11 dB | clean gap, valley at ≈ −19 dB |

So **HV is the channel to map water with**; HH is better for texture and shoreline structure. That is
exactly the physics the primer describes — cross-polarized returns need volume scattering, and a flat
water surface delivers almost none — but quoting −20 dB for HH would have mapped the lake wrongly.

**2. Two images are not two identical measurements.** Between June and October the *whole* scene got
darker in HV by ≈ 0.8 dB and brighter in HH by ≈ 0.4 dB — on water and on land alike. A real surface
change cannot brighten land and darken water in opposite directions by a constant, so we treat this as
a **scene-wide radiometric offset** and remove it before reading the change map. Whether it is
calibration drift across the PROVISIONAL series or genuine seasonal drying is **not decidable from two
dates** — it is a stated limitation, not a finding.

**3. The water area is stable; the trend is not yet visible.** With per-image (Otsu) thresholds:

| channel | 2026-06-24 | 2026-10-10 | net |
|---|---|---|---|
| HH | 137.5 km² | 135.7 km² | −1.7 km² |
| HV | 140.1 km² | 140.9 km² | +0.8 km² |

The two channels disagree in sign at the ±2 km² level, and moving the threshold by 1.5 dB swings the
area by ±15 km². **Honest conclusion: the shoreline shift over these 3.5 months is smaller than our
method's uncertainty at 20 m resolution.** Saying that out loud is stronger than inventing a trend.

**4. Multi-looking is what makes change visible.** At native 20 m, a single difference image is 90 %
speckle. Averaging 3×3 blocks **in power** (60 m output, ~9× less variance) reveals structure: the
lake brightens (wind roughening of the surface) while parts of the eastern plain darken. Those
patterns still need a physical explanation before they become claims.



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

---

# Hour 1 additions (2026-11-14) - thresholds, offsets and why HH fails

## Backscatter in one line

Radar sends a pulse and measures how much comes back. A smooth surface (open water) bounces the pulse
away from the satellite, so the return is weak and the pixel looks dark; a rough or structured surface
sends energy back in many directions, including toward the satellite, and looks bright. We report that
return in decibels, 10*log10(power).

## Why HV is the water channel

HH (horizontal send, horizontal receive) is dominated by smooth-surface reflection and double-bounce
off walls and salt crusts, and it is bright: on this window land runs -13 to -5 dB while water sits at
about -13.7 dB. The two populations overlap, so no single HH threshold can separate lake from shore.
HV (horizontal send, vertical receive) only gets a return from volume scattering and rough surfaces,
so the whole scene is quieter: water near -20.5 dB, land -18 to -11 dB. The gap is about 7 dB, which
is why every water number we publish is HV.

## What a scene-wide offset is

Compare two dates and the whole scene is a few tenths of a dB brighter or darker, water and land
alike. Real surface change does not do that: a drying lake bed does not brighten the desert 20 km
away. So we measure it as the median of (date minus reference) over stable land only, remove it before
differencing, and print the value on the figure. HH and HV offsets even have opposite signs
(+0.42 and -0.78 dB between June and October), which is further evidence that it is instrumental or
seasonal rather than a surface process.

## Why Otsu is biased here

Otsu picks the split that maximises the variance between two classes, and it assumes both classes are
roughly equally common. In this window land covers far more pixels than water, so Otsu moves the cut
toward the land mode: it returns about -17 dB when the histogram valley is nearer -19 dB. Every extra
0.1 dB higher costs several km2 of lake. That is why the area is quoted with a band and why we compare
several estimators instead of trusting one.

## Mask semantics (verified from the product attributes, not assumed)

The GCOV ``mask`` layer is not a 0/1 validity flag: it is the **subswath number**. 0 means at least
one radar sample in the averaging set was partially focused or invalid, 1-3 mean valid data from that
subswath, and 255 marks pixels outside the radar acquisition. Our window sits in subswath 1, where
99.996 percent of pixels carry mask == 1.

## Hour 2 notes

- **Detection limit versus band.** The +/-1.5 dB band answers how sure we are of one date's area. Whether
  two dates differ is a separate question, answered by the sign-robustness check and the offset
  uncertainty.
- **Persistence.** Speckle does not repeat from one date to the next, so a real surface change should
  survive a two-date test while noise does not. This is the cheapest honest filter we have.
- **Web Mercator is not metric.** A Web Mercator pixel is stretched by about 1 / cos(latitude), roughly 16
  percent at 31 degrees north. Area must be computed in UTM (or with the cos^2 correction), never from
  the image pixel count.
