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
  var OPACITY = { rgb: 1, backscatter: 0.92, change: 0.9, water: 1, band: 1 };
  var PLAY_TOTAL_MS = 12000;           // the whole series plays in about 12 seconds

  var state = {
    index: 0, layer: "backscatter", pol: "HV",
    place: "dead_sea_east", swipe: false, leftIndex: 0, leftLayer: "backscatter", split: 50,
    band: false, patches: false,
    playing: false, loop: false
  };
  var map = null, bounds = null, overlays = null, patchLayer = null, selectedPatch = null;
  var slots = { main: { overlay: null, wanted: null }, left: { overlay: null, wanted: null }, band: { overlay: null, wanted: null } };
  var playTimer = null;
  var debugOpacity = null;

  /* ---------------------------------------------------------------- lookup */

  function find(kind, pol, date) {
    for (var i = 0; i < M.layers.length; i++) {
      var layer = M.layers[i];
      if (layer.kind !== kind || layer.date !== date) continue;
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
  function imageUrl(def) {
    var placeName = (M && M.place && M.place.name) || "dead_sea_east";
    return "data/" + placeName + "/" + def.file;
  }

  function opacityFor(def) {
    return debugOpacity !== null ? debugOpacity : OPACITY[def.kind];
  }

  /* ------------------------------------------------------------------ map */

  function initMap() {
    bounds = L.latLngBounds(M.bounds); // [[south, west], [north, east]] from the manifest
    map = L.map("map", {
      minZoom: 10,
      maxZoom: 16,
      zoomSnap: 0.25,
      maxBounds: bounds.pad(0.5),
      maxBoundsViscosity: 0.8
    });
    // Panes make the stacking explicit: left, after and band images, then patches on top.
    [["radarLeft", 401], ["radarMain", 402], ["radarBand", 403], ["venusPatches", 450]].forEach(function (p) {
      map.createPane(p[0]);
      map.getPane(p[0]).style.zIndex = String(p[1]);
    });
    map.fitBounds(bounds, { padding: [12, 12] });
    L.control.scale({ metric: true, imperial: false }).addTo(map);
    overlays = L.layerGroup().addTo(map);
    map.on("move zoom resize moveend", applyClip);
    if (DEBUG) window.VENUS_MAP = map; // debug only
  }

  function initBasemap() {
    var reported = false;
    var basemap = L.tileLayer(BASEMAP_URL, { attribution: UI.t("basemap_attribution"), maxZoom: 17 });
    basemap.on("tileerror", function () {
      if (!reported) {
        reported = true;
        UI.showNotice(UI.t("basemap_unavailable"));
      }
    });
    basemap.on("tileload", function () {
      if (reported) {
        reported = false;
        UI.hideNotice();
      }
    });
    if (navigator.onLine === false) UI.showNotice(UI.t("basemap_unavailable"));
    basemap.addTo(map);
  }

  /* -------------------------------------------------------------- overlays */

  // A slot holds one overlay. A new image replaces the old one only after it has loaded, and only
  // one load may be in flight per slot, so rapid changes (story steps, fast stepping) cannot pile up.
  function setSlot(name, def, pane) {
    var slot = slots[name];
    var id = def ? def.id : null;
    slot.wanted = id;
    if (slot.pending) {
      overlays.removeLayer(slot.pending);
      slot.pending = null;
    }
    if (!def) {
      if (slot.overlay) { overlays.removeLayer(slot.overlay); slot.overlay = null; }
      return;
    }
    if (slot.overlay && slot.overlay.options.venusId === id) { applyClip(); return; }

    var next = L.imageOverlay(imageUrl(def), L.latLngBounds(def.bounds), {
      opacity: 0, interactive: false, alt: def.label, pane: pane, className: "radar-layer"
    });
    next.options.venusId = id;
    slot.pending = next;
    next.on("load", function () {
      if (slot.pending === next) slot.pending = null;
      if (slot.wanted !== id) { overlays.removeLayer(next); return; }
      next.setOpacity(opacityFor(def));
      if (slot.overlay && slot.overlay !== next) overlays.removeLayer(slot.overlay);
      slot.overlay = next;
      applyClip();
    });
    next.on("error", function () {
      if (slot.pending === next) slot.pending = null;
      overlays.removeLayer(next);
      UI.setLayerNote(UI.t("error_layer", { name: def.label }));
      document.getElementById("map").classList.remove("is-loading");
      var stale = document.querySelector("#map .loading-text");
      if (stale) stale.parentNode.removeChild(stale);
    });
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

  // Fetch every date of the current layer and polarization into the browser cache, so stepping through
  // the series has little or no delay. Images are small (tens of KB each); this is a few MB at most.
  var preloaded = {};
  function preloadSeries() {
    M.dates.forEach(function (date, index) {
      var def = resolve(state.layer, state.pol, index).def;
      if (!def || preloaded[def.id]) return;
      preloaded[def.id] = true;
      new Image().src = imageUrl(def);
    });
  }

  // Ask the browser to fetch the neighbouring frames so stepping is smooth.
  function preloadNeighbours() {
    [-1, 1].forEach(function (step) {
      var index = state.index + step;
      if (index < 0 || index >= M.dates.length) return;
      var def = resolve(state.layer, state.pol, index).def;
      if (def) new Image().src = imageUrl(def);
    });
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
      index: 0, view: { center: [31.45, 35.56], zoom: 12 }
    },
    {
      key: "3", state: { layer: "water", pol: "HV", swipe: false, band: false, patches: false },
      index: "last", view: { center: [31.45, 35.55], zoom: 12 }
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
    UI.renderLegend(r.def, M.scales.change_db_symmetric[state.pol], extra);
    UI.renderInfo(r.def, M, leftR ? leftR.def : null);
    setPatchesVisible(state.patches);

    writeHash();
    preloadNeighbours();
    applyClip();
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
    var remaining = urls.length;
    UI.setLayerNote(UI.t("preloading"));
    if (!remaining) { UI.setLayerNote(""); beginTimer(); return; }
    urls.forEach(function (url) {
      var img = new Image();
      img.onload = img.onerror = function () {
        remaining -= 1;
        if (remaining === 0) { UI.setLayerNote(""); beginTimer(); }
      };
      img.src = url;
    });
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
    state.index = M.dates.length - 1;
    state.layer = "rgb";
    readHash();
    UI.initDates(M.dates, state.index, M.reference_date, UI.outageIndices(M.dates));
    applyStateToControls();
    UI.renderFooter(V.license);
    UI.renderAreaChart(V.place_water_stats, M, bandDb());
    UI.renderOffsetChart(V.place_offsets, M);
    UI.renderPatch(null, M);
    UI.renderFeatured(patchFeatures(), selectPatch);
    UI.initPlaces(V.places, selectPlace);
    var startPlace = placeByName(M.study_area.name);
    if (startPlace) { state.place = startPlace.name; UI.setPlaceStatus(startPlace); UI.setPlaceSelection(startPlace.name); }

    initMap();
    initBasemap();
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
