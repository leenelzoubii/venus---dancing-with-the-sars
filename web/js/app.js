/*
 * app.js - the map, the radar layers, swipe, play, patches and the URL state.
 * Reads window.VENUS (data), window.VENUS_UI (panels) and window.VENUS_CHARTS (SVG). No fetch().
 *
 * Overlay rules (unchanged from Hour 3, extended):
 *   - each image is an L.imageOverlay at the bounds stored in the manifest; bounds are never recomputed;
 *   - a new image fades in only after it has loaded; a load that is no longer wanted is discarded;
 *   - the swipe "before" and "after" are two slots in their own panes; each is clipped to its side of the
 *     divider using the image's on-screen rectangle, so the split stays aligned on pan and zoom;
 *   - only the visible image and its neighbours are requested; play preloads the series first.
 */
(function () {
  "use strict";

  var V = window.VENUS || {};
  var M = null;                    // manifest of the place currently loaded
  var PLACE = new URLSearchParams(window.location.search).get("place");
  var UI = window.VENUS_UI;
  var DEBUG = new URLSearchParams(window.location.search).get("debug") === "1";

  // Esri World Imagery (terms: docs/DATA_SOURCES.md). Displayed only, never cached or exported.
  var BASEMAP_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  var ESRI_LABELS_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
  // Dark basemap: Esri World Dark Gray Canvas. CARTO's dark tiles were the brief's first choice, but
  // on 2026-11-15 every tile came back stamped "API KEY REQUIRED", so they are not usable without an
  // account. The Esri dark canvas and its reference (label) layer need no key: both verified HTTP 200
  // (image/jpeg and image/png) on 2026-11-15.
  var DARK_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}";
  var DARK_LABELS_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}";
  // NASA GIBS NISAR GCOV mosaic (context only). GetCapabilities on 2026-11-15 lists one layer id and
  // a time extent of 2026-11-12..2026-11-14, so context is shown only for dates inside that window.
  var GIBS_URL = "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi";
  var GIBS_LAYER = "NISAR_L2_Geocoded_Polarimetric_Covariance";
  var GIBS_TIMES = ["2026-11-12", "2026-11-13", "2026-11-14"];

  var OPACITY = { rgb: 1, backscatter: 0.92, change: 0.9, water: 1, band: 1 };
  var PLAY_TOTAL_MS = 12000;           // the whole series plays in about 12 seconds

  var state = {
    index: 0, layer: "backscatter", pol: "HV",
    place: "dead_sea_east", swipe: false, leftIndex: 0, leftLayer: "backscatter", split: 50,
    band: false, patches: false,
    playing: false, loop: false,
    basemap: "dark", labels: true, aoiFrame: true, dim: true,
    seriesId: null, context: true, contextOpacity: 0.6
  };
  var map = null, bounds = null, overlays = null, patchLayer = null, selectedPatch = null;
  var slots = {
    main: { overlay: null, preview: null, pending: null, wanted: null, timer: null },
    left: { overlay: null, preview: null, pending: null, wanted: null, timer: null },
    band: { overlay: null, preview: null, pending: null, wanted: null, timer: null }
  };
  var playTimer = null;
  var debugOpacity = null;
  var baseLayers = { dark: null, satellite: null };
  var labelLayers = { dark: null, satellite: null };
  var aoiLayer = null;
  var locator = null;
  var preload = { generation: 0, queue: [], active: 0 };

  /* ---------------------------------------------------------------- lookup */

  function find(kind, pol, date) {
    for (var i = 0; i < M.layers.length; i++) {
      var layer = M.layers[i];
      if (layer.kind !== kind || layer.date !== date) continue;
      if (state.seriesId && layer.series && layer.series !== state.seriesId) continue;
      if (kind === "water" || kind === "band" || kind === "rgb" || layer.polarization === pol) return layer;
    }
    return null;
  }

  // What the controls ask for at one date. Returns {def, note}; note explains an empty result.
  function resolve(layerKind, pol, index) {
    var date = M.dates[index];
    if (layerKind === "rgb") {
      return { def: find("rgb", "HH+HV", date), note: null };
    }
    if (layerKind === "water") {
      if (pol !== "HV") return { def: null, note: UI.t("water_hh_note") };
      return { def: find("water", "HV", date), note: null };
    }
    if (layerKind === "change") {
      if (date === M.reference_date) return { def: null, note: UI.t("change_reference_note") };
      return { def: find("change", pol, date), note: null };
    }
    return { def: find("backscatter", pol, date), note: null };
  }

  function bandLayerFor(index) {
    return find("band", "HV", M.dates[index]);
  }

  function bandDb() {
    var any = M.layers.filter(function (l) { return l.kind === "band"; })[0];
    return any ? any.band_db : undefined;
  }

  // Manifest paths are relative to web/data/, so the page prefixes the data folder.
  function imageUrl(def, preview) {
    var placeName = (M && M.place && M.place.name) || "dead_sea_east";
    if (preview && def.preview) return "data/" + placeName + "/" + def.preview;
    return "data/" + placeName + "/" + def.file;
  }

  function opacityFor(def) {
    return debugOpacity !== null ? debugOpacity : OPACITY[def.kind];
  }

  /* --------------------------------------------------------------- series */

  function seriesList() {
    if (M.series && M.series.length) return M.series;
    return [{
      id: M.primary_series || "series-1", label: M.maturity + " series", maturity: M.maturity,
      crid: M.crid, track: M.track, direction: M.direction, dates: M.dates,
      polarizations: M.polarizations, analysis: true
    }];
  }

  function activeSeries() {
    var list = seriesList();
    for (var i = 0; i < list.length; i++) if (list[i].id === state.seriesId) return list[i];
    return list[0];
  }

  function applySeriesDates() {
    var series = activeSeries();
    M.dates = series.dates.slice();
    M.reference_date = series.dates[0];
  }

  function selectSeries(id, index) {
    if (!id) return;
    state.seriesId = id;
    applySeriesDates();
    state.index = index === undefined ? M.dates.length - 1 : Math.max(0, Math.min(M.dates.length - 1, index));
    state.leftIndex = 0;
    preload.generation += 1;
    UI.initDates(M.dates, state.index, M.reference_date, UI.outageIndices(M.dates));
    render();
    renderSeriesChips();
    renderTimeline();
    updateBadge();
    renderContext();
    renderCharts();
    updateSeriesNote();
  }

  function updateSeriesNote() {
    var note = document.getElementById("series-dates-note");
    if (!note) return;
    var series = activeSeries();
    note.textContent = UI.t("maturity_dates_so_far", { n: series.dates.length }) +
      (series.analysis ? "" : " " + UI.t("browse_only_note"));
  }

  function updateBadge() {
    var el = document.getElementById("maturity-badge");
    if (!el) return;
    var series = activeSeries();
    var maturity = String(series.maturity || M.maturity || "PROVISIONAL").toUpperCase();
    el.textContent = UI.t("badge_" + maturity.toLowerCase(), { n: series.dates.length });
    el.className = "badge " + (maturity === "BETA" ? "badge-beta"
      : maturity === "VALIDATED" ? "badge-validated" : "badge-provisional");
  }

  function renderSeriesChips() {
    var host = document.getElementById("series-row");
    if (!host) return;
    host.innerHTML = "";
    seriesList().forEach(function (series) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "series-chip " + String(series.maturity).toLowerCase();
      button.setAttribute("aria-pressed", String(series.id === state.seriesId));
      var dot = document.createElement("span");
      dot.className = "dot";
      button.appendChild(dot);
      button.appendChild(document.createTextNode(UI.t("series_chip", {
        track: series.track, direction: String(series.direction).slice(0, 4).toLowerCase(),
        maturity: series.maturity, n: series.dates.length
      })));
      button.addEventListener("click", function () { selectSeries(series.id); });
      host.appendChild(button);
    });
  }

  function renderTimeline() {
    var host = document.getElementById("mission-timeline");
    if (!host) return;
    host.innerHTML = "";
    var all = [];
    seriesList().forEach(function (series) { all = all.concat(series.dates); });
    if (!all.length) return;
    var toTime = function (day) { return Date.parse(day + "T00:00:00Z"); };
    var times = all.map(toTime);
    var min = Math.min.apply(null, times);
    var max = Math.max.apply(null, times.concat([Date.now()]));
    var span = Math.max(max - min, 1);
    var pos = function (day) { return (toTime(day) - min) / span * 100; };
    var gapStart = "2026-07-27", gapEnd = "2026-08-10";

    seriesList().forEach(function (series) {
      var lane = document.createElement("div");
      lane.className = "timeline-lane";

      function gap(a, b, title) {
        var element = document.createElement("div");
        element.className = "timeline-gap";
        element.style.left = pos(a) + "%";
        element.style.width = Math.max(0.3, pos(b) - pos(a)) + "%";
        element.title = title;
        lane.appendChild(element);
      }
      if (toTime(gapEnd) > min) gap(gapStart, gapEnd, UI.t("gap_instrument"));

      series.dates.forEach(function (day, index) {
        if (index > 0 && (toTime(day) - toTime(series.dates[index - 1])) / 86400000 >= 20) {
          gap(series.dates[index - 1], day, UI.t("gap_computed"));
        }
        var dot = document.createElement("button");
        dot.type = "button";
        dot.className = "timeline-dot " + String(series.maturity).toLowerCase();
        dot.style.left = pos(day) + "%";
        dot.title = UI.fmtDate(day) + " - " + series.label;
        dot.setAttribute("aria-label", UI.fmtDate(day) + ", " + series.label);
        dot.setAttribute("aria-pressed",
          String(series.id === state.seriesId && index === state.index));
        dot.addEventListener("click", function () { selectSeries(series.id, index); });
        lane.appendChild(dot);
      });
      host.appendChild(lane);
    });

    var months = document.createElement("div");
    months.className = "timeline-months";
    var cursor = new Date(min);
    cursor.setUTCDate(1);
    while (cursor.getTime() <= max) {
      var mark = document.createElement("span");
      mark.style.left = pos(cursor.toISOString().slice(0, 10)) + "%";
      mark.textContent = cursor.toLocaleString("en", { month: "short", year: "2-digit", timeZone: "UTC" });
      months.appendChild(mark);
      cursor.setUTCMonth(cursor.getUTCMonth() + 3);
    }
    host.appendChild(months);
    var legend = document.createElement("div");
    legend.className = "timeline-legend";
    legend.textContent = UI.t("timeline_legend");
    host.appendChild(legend);
  }

  /* ------------------------------------------------------------------ map */

  function placeInfo() {
    var place = placeByName((M && M.place && M.place.name) || state.place);
    return place || { bounds: M.bounds, title: (M.place && M.place.title) || state.place };
  }

  function aoiBounds() {
    return L.latLngBounds(placeInfo().bounds);
  }

  // Deep-zoom limit from the real display pixel size. Past it the browser would only stretch pixels.
  function maxZoomForManifest() {
    var px = M.layers[0] && M.layers[0].px_size_m_3857 ? M.layers[0].px_size_m_3857 : 12;
    return Math.max(11, Math.floor(Math.log2(156543.03 / px)) + 1);
  }

  function initMap() {
    bounds = L.latLngBounds(M.bounds); // [[south, west], [north, east]] from the manifest
    var maxZoom = maxZoomForManifest();
    var aoi = aoiBounds();
    var limit = L.latLngBounds(
      [aoi.getSouth() - 0.75, aoi.getWest() - 0.75],
      [aoi.getNorth() + 0.75, aoi.getEast() + 0.75]
    );
    map = L.map("map", {
      minZoom: 8,
      maxZoom: maxZoom,
      zoomSnap: 0.25,
      maxBounds: limit,
      maxBoundsViscosity: 0.7,
      zoomControl: true
    });
    // Panes make the stacking explicit: radar images, then patches, then the label layer on top.
    [["nasaContext", 350], ["radarLeft", 401], ["radarMain", 402], ["radarBand", 403], ["venusPatches", 450], ["labels", 650]].forEach(function (p) {
      map.createPane(p[0]);
      map.getPane(p[0]).style.zIndex = String(p[1]);
    });
    map.getPane("labels").style.pointerEvents = "none";
    var small = window.matchMedia("(max-width: 1100px)").matches;
    map.fitBounds(aoi, small
      ? { paddingTopLeft: [10, 150], paddingBottomRight: [10, 215] }
      : { padding: [24, 24] });
    L.control.scale({ metric: true, imperial: false, position: "bottomleft" }).addTo(map);
    overlays = L.layerGroup().addTo(map);
    map.on("move zoom resize moveend", applyClip);
    map.on("mousemove", showCoords);
    map.on("moveend", function () { showCoords({ latlng: map.getCenter() }); });
    console.info("maxZoom from display pixel size:", maxZoom, "px", M.layers[0] && M.layers[0].px_size_m_3857);
    if (DEBUG) window.VENUS_MAP = map; // debug only
  }

  function showCoords(event) {
    var el = document.getElementById("cursor-readout");
    if (!el || !event || !event.latlng) return;
    var lat = event.latlng.lat;
    var lon = event.latlng.lng;
    el.textContent = Math.abs(lat).toFixed(4) + (lat >= 0 ? " N  " : " S  ") +
      Math.abs(lon).toFixed(4) + (lon >= 0 ? " E" : " W");
  }

  function makeBase(kind) {
    if (kind === "satellite") {
      return L.tileLayer(BASEMAP_URL, { attribution: UI.t("basemap_attribution"), maxZoom: 19 });
    }
    return L.tileLayer(DARK_URL, {
      attribution: UI.t("basemap_attribution_carto"),
      maxZoom: 19
    });
  }

  function makeLabels(kind) {
    if (kind === "satellite") {
      return L.tileLayer(ESRI_LABELS_URL, { pane: "labels", maxZoom: 19, opacity: 1 });
    }
    return L.tileLayer(DARK_LABELS_URL, { pane: "labels", maxZoom: 19, opacity: 1, attribution: UI.t("basemap_attribution_carto") });
  }

  var contextLayer = null;

  function renderContext() {
    var note = document.getElementById("context-note");
    if (!map) return;
    if (contextLayer && map.hasLayer(contextLayer)) map.removeLayer(contextLayer);
    contextLayer = null;
    if (!state.context) {
      if (note) note.hidden = true;
      return;
    }
    var day = M.dates[state.index];
    if (GIBS_TIMES.indexOf(day) >= 0) {
      contextLayer = L.tileLayer.wms(GIBS_URL, {
        layers: GIBS_LAYER, format: "image/png", transparent: true, version: "1.3.0",
        time: day, opacity: state.contextOpacity, pane: "nasaContext",
        attribution: UI.t("context_attribution"), maxZoom: 14
      }).addTo(map);
      if (note) note.hidden = true;
    } else if (note) {
      note.textContent = UI.t("context_unavailable", { from: GIBS_TIMES[0], to: GIBS_TIMES[GIBS_TIMES.length - 1] });
      note.hidden = false;
    }
  }

  function initBasemap() {
    baseLayers.dark = makeBase("dark");
    baseLayers.satellite = makeBase("satellite");
    labelLayers.dark = makeLabels("dark");
    labelLayers.satellite = makeLabels("satellite");

    var reported = false;
    Object.keys(baseLayers).forEach(function (kind) {
      baseLayers[kind].on("tileerror", function () {
        if (!reported) {
          reported = true;
          UI.showNotice(UI.t("basemap_unavailable"));
        }
      });
      baseLayers[kind].on("tileload", function () {
        if (reported) {
          reported = false;
          UI.hideNotice();
        }
      });
    });
    if (navigator.onLine === false) UI.showNotice(UI.t("basemap_unavailable"));
    applyBasemap();
  }

  function radarVisible() {
    return !!(slots.main.overlay || slots.main.preview);
  }

  function applyBasemap() {
    if (!map) return;
    Object.keys(baseLayers).forEach(function (kind) {
      if (kind === state.basemap && !map.hasLayer(baseLayers[kind])) baseLayers[kind].addTo(map);
      if (kind !== state.basemap && map.hasLayer(baseLayers[kind])) map.removeLayer(baseLayers[kind]);
    });
    Object.keys(labelLayers).forEach(function (kind) {
      var wanted = state.labels && kind === state.basemap;
      if (wanted && !map.hasLayer(labelLayers[kind])) labelLayers[kind].addTo(map);
      if (!wanted && map.hasLayer(labelLayers[kind])) map.removeLayer(labelLayers[kind]);
    });
    document.body.classList.toggle("basemap-satellite", state.basemap === "satellite");
    document.body.classList.toggle("radar-visible", radarVisible());
    document.body.classList.toggle("radar-dimmed", state.dim);
  }

  /* -------------------------------------------------------------- overlays */

  // A slot holds one overlay. The tiny preview appears first; the full image replaces it only after
  // it has loaded. One load may be in flight per slot, a 20 s timeout triggers one retry, and a
  // failure is always visible - a spinner must never outlive its request.
  function removeLayerQuietly(layer) {
    if (layer && overlays.hasLayer(layer)) overlays.removeLayer(layer);
  }

  function showLoadFailure(def) {
    UI.setLayerNote(UI.t("layer_failed", { name: def.label }));
    var note = document.getElementById("layer-note");
    if (!note) return;
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-quiet retry-btn";
    button.textContent = UI.t("retry_layer");
    button.addEventListener("click", function () { render(); });
    note.appendChild(button);
  }

  function setSlot(name, def, pane) {
    var slot = slots[name];
    var id = def ? def.id : null;
    slot.wanted = id;
    if (slot.timer) { clearTimeout(slot.timer); slot.timer = null; }
    removeLayerQuietly(slot.pending);
    removeLayerQuietly(slot.preview);
    slot.pending = null;
    slot.preview = null;
    if (!def) {
      removeLayerQuietly(slot.overlay);
      slot.overlay = null;
      applyBasemap();
      return;
    }
    if (slot.overlay && slot.overlay.options.venusId === id) { applyClip(); return; }

    if (def.preview) {
      slot.preview = L.imageOverlay(imageUrl(def, true), L.latLngBounds(def.bounds), {
        opacity: opacityFor(def), pane: pane, className: "radar-preview", interactive: false
      });
      overlays.addLayer(slot.preview);
    }
    loadAttempt(slot, def, pane, 0);
    applyBasemap();
  }

  function loadAttempt(slot, def, pane, attempt) {
    var id = def.id;
    var next = L.imageOverlay(imageUrl(def), L.latLngBounds(def.bounds), {
      opacity: 0, interactive: false, alt: def.label, pane: pane, className: "radar-layer"
    });
    next.options.venusId = id;
    slot.pending = next;
    var settled = false;

    function finish(ok) {
      if (settled) return;
      settled = true;
      if (slot.timer) { clearTimeout(slot.timer); slot.timer = null; }
      if (slot.pending === next) slot.pending = null;
      removeLayerQuietly(next);
      if (slot.wanted !== id) return;
      if (ok) {
        if (slot.overlay && slot.overlay !== next) removeLayerQuietly(slot.overlay);
        // Re-add the loaded image (finish() may run after a timeout removed it).
        if (!overlays.hasLayer(next)) overlays.addLayer(next);
        next.setOpacity(opacityFor(def));
        slot.overlay = next;
        removeLayerQuietly(slot.preview);
        slot.preview = null;
        applyClip();
        applyBasemap();
      } else if (attempt === 0) {
        loadAttempt(slot, def, pane, 1);
      } else {
        removeLayerQuietly(slot.preview);
        slot.preview = null;
        showLoadFailure(def);
      }
    }

    next.on("load", function () { finish(true); });
    next.on("error", function () { finish(false); });
    slot.timer = setTimeout(function () { finish(false); }, 20000);
    overlays.addLayer(next);
  }

  // Clip each side of the swipe to the divider, measured on the screen so pan and zoom stay aligned.
  function applyClip() {
    if (!map) return;
    var clear = !state.swipe;
    var mapRect = map.getContainer().getBoundingClientRect();
    var xAbs = mapRect.left + mapRect.width * state.split / 100;
    clipOne(slots.left, xAbs, "left", clear);
    clipOne(slots.main, xAbs, "right", clear);
  }

  function clipOne(slot, xAbs, side, clear) {
    if (!slot.overlay) return;
    var img = slot.overlay.getElement();
    if (!img) return;
    if (clear) { img.style.clipPath = ""; return; }
    var r = img.getBoundingClientRect();
    if (r.width < 1) return;
    var p = Math.min(100, Math.max(0, (xAbs - r.left) / r.width * 100));
    img.style.clipPath = side === "left" ? "inset(0 " + (100 - p) + "% 0 0)" : "inset(0 0 0 " + p + "%)";
  }

  // Idle preloading: current date first, then its neighbours, then the rest, at most two requests at
  // a time. Any place or layer change bumps the generation and the pending queue is dropped.
  function idle(fn) {
    if (window.requestIdleCallback) window.requestIdleCallback(fn, { timeout: 1200 });
    else setTimeout(fn, 80);
  }

  function pumpPreload() {
    var generation = preload.generation;
    while (preload.active < 2 && preload.queue.length) {
      var url = preload.queue.shift();
      preload.active += 1;
      (function (target) {
        var img = new Image();
        var done = function () {
          preload.active -= 1;
          if (generation === preload.generation) idle(pumpPreload);
        };
        img.onload = img.onerror = done;
        img.src = target;
      })(url);
    }
  }

  function queuePreload(urls) {
    preload.generation += 1;
    preload.queue = urls.slice();
    idle(pumpPreload);
  }

  function preloadSeries() {
    var defs = M.dates.map(function (_, index) { return { index: index, def: resolve(state.layer, state.pol, index).def }; })
      .filter(function (item) { return item.def; });
    defs.sort(function (a, b) {
      return Math.abs(a.index - state.index) - Math.abs(b.index - state.index);
    });
    queuePreload(defs.map(function (item) { return imageUrl(item.def); }));
  }

  function preloadNeighbours() {
    preloadSeries();
  }

  /* ------------------------------------------------------------ swipe */

  function setSplit(value) {
    state.split = Math.min(100, Math.max(0, Math.round(value)));
    var divider = document.getElementById("swipe-divider");
    divider.style.left = state.split + "%";
    divider.setAttribute("aria-valuenow", String(state.split));
    divider.setAttribute("aria-valuetext", state.split + "%");
    document.getElementById("swipe-range").value = String(state.split);
    applyClip();
  }

  function initSwipe() {
    var divider = document.getElementById("swipe-divider");
    var dragging = false;

    divider.addEventListener("pointerdown", function (event) {
      dragging = true;
      divider.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    divider.addEventListener("pointermove", function (event) {
      if (!dragging) return;
      var rect = map.getContainer().getBoundingClientRect();
      setSplit((event.clientX - rect.left) / rect.width * 100);
    });
    divider.addEventListener("pointerup", function () { dragging = false; });
    divider.addEventListener("pointercancel", function () { dragging = false; });

    // Keyboard: arrows move 2 percent (10 with Shift); Home and End go to the edges.
    divider.addEventListener("keydown", function (event) {
      var step = event.shiftKey ? 10 : 2;
      if (event.key === "ArrowLeft") setSplit(state.split - step);
      else if (event.key === "ArrowRight") setSplit(state.split + step);
      else if (event.key === "Home") setSplit(0);
      else if (event.key === "End") setSplit(100);
      else return;
      event.preventDefault();
    });
  }

  /* -------------------------------------------------------- place card */

  function renderPlaceCard() {
    var place = placeInfo();
    var aoi = aoiBounds();
    var centre = aoi.getCenter();
    var name = document.getElementById("place-name");
    var country = document.getElementById("place-country");
    var story = document.getElementById("place-story");
    var meta = document.getElementById("place-meta");
    if (name) name.textContent = (M.place && M.place.title) || place.title || state.place;
    if (country) country.textContent = UI.t("place_country");
    if (story) story.textContent = (M.study_area && M.study_area.story) || place.story || "";
    if (meta) {
      meta.textContent = centre.lat.toFixed(3) + " N  " + centre.lng.toFixed(3) + " E  |  " +
        UI.fmtDate(M.dates[0]) + " to " + UI.fmtDate(M.dates[M.dates.length - 1]) + "  |  " +
        M.polarizations.join(" + ");
    }
  }

  function initAoiFrame() {
    aoiLayer = L.rectangle(aoiBounds(), {
      color: "#E2B862", weight: 1.25, dashArray: "5 5", fill: false, interactive: false
    });
    aoiLayer.bindTooltip(UI.t("aoi_label"), { sticky: true, direction: "center" });
    if (state.aoiFrame) aoiLayer.addTo(map);
  }

  function setAoiFrame(show) {
    state.aoiFrame = show;
    if (!aoiLayer) return;
    if (show && !map.hasLayer(aoiLayer)) aoiLayer.addTo(map);
    if (!show && map.hasLayer(aoiLayer)) map.removeLayer(aoiLayer);
  }

  function initLocator() {
    var element = document.getElementById("locator-map");
    if (!element || typeof L === "undefined") return;
    locator = L.map(element, {
      zoomControl: false, attributionControl: false, dragging: false, scrollWheelZoom: false,
      doubleClickZoom: false, boxZoom: false, keyboard: false, touchZoom: false
    }).setView([31.35, 36.2], 6);
    L.tileLayer(DARK_URL, { maxZoom: 19 }).addTo(locator);
    var places = (V.places && V.places.places) || [];
    places.filter(function (place) { return place.processed; }).forEach(function (place) {
      var bounds = L.latLngBounds(place.bounds);
      var c = bounds.getCenter();
      var active = state.place === place.name;
      var marker = L.marker(c, {
        keyboard: true,
        title: place.title,
        alt: place.title,
        icon: L.divIcon({
          className: "locator-dot" + (active ? " is-active" : ""),
          html: "<span></span>",
          iconSize: [14, 14],
          iconAnchor: [7, 7]
        })
      }).addTo(locator);
      marker.on("click", function () { selectPlace(place.name); });
    });
    setTimeout(function () { locator.invalidateSize(); }, 250);
  }

  /* -------------------------------------------------------- map controls */

  function initMapControls() {
    var select = document.getElementById("basemap-select");
    if (select) {
      select.value = state.basemap;
      select.addEventListener("change", function () {
        state.basemap = select.value;
        applyBasemap();
      });
    }
    var labels = document.getElementById("labels-toggle");
    if (labels) labels.addEventListener("change", function () {
      state.labels = labels.checked;
      applyBasemap();
    });
    var frame = document.getElementById("aoi-toggle");
    if (frame) frame.addEventListener("change", function () { setAoiFrame(frame.checked); });
    var dim = document.getElementById("dim-toggle");
    if (dim) dim.addEventListener("change", function () {
      state.dim = dim.checked;
      applyBasemap();
    });
    var collapse = document.getElementById("panel-toggle");
    if (collapse) collapse.addEventListener("click", function () {
      var controls = document.querySelector(".controls");
      var collapsed = controls.classList.toggle("is-collapsed");
      collapse.setAttribute("aria-expanded", String(!collapsed));
    });
    var openControls = document.getElementById("open-controls");
    if (openControls) openControls.addEventListener("click", function () {
      document.querySelector(".controls").classList.remove("is-collapsed");
    });
    var openPanel = document.getElementById("open-panel");
    if (openPanel) openPanel.addEventListener("click", function () {
      document.querySelector(".panel").classList.toggle("is-collapsed");
    });
    var contextToggle = document.getElementById("context-toggle");
    if (contextToggle) contextToggle.addEventListener("change", function () {
      state.context = contextToggle.checked;
      renderContext();
    });
    var contextOpacity = document.getElementById("context-opacity");
    if (contextOpacity) contextOpacity.addEventListener("input", function () {
      state.contextOpacity = Number(contextOpacity.value) / 100;
      if (contextLayer) contextLayer.setOpacity(state.contextOpacity);
    });
    var motionToggle = document.getElementById("motion-toggle");
    if (motionToggle) {
      motionToggle.checked = state.reduceMotion;
      motionToggle.addEventListener("change", function () {
        state.reduceMotion = motionToggle.checked;
        document.body.classList.toggle("reduce-motion", state.reduceMotion);
        try { localStorage.setItem("venus-reduce-motion", state.reduceMotion ? "1" : "0"); } catch (e) {}
      });
      document.body.classList.toggle("reduce-motion", state.reduceMotion);
    }
    document.querySelectorAll("[data-theme-set]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-theme-set") === state.theme));
      button.addEventListener("click", function () { applyTheme(button.getAttribute("data-theme-set")); });
    });
    if (window.matchMedia("(max-width: 1100px)").matches) {
      document.querySelector(".controls").classList.add("is-collapsed");
      document.querySelector(".panel").classList.add("is-collapsed");
    }
  }

  /* ----------------------------------------------------------- patches */

  /* ----------------------------------------------------------- patches */

  function patchFeatures() {
    return (V.patches && V.patches.geojson && V.patches.geojson.features) || [];
  }

  function initPatches() {
    var features = patchFeatures();
    patchLayer = L.layerGroup();
    if (!features.length) return;
    var poly = L.geoJSON({ type: "FeatureCollection", features: features }, {
      pane: "venusPatches",
      style: { color: "#E2B862", weight: 2, fillOpacity: 0.12, dashArray: "4 3" },
      interactive: false
    });
    patchLayer.addLayer(poly);
    features.forEach(function (feature) {
      var p = feature.properties;
      var icon = L.divIcon({
        className: "patch-icon",
        html: "<span>" + p.id.replace(/[^A-Za-z0-9]/g, "") + "</span>",
        iconSize: [34, 22],
        iconAnchor: [17, 11]
      });
      var marker = L.marker([p.lat, p.lon], { icon: icon, keyboard: true, title: p.id, alt: p.id, pane: "venusPatches" });
      marker.on("click", function () { selectPatch(feature); });
      patchLayer.addLayer(marker);
    });
  }

  function selectPatch(feature) {
    selectedPatch = feature ? feature.properties.id : null;
    UI.renderPatch(feature, M);
  }

  function setPatchesVisible(show) {
    if (!patchLayer) return;
    if (show && !patchFeatures().length) {
      UI.setLayerNote(UI.t("patches_none"));
      return;
    }
    if (show) {
      if (!map.hasLayer(patchLayer)) patchLayer.addTo(map);
    } else if (map.hasLayer(patchLayer)) {
      map.removeLayer(patchLayer);
    }
  }

  /* ------------------------------------------------------------ story mode */

  // Six steps. Each one only sets state that the controls also set, then calls render(), so the
  // story and the controls can never drift apart. No numbers are introduced here.
  var STORY = [
    {
      key: "1", state: { layer: "backscatter", pol: "HV", swipe: false, band: false, patches: false },
      index: 0, view: "fit"
    },
    {
      key: "2", state: { layer: "backscatter", pol: "HV", swipe: false, band: false, patches: false },
      index: 0, view: { center: [31.55, 35.47], zoom: 11 }
    },
    {
      key: "3", state: { layer: "water", pol: "HV", swipe: false, band: false, patches: false },
      index: "last", view: { center: [31.55, 35.47], zoom: 11 }
    },
    {
      key: "4", state: { layer: "water", pol: "HV", swipe: true, band: true, patches: false },
      index: "last", leftIndex: 0, leftLayer: "water", split: 50, view: "fit"
    },
    {
      key: "5", state: { layer: "backscatter", pol: "HV", swipe: false, band: false, patches: true },
      index: "last", view: "patch"
    },
    {
      key: "6", state: { layer: "backscatter", pol: "HV", swipe: false, band: false, patches: false },
      index: "last", view: "fit"
    }
  ];
  var storyIndex = -1;

  function startStory() {
    // The story explains the analysed series; switch to it first so no step is empty.
    var analysed = seriesList().filter(function (series) { return series.analysis; })[0];
    if (analysed && analysed.id !== state.seriesId) selectSeries(analysed.id);
    document.getElementById("story-idle").hidden = true;
    document.getElementById("story-intro").hidden = true;
    document.getElementById("story-run").hidden = false;
    goToStoryStep(0);
  }

  function exitStory() {
    storyIndex = -1;
    document.getElementById("story-idle").hidden = false;
    document.getElementById("story-intro").hidden = false;
    document.getElementById("story-run").hidden = true;
  }

  function goToStoryStep(n) {
    var step = STORY[Math.max(0, Math.min(STORY.length - 1, n))];
    storyIndex = STORY.indexOf(step);
    stopPlaying();

    state.layer = step.state.layer;
    state.pol = step.state.pol;
    state.swipe = step.state.swipe;
    state.band = step.state.band;
    state.patches = step.state.patches;
    state.index = step.index === "last" ? M.dates.length - 1 : step.index;
    if (step.leftIndex !== undefined) state.leftIndex = step.leftIndex;
    if (step.leftLayer) state.leftLayer = step.leftLayer;
    if (step.split !== undefined) state.split = step.split;

    // Band only makes sense with the water mask; step 4 shows it over the change layer's water panes.
    applyStateToControls();
    render();
    setStoryView(step.view);

    document.getElementById("story-progress").textContent = UI.t("story_progress", { n: storyIndex + 1, total: STORY.length });
    document.getElementById("story-step-title").textContent = UI.t("story_" + step.key + "_title");
    document.getElementById("story-step-body").textContent = UI.t("story_" + step.key + "_body");
    var dots = document.getElementById("story-dots");
    dots.innerHTML = "";
    STORY.forEach(function (_, i) {
      var li = document.createElement("li");
      if (i === storyIndex) li.className = "active";
      dots.appendChild(li);
    });
    document.getElementById("story-prev").disabled = storyIndex === 0;
    document.getElementById("story-next").disabled = storyIndex === STORY.length - 1;
  }

  function setStoryView(view) {
    if (view === "fit") map.fitBounds(bounds, { padding: [12, 12] });
    else if (view === "patch") {
      var features = patchFeatures();
      if (features.length) {
        var f = features[0];
        map.setView([f.properties.lat, f.properties.lon], 14, { animate: false });
        selectPatch(f);
      } else map.fitBounds(bounds, { padding: [12, 12] });
    } else if (view && view.center) map.setView(view.center, view.zoom, { animate: false });
  }

  function initStory() {
    document.getElementById("story-start").addEventListener("click", startStory);
    document.getElementById("story-prev").addEventListener("click", function () { goToStoryStep(storyIndex - 1); });
    document.getElementById("story-next").addEventListener("click", function () { goToStoryStep(storyIndex + 1); });
    document.getElementById("story-exit").addEventListener("click", exitStory);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && storyIndex >= 0) exitStory();
      // Shift+arrows step between calibration series, never mixing their statistics.
      if (event.shiftKey && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
        var tag = (event.target && event.target.tagName) || "";
        if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
        var list = seriesList();
        if (list.length < 2) return;
        var at = list.map(function (item) { return item.id; }).indexOf(state.seriesId);
        var next = (at + (event.key === "ArrowRight" ? 1 : -1) + list.length) % list.length;
        selectSeries(list[next].id);
        event.preventDefault();
      }
    });
  }

  /* -------------------------------------------------------------- places */

  var outlineLayer = null;

  function placeByName(name) {
    var list = (V.places && V.places.places) || [];
    return list.filter(function (p) { return p.name === name; })[0] || null;
  }

  // Draw the selected place's outline. Switching to a processed place reloads with its own bundle,
  // which keeps one place's data from ever being drawn on another place's coordinates.
  function selectPlace(name) {
    var place = placeByName(name);
    if (!place) return;
    if (place.processed && place.name !== (M && M.study_area && M.study_area.name)) {
      window.location.search = "?place=" + encodeURIComponent(place.name);
      return;
    }
    if (outlineLayer) { map.removeLayer(outlineLayer); outlineLayer = null; }

    var rect = L.latLngBounds(place.bounds);
    outlineLayer = L.rectangle(rect, {
      color: "#E2B862", weight: 2, fillOpacity: 0.06, interactive: false
    }).addTo(map);
    map.fitBounds(rect, { padding: [16, 16] });
    UI.setPlaceStatus(place);
    state.place = place.name;

    if (place.processed) {
      map.setMaxBounds(rect.pad(0.5));
      render();
    } else {
      // No imagery for this place: clear every radar layer rather than show another place's data.
      stopPlaying();
      ["main", "left", "band"].forEach(function (slot) { setSlot(slot, null, null); });
      if (patchLayer && map.hasLayer(patchLayer)) map.removeLayer(patchLayer);
      UI.setLayerNote(null);
      document.getElementById("swipe-divider").hidden = true;
      document.getElementById("swipe-tag-left").hidden = true;
      document.getElementById("swipe-tag-right").hidden = true;
    }
  }

  /* ----------------------------------------------------------- render */

  function render() {
    var r = resolve(state.layer, state.pol, state.index);
    var leftR = state.swipe ? resolve(state.leftLayer, state.pol, state.leftIndex) : null;
    var band = state.band && state.layer === "water" && r.def ? bandLayerFor(state.index) : null;

    setSlot("main", r.def, "radarMain");
    setSlot("left", leftR ? leftR.def : null, "radarLeft");
    setSlot("band", band, "radarBand");

    var note = r.note || (leftR && leftR.note) || null;
    UI.setLayerNote(note);
    UI.setPolHint(state.pol);
    UI.setBandAvailable(state.layer === "water");
    UI.setDateIndex(state.index);
    UI.setLeftIndex(state.leftIndex);

    // Swipe controls and labels
    var divider = document.getElementById("swipe-divider");
    divider.hidden = !state.swipe;
    var tagL = document.getElementById("swipe-tag-left");
    var tagR = document.getElementById("swipe-tag-right");
    tagL.hidden = tagR.hidden = !state.swipe;
    if (state.swipe && leftR && leftR.def) {
      tagL.textContent = UI.t("swipe_left_tag") + ": " + UI.fmtDate(leftR.def.date) + " (" + leftR.def.label + ")";
    }
    if (state.swipe && r.def) {
      tagR.textContent = UI.t("swipe_right_tag") + ": " + UI.fmtDate(r.def.date) + " (" + r.def.label + ")";
    }
    UI.setSwipeOpen(state.swipe);
    setSplit(state.split);

    // Legend and details. A band caption uses only numbers from the water statistics.
    var extra = {
      patches: state.patches,
      patchThreshold: V.patches ? V.patches.threshold_db : undefined,
      bandDb: bandDb(),
      leftLabel: state.swipe && leftR && leftR.def ? leftR.def.label + " " + UI.fmtDate(leftR.def.date) : null,
      rightLabel: r.def ? r.def.label + " " + UI.fmtDate(r.def.date) : ""
    };
    if (band) extra.bandText = bandCaption(band.date);
    var changeScale = (M.scales && M.scales.change_db_symmetric) ? M.scales.change_db_symmetric[state.pol] : 1;
    UI.renderLegend(r.def, changeScale, extra);
    UI.renderInfo(r.def, M, leftR ? leftR.def : null);
    setPatchesVisible(state.patches);
    updateBadge();
    renderTimeline();
    renderContext();
    updateSeriesNote();

    writeHash();
    preloadNeighbours();
    applyClip();
  }

  function renderCharts() {
    var stats = V.place_water_stats;
    if (!stats) return;
    var chartManifest = Object.assign({}, M);
    chartManifest.dates = (stats.dates || []).map(function (entry) { return entry.date; });
    UI.renderAreaChart(stats, chartManifest, bandDb());
    UI.renderOffsetChart(V.place_offsets, chartManifest);
  }

  // Caption for the detection-limit band on one date, built from water_stats numbers only.
  function bandCaption(date) {
    var stats = V.place_water_stats;
    var entry = stats && stats.dates ? stats.dates.filter(function (d) { return d.date === date; })[0] : null;
    var b = entry && entry.methods ? entry.methods.B : null;
    if (!b) return UI.t("error_missing_data", { name: "water_stats.js" });
    return UI.t("band_caption", {
      band: UI.fmt(bandDb(), 1), date: UI.fmtDate(date),
      low: UI.fmt(b.low_km2, 1), high: UI.fmt(b.high_km2, 1), area: UI.fmt(b.area_km2, 1)
    });
  }

  /* ------------------------------------------------------------ indexing */

  function setIndex(i) {
    var prev = M.dates[state.index];
    var next = M.dates[i];
    var gap = UI.outageIndices(M.dates);
    var crossing = gap && ((prev < gap.start && next > gap.end) || (prev > gap.end && next < gap.start));
    state.index = i;
    render();
    if (crossing) UI.flashOutage(true);
  }

  /* ----------------------------------------------------------- playing */

  // Preload every frame of the current layer before playing, so playback never stalls on the network.
  function startPlaying() {
    var urls = [];
    M.dates.forEach(function (_, i) {
      var def = resolve(state.layer, state.pol, i).def;
      if (def) urls.push(imageUrl(def));
    });
    UI.setLayerNote(UI.t("preloading"));
    var remaining = urls.length;
    if (!remaining) { UI.setLayerNote(""); beginTimer(); return; }
    var active = 0;
    var next = function () {
      while (active < 2 && urls.length) {
        active += 1;
        (function (url) {
          var img = new Image();
          var done = function () {
            active -= 1;
            remaining -= 1;
            if (remaining === 0) { UI.setLayerNote(""); beginTimer(); }
            else next();
          };
          img.onload = img.onerror = done;
          img.src = url;
        })(urls.shift());
      }
    };
    next();
  }

  function beginTimer() {
    if (!state.playing) return;
    var interval = Math.round(PLAY_TOTAL_MS / M.dates.length);
    playTimer = setInterval(function () {
      var next = state.index + 1;
      if (next >= M.dates.length) {
        if (!state.loop) { stopPlaying(); return; }
        next = 0;
      }
      setIndex(next);
    }, interval);
  }

  function togglePlay() {
    if (state.playing) return stopPlaying();
    state.playing = true;
    UI.setPlaying(true);
    startPlaying();
  }

  function stopPlaying() {
    if (playTimer) clearInterval(playTimer);
    playTimer = null;
    state.playing = false;
    UI.setPlaying(false);
  }

  /* ----------------------------------------------------------- URL state */

  // Plain names only (date, layer, pol, swipe, left, split, band, patches). Nothing sensitive.
  function writeHash() {
    var params = new URLSearchParams();
    params.set("date", M.dates[state.index]);
    params.set("layer", state.layer);
    params.set("pol", state.pol);
    if (seriesList().length > 1) params.set("series", state.seriesId);
    if (state.swipe) {
      params.set("swipe", M.dates[state.leftIndex]);
      params.set("left", state.leftLayer);
      params.set("split", String(state.split));
    }
    if (state.band) params.set("band", "1");
    if (state.patches) params.set("patches", "1");
    try {
      history.replaceState(null, "", "#" + params.toString());
    } catch (error) {
      // file:// in some browsers refuses history changes; the page still works without bookmarks.
    }
  }

  function readHash() {
    var params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    var series = params.get("series");
    if (series && seriesList().some(function (item) { return item.id === series; })) {
      state.seriesId = series;
      applySeriesDates();
    }
    var date = params.get("date");
    if (date && M.dates.indexOf(date) >= 0) state.index = M.dates.indexOf(date);
    var layer = params.get("layer");
    if (["rgb", "backscatter", "change", "water"].indexOf(layer) >= 0) state.layer = layer;
    var pol = params.get("pol");
    if (pol === "HV" || pol === "HH") state.pol = pol;
    var swipe = params.get("swipe");
    if (swipe && M.dates.indexOf(swipe) >= 0) {
      state.swipe = true;
      state.leftIndex = M.dates.indexOf(swipe);
    }
    var left = params.get("left");
    if (["rgb", "backscatter", "change", "water"].indexOf(left) >= 0) state.leftLayer = left;
    var split = Number(params.get("split"));
    if (isFinite(split) && params.get("split") !== null) state.split = Math.min(100, Math.max(0, split));
    state.band = params.get("band") === "1";
    state.patches = params.get("patches") === "1";
  }

  /* ------------------------------------------------------------ events */

  function onChange() {
    state.layer = UI.selectedLayer();
    state.pol = UI.selectedPol();
    state.index = UI.selectedDateIndex();
    state.swipe = UI.isChecked("swipe-toggle");
    state.leftIndex = UI.selectedLeftIndex();
    state.leftLayer = UI.selectedLeftLayer();
    state.band = UI.isChecked("band-toggle");
    state.patches = UI.isChecked("patches-toggle");
    render();
  }

  /* ------------------------------------------------------------- debug */

  function initDebug() {
    document.getElementById("debug-panel").hidden = false;
    var slider = document.getElementById("debug-opacity");
    var output = document.getElementById("debug-opacity-out");
    slider.addEventListener("input", function () {
      debugOpacity = Number(slider.value) / 100;
      output.textContent = Math.round(debugOpacity * 100) + "%";
      [slots.main, slots.left, slots.band].forEach(function (s) { if (s.overlay) s.overlay.setOpacity(debugOpacity); });
    });
    var outline = null;
    document.getElementById("debug-bounds").addEventListener("change", function (event) {
      if (event.target.checked) {
        outline = L.rectangle(bounds, { color: "#E2B862", weight: 2, dashArray: "6 4", fill: false, interactive: false }).addTo(map);
        console.info("manifest bounds [[south, west], [north, east]]", M.bounds);
      } else if (outline) {
        map.removeLayer(outline);
        outline = null;
      }
    });
    document.getElementById("debug-crosshair").addEventListener("change", function (event) {
      document.getElementById("map").classList.toggle("debug-crosshair", event.target.checked);
    });
  }

  /* -------------------------------------------------------------- boot */

  function applyStateToControls() {
    UI.setLayer(state.layer);
    UI.setPol(state.pol);
    UI.setDateIndex(state.index);
    UI.setLeftIndex(state.leftIndex);
    document.getElementById("left-layer").value = state.leftLayer;
    document.getElementById("swipe-range").value = String(state.split);
    document.getElementById("band-toggle").checked = state.band;
    document.getElementById("patches-toggle").checked = state.patches;
    UI.setSwipeOpen(state.swipe);
  }

  // Load one place's bundle with plain script tags (file:// safe) and continue once it has arrived.
  function loadPlace(name, done) {
    var files = ["manifest", "water_stats", "offsets"];
    var remaining = files.length;
    files.forEach(function (file) {
      var tag = document.createElement("script");
      tag.src = "data/" + name + "/" + file + ".js";
      tag.onload = tag.onerror = function () {
        remaining -= 1;
        if (remaining === 0) done();
      };
      document.head.appendChild(tag);
    });
  }

  function applyTheme(name) {
    state.theme = name === "aurora" ? "aurora" : "void";
    document.body.setAttribute("data-theme", state.theme);
    try { localStorage.setItem("venus-theme", state.theme); } catch (e) {}
    document.querySelectorAll("[data-theme-set]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-theme-set") === state.theme));
    });
  }

  function showIntro() {
    var intro = document.getElementById("intro");
    if (!intro) return;
    var seen = false;
    try { seen = sessionStorage.getItem("venus-intro") === "1"; } catch (e) {}
    if (seen || state.reduceMotion) { intro.parentNode.removeChild(intro); return; }
    try { sessionStorage.setItem("venus-intro", "1"); } catch (e) {}
    setTimeout(function () {
      intro.classList.add("is-done");
      setTimeout(function () { if (intro.parentNode) intro.parentNode.removeChild(intro); }, 700);
    }, 1200);
  }

  function boot() {
    UI.applyStrings();
    if (typeof L === "undefined") {
      UI.showNotice(UI.t("error_no_data"));
      return;
    }
    var wanted = PLACE || (V.places && V.places.active) || "dead_sea_east";
    loadPlace(wanted, function () {
      M = V.place_manifest;
      if (!M) {
        UI.showNotice(UI.t("error_no_data"));
        return;
      }
      // Some places have only HH. Never leave the polarization pointing at a channel that is absent.
      if (M.polarizations && M.polarizations.indexOf("HV") < 0) state.pol = M.polarizations[0];
      else if (M.polarizations) state.pol = "HV";
      start();
    });
  }

  function start() {
    // A visible indicator until the first overlay has loaded. It is also cleared on failure and by a
    // timeout, because a spinner that never clears is worse than no spinner at all.
    var mapEl = document.getElementById("map");
    mapEl.classList.add("is-loading");
    var loadingText = document.createElement("p");
    loadingText.className = "loading-text";
    loadingText.textContent = UI.t("loading_first");
    mapEl.appendChild(loadingText);
    var cleared = false;
    function clearLoading() {
      if (cleared) return;
      cleared = true;
      clearInterval(firstLoad);
      clearTimeout(giveUp);
      mapEl.classList.remove("is-loading");
      if (loadingText.parentNode) loadingText.parentNode.removeChild(loadingText);
    }
    var firstLoad = setInterval(function () {
      if (slots.main.overlay) clearLoading();
    }, 120);
    var giveUp = setTimeout(clearLoading, 15000);
    state.theme = (function () { try { return localStorage.getItem("venus-theme") || "void"; } catch (e) { return "void"; } })();
    state.reduceMotion = (function () { try { return localStorage.getItem("venus-reduce-motion") === "1"; } catch (e) { return false; } })();
    applyTheme(state.theme);
    document.body.classList.toggle("reduce-motion", state.reduceMotion);
    if (M.series && M.series.length) state.seriesId = M.primary_series || M.series[0].id;
    applySeriesDates();
    state.index = M.dates.length - 1;
    state.layer = "rgb";
    readHash();
    applySeriesDates();
    state.index = Math.min(state.index, M.dates.length - 1);
    UI.initDates(M.dates, state.index, M.reference_date, UI.outageIndices(M.dates));
    applyStateToControls();
    UI.renderFooter(V.license);
    renderCharts();
    renderSeriesChips();
    renderTimeline();
    updateBadge();
    showIntro();
    UI.renderPatch(null, M);
    UI.renderFeatured(patchFeatures(), selectPatch);
    UI.initPlaces(V.places, selectPlace);
    var startPlace = placeByName(M.study_area.name);
    if (startPlace) { state.place = startPlace.name; UI.setPlaceStatus(startPlace); UI.setPlaceSelection(startPlace.name); }

    // Move the date controls and the legend into their floating homes before the map is drawn.
    var timebar = document.getElementById("timebar");
    var dateField = document.getElementById("date-field");
    if (timebar && dateField) timebar.appendChild(dateField);
    var legendHome = document.getElementById("legend-inset");
    var legendCard = document.getElementById("legend-card");
    if (legendHome && legendCard) legendHome.appendChild(legendCard);
    var contextNote = document.getElementById("context-note");
    if (legendHome && contextNote) legendHome.appendChild(contextNote);

    initMap();
    initBasemap();
    renderPlaceCard();
    initAoiFrame();
    initLocator();
    initMapControls();
    var pixelNote = document.getElementById("legend-pixel-note");
    if (pixelNote) pixelNote.textContent = UI.t("pixel_note");
    initPatches();
    initSwipe();
    initStory();
    if (DEBUG) initDebug();

    UI.bind({
      onChange: onChange,
      onTime: function (v) { setIndex(v); },
      onPlay: togglePlay,
      onSplit: function (v) { setSplit(v); },
      onPatchClose: function () { selectPatch(null); }
    });
    document.getElementById("loop-toggle").addEventListener("change", function (event) {
      state.loop = event.target.checked;
    });
    render();
    preloadSeries();
  }

  try {
    boot();
  } catch (error) {
    // Never fail silently: say what went wrong, in plain words.
    UI.showNotice(UI.t("error_start", { message: error.message }));
    throw error;
  }
})();
