# Demo script

## Before you start

Open the live app: https://leenelzoubii.github.io/venus---dancing-with-the-sars/

Every view below is a URL you can bookmark. The app stores its state in the hash, so each link opens
exactly the view described.

## 60-second version

1. **Open the default view.** Say: "Six places in Jordan, seen by radar that works through cloud and at
   night. This is the same way we know the surface of Venus."
2. **Point at the picture.** Say: "This is not a photograph. It is a false-colour composite of how much
   radar came back: green is vegetation structure, orange and yellow are rough or built ground."
3. **Switch place to Potash City.** Say: "The evaporation ponds and salt crust here change because of
   industry. That is the human-driven change the challenge asked for."
4. **Switch layer to Change map.** Say: "Blue means less echo than the first date, orange means more.
   We removed a scene-wide offset first, and we print that offset on the layer."
5. **Switch layer to Water mask, turn on the detection limit.** Say: "Cyan is water, amber is the band
   where the answer could flip. The shoreline change we can measure is smaller than that band, so we do
   not claim it."

## 3-minute version

1. Story mode, steps 1 to 3 (`Start the story`, then `Next` twice). Sets the scene, then the physical
   reason water is dark and why every water number uses HV.
2. Story mode, step 4. Two water masks either side of a swipe divider, with the detection band on top.
   This is the honest core: the change is real to look at, and still smaller than the uncertainty.
3. Story mode, step 5. Candidate patches on the eastern plain, with the time series and the empty
   confidence fields. Say plainly: "These are questions."
4. Switch to Melehat Sdom. Say: "The shallow southern basin, where the shoreline has moved most."
5. Switch to Wadi Rum. Say: "The desert control. If our method invented water change, it would show up
   here. It does not."
6. Open `Layer information`. Say: "Every layer states its date, product, CRID, polarization, both
   coordinate systems, and the ordered processing steps. Nothing is hidden."

## Hero views (bookmark these)

| View | URL |
|---|---|
| Dead Sea, false colour, latest date | `/?place=dead_sea_east&layer=rgb` |
| Dead Sea, change map | `/?place=dead_sea_east&layer=change` |
| Dead Sea, water mask plus band | `/?place=dead_sea_east&layer=water&band=1` |
| Potash City, false colour | `/?place=potash_city&layer=rgb` |
| Melehat Sdom, water mask | `/?place=melehat_sdom&layer=water` |
| Wadi Rum, desert control | `/?place=wadi_rum&layer=rgb` |
| Al-Wehda Dam | `/?place=alwehda_dam&layer=rgb` |
| Debug view (bounds, crosshair) | `/?place=dead_sea_east&layer=rgb&debug=1` |

## If the internet fails

Open `web\index.html` on your own machine by double-clicking it.

- The radar layers work offline: they are local files.
- The satellite basemap does not load; the app says "Basemap unavailable offline; radar layers still
  work" instead of failing silently.
- Numbers, charts and layer information all read from local files, so the story still holds.

Worst case, use the screenshots in the submission pack and narrate the same six places.
