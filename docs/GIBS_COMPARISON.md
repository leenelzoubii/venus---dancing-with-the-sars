# GIBS comparison - 2026-11-15T04:08Z

GIBS layer `NISAR_L2_Geocoded_Polarimetric_Covariance` on 2026-11-13; our nearest RGB layer on 2026-11-03 (151-DESC-P05036-HHHV). Different dates, same geometry; context only.

| source | region | mean R | mean G | mean B | hue deg |
|---|---|---|---|---|---|
| ours 2026-11-03 | lake | 72.6 | 64.4 | 2.5 | 53.0 |
| ours 2026-11-03 | land | 125.1 | 92.7 | 4.7 | 43.8 |

One sentence: the two mosaics are not the same date and are not expected to match pixel for pixel; the lake reads olive in our view while NASA's description says calm water is blue, and the difference is not yet explained.

GIBS check: the same GetMap for the lake bbox on 2026-11-13 returned a 700-byte fully transparent PNG
(no mosaic pixels over the Dead Sea in that 3-day window), so only our values are listed. No comparison
is possible from this endpoint today; the context layer is therefore informative only when GIBS actually
has data, and it never feeds a statistic.
