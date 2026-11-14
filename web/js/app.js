/*
 * app.js - the map and the radar layers. Reads window.VENUS (data) and window.VENUS_UI (panels).
 *
 * Overlay rules:
 *   - every image is an L.imageOverlay placed at the bounds stored in the manifest (never recomputed);
 *   - a new image fades in only after it has loaded, so the map never flashes empty;
 *   - a load that is no longer wanted (the user moved on) is discarded;
 *   - only the visible image and its two neighbours are requested; the rest are never downloaded.
 */
(function () {
  "use strict";

  var V = window.VENUS || {};
  var M = V.manifest;
  var UI = window.VENUS_UI;
  var DEBUG = new URLSearchParams(window.location.search).get("debug") === "1";

  // Esri World Imagery (see docs/DATA_SOURCES.md for the terms check). Displayed only, never exported.
  var BASEMAP_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  var OPACITY = { backscatter: 0.92, change: 0.9, water: 1, band: 1 };

  var state = { index: 0, layer: "backscatter", pol: "HV" };
  var wanted = null;      // id of the overlay the user currently wants on screen
  var current = null;     // the overlay currently visible
  var debugOpacity = null;
  var map = null;
  var overlays = null;
  var bounds = null;

  /* ------------------------------------------------------------ lookup */

  function find(kind, pol, date) {
    for (var i = 0; i < M.layers.length; i++) {
      var layer = M.layers[i];
      if (layer.kind !== kind || layer.date !== date) continue;
      if (kind === "water" || layer.polarization === pol) return layer;
    }
    return null;
  }

  // Decide what the current controls ask for. Returns {def, note}; note explains an empty result.
  function resolve(index) {
    var date = M.dates[index];
    if (state.layer === "water") {
      if (state.pol !== "HV") return { def: null, note: UI.t("water_hh_note") };
      return { def: find("water", "HV", date), note: null };
    }
    if (state.layer === "change") {
      if (date === M.reference_date) return { def: null, note: UI.t("change_reference_note") };
      return { def: find("change", state.pol, date), note: null };
    }
    return { def: find("backscatter", state.pol, date), note: null };
  }

  /* ------------------------------------------------------------- map */

  function initMap() {
    bounds = L.latLngBounds(M.bounds); // [[south, west], [north, east]] from the manifest
    map = L.map("map", {
      minZoom: 10,
      maxZoom: 16,
      zoomSnap: 0.25,
      maxBounds: bounds.pad(0.5),          // stay near the study area
      maxBoundsViscosity: 0.8,
      attributionControl: true
    });
    map.fitBounds(bounds, { padding: [12, 12] });
    L.control.scale({ metric: true, imperial: false }).addTo(map);
    overlays = L.layerGroup().addTo(map);
    if (DEBUG) window.VENUS_MAP = map; // debug only: lets the alignment check move the view
  }

  function initBasemap() {
    var reported = false;
    var basemap = L.tileLayer(BASEMAP_URL, {
      attribution: UI.t("basemap_attribution"),
      maxZoom: 17
    });
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
    if (navigator.onLine === false) {
      UI.showNotice(UI.t("basemap_unavailable"));
    }
    basemap.addTo(map);
  }

  /* ---------------------------------------------------------- overlays */

  // Manifest paths are relative to web/data/, so the page prefixes the data folder.
  function imageUrl(def) {
    return "data/" + def.file;
  }

  function opacityFor(def) {
    return debugOpacity !== null ? debugOpacity : OPACITY[def.kind];
  }

  function show(def) {
    var id = def ? def.id : null;
    wanted = id;
    if (!def) {
      if (current) {
        overlays.removeLayer(current);
        current = null;
      }
      return;
    }
    if (current && current.options.venusId === id) return;

    var next = L.imageOverlay(imageUrl(def), L.latLngBounds(def.bounds), {
      opacity: 0,
      interactive: false,
      alt: def.label
    });
    next.options.venusId = id;

    next.on("load", function () {
      if (wanted !== id) {          // the user has moved on: drop this one
        overlays.removeLayer(next);
        return;
      }
      next.setOpacity(opacityFor(def));
      if (current && current !== next) overlays.removeLayer(current);
      current = next;
      if (DEBUG) console.info("overlay", id, "bounds", def.bounds);
    });

    next.on("error", function () {
      UI.setLayerNote(UI.t("error_layer", { name: def.label }));
    });

    overlays.addLayer(next);
  }

  // Ask the browser to fetch the neighbouring frames so stepping through dates is smooth.
  function preloadNeighbours() {
    [-1, 1].forEach(function (step) {
      var index = state.index + step;
      if (index < 0 || index >= M.dates.length) return;
      var def = resolve(index).def;
      if (def) {
        var image = new Image();
        image.src = imageUrl(def);
      }
    });
  }

  /* ------------------------------------------------------------ render */

  function render() {
    var r = resolve(state.index);
    show(r.def);
    var scale = M.scales.change_db_symmetric[state.pol];
    UI.renderLegend(r.def, scale);
    UI.renderInfo(r.def, M);
    UI.setLayerNote(r.note);
    UI.setPolHint(state.pol);
    preloadNeighbours();
  }

  function onChange() {
    state.layer = UI.selectedLayer();
    state.pol = UI.selectedPol();
    state.index = UI.selectedDateIndex();
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
      if (current) current.setOpacity(debugOpacity);
    });

    var outline = null;
    document.getElementById("debug-bounds").addEventListener("change", function (event) {
      if (event.target.checked) {
        outline = L.rectangle(bounds, { color: "#E2B862", weight: 2, dashArray: "6 4", fill: false, interactive: false });
        outline.addTo(map);
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

  function boot() {
    UI.applyStrings();
    if (!M || typeof L === "undefined") {
      UI.showNotice(UI.t("error_no_data"));
      return;
    }
    state.index = M.dates.length - 1;
    UI.populateDates(M.dates, state.index);
    UI.setPol(state.pol);
    UI.renderFooter(V.license, M);
    UI.renderDetection(V.water_stats);

    initMap();
    initBasemap();
    if (DEBUG) initDebug();
    UI.bind({ onChange: onChange });
    render();
  }

  try {
    boot();
  } catch (error) {
    // Never fail silently: show what went wrong, in plain words.
    UI.showNotice("Something went wrong while starting the map: " + error.message);
    throw error;
  }
})();
