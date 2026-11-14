/* Team Venus - app logic. Plain ES2020, no dependencies except Leaflet (vendored).
 *
 * Three view modes, all driven by the same pre-computed static assets:
 *   Date   - one dB overlay for the selected date
 *   Swipe  - first date on the left, selected date on the right, draggable divider
 *   Change - the dB difference (selected minus first), scene-wide offset removed
 */

(function () {
  "use strict";

  var MANIFEST = window.VENUS_MANIFEST || null;

  var state = {
    manifest: null,
    pol: "HV",
    index: 0,
    mode: "swipe",
    split: 50,
    opacity: 1
  };

  var map = null;
  var layers = { before: null, after: null, change: null };
  var handleEl = null;
  var tagLeft = null;
  var tagRight = null;
  var dragging = false;

  var el = {};

  /* ------------------------------------------------------------------ helpers */

  function fmtDate(iso) {
    var d = new Date(iso + "T00:00:00Z");
    return d.toLocaleDateString("en-GB", {
      day: "2-digit", month: "short", year: "numeric", timeZone: "UTC"
    });
  }

  function fmtDb(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) return "-";
    return (n > 0 ? "+" : "") + n.toFixed(digits === undefined ? 1 : digits) + " dB";
  }

  function current() { return state.manifest.dates[state.index]; }
  function firstDate() { return state.manifest.dates[0]; }
  function pol() { return state.pol; }

  function assetUrl(name) { return "assets/" + name; }

  function showStatus(html) {
    if (!el.status) return;
    el.status.innerHTML = html;
    el.status.classList.add("visible");
  }

  function hideStatus() {
    if (el.status) el.status.classList.remove("visible");
  }

  /* -------------------------------------------------------------------- layers */

  function clearLayers() {
    ["before", "after", "change"].forEach(function (key) {
      if (layers[key]) {
        map.removeLayer(layers[key]);
        layers[key] = null;
      }
    });
  }

  function boundsOf(entry) {
    // Leaflet order: [[south, west], [north, east]]
    return [[entry.bounds[0], entry.bounds[1]], [entry.bounds[2], entry.bounds[3]]];
  }

  function addOverlay(entry, png, opacity) {
    return L.imageOverlay(assetUrl(png), boundsOf(entry), {
      opacity: opacity,
      interactive: false,
      className: "venus-layer"
    }).addTo(map);
  }

  function applySplit() {
    if (layers.after && layers.after._image) {
      layers.after._image.style.clipPath = "inset(0 0 0 " + state.split + "%)";
    }
    if (handleEl) handleEl.style.left = state.split + "%";
  }

  function render() {
    clearLayers();
    var entry = current();
    var first = firstDate();
    var polKey = pol();

    // Date labels
    var showTags = state.mode === "swipe";
    tagLeft.classList.toggle("hidden", !showTags);
    tagRight.classList.toggle("hidden", !showTags);
    handleEl.classList.toggle("hidden", !showTags);
    if (showTags) {
      tagLeft.textContent = fmtDate(first.date);
      tagRight.textContent = fmtDate(entry.date);
    }

    if (state.mode === "change") {
      var changeEntry = state.manifest.changes.find(function (c) { return c.date === entry.date; });
      if (changeEntry && changeEntry.layers[polKey]) {
        var c = changeEntry.layers[polKey];
        if (layers.before) { layers.before.setUrl(assetUrl(first.layers[polKey].png)); }
        layers.change = addOverlay(entry, c.png, state.opacity);
      } else {
        // The first date has no difference to the first date; show it plainly instead.
        layers.after = addOverlay(entry, entry.layers[polKey].png, state.opacity);
      }
    } else if (state.mode === "swipe" && entry.date !== first.date) {
      layers.before = addOverlay(first, first.layers[polKey].png, state.opacity);
      layers.after = addOverlay(entry, entry.layers[polKey].png, state.opacity);
      applySplit();
    } else {
      layers.after = addOverlay(entry, entry.layers[polKey].png, state.opacity);
    }

    renderLegend();
    renderStats();
    renderProvenance();
  }

  /* -------------------------------------------------------------------- legend */

  function renderLegend() {
    var entry = current();
    var layer = entry.layers[pol()];

    if (state.mode === "change") {
      var changeEntry = state.manifest.changes.find(function (c) { return c.date === entry.date; });
      if (changeEntry && changeEntry.layers[pol()]) {
        var c = changeEntry.layers[pol()];
        var lim = c.limit_db;
        el.legendBar.style.background =
          "linear-gradient(90deg,#313695 0%,#74add1 25%,#f7f7f7 50%,#f46d43 75%,#a50026 100%)";
        el.legendTicks.innerHTML =
          "<span>-" + lim.toFixed(1) + "</span><span>0</span><span>+" + lim.toFixed(1) + "</span>";
        el.legendCaption.innerHTML =
          "Change in backscatter, <strong>" + pol() + "</strong>, " + fmtDate(entry.date) +
          " minus " + fmtDate(firstDate().date) + ". <strong>Blue = less radar echo on the later " +
          "date</strong> (smoother or wetter). <strong>Red = more echo</strong> (rougher or drier). " +
          "Scene-wide offset of " +
          fmtDb(c.offset_dB_removed, 2) + " removed; scale is +/-" + lim.toFixed(1) + " dB.";
        return;
      }
      el.legendBar.style.background = "#222";
      el.legendTicks.innerHTML = "";
      el.legendCaption.textContent = "This is the first date, so there is nothing to compare it with yet.";
      return;
    }

    var stops = [];
    for (var i = 0; i <= 10; i++) {
      var g = Math.round((i / 10) * 255);
      stops.push("rgb(" + g + "," + g + "," + g + ") " + (i * 10) + "%");
    }
    el.legendBar.style.background = "linear-gradient(90deg," + stops.join(",") + ")";
    el.legendTicks.innerHTML =
      "<span>" + layer.vmin.toFixed(1) + " dB</span><span>" + layer.vmax.toFixed(1) + " dB</span>";
    el.legendCaption.innerHTML =
      "Gamma-0 backscatter, <strong>" + pol() + "</strong>, " + fmtDate(entry.date) +
      ". Dark = smooth (open water throws the radar away). Bright = rough or textured " +
      "(shore, salt crust, vegetation). Stretch 2nd-98th percentile.";
  }

  /* --------------------------------------------------------------------- stats */

  function renderStats() {
    var entry = current();
    var layer = entry.layers[pol()];
    var water = layer.water_km2;
    var low = layer.water_low_km2;
    var high = layer.water_high_km2;

    var cells = [
      ["Mapped water", water.toFixed(0) + " km²",
        "±" + Math.max(water - low, high - water).toFixed(0) + " km² threshold band"],
      ["Water threshold", layer.water_threshold_db.toFixed(1) + " dB", "Otsu, per image"],
      ["Dates in series", String(state.manifest.dates.length), "12-day repeat, one geometry"],
      ["Pixel size", state.manifest.processing.pixel_spacing_m + " m",
        state.manifest.processing.multilook + "x" + state.manifest.processing.multilook + " multilook"]
    ];

    el.stats.innerHTML = cells.map(function (c) {
      return '<dl class="stat"><dt>' + c[0] + "</dt><dd>" + c[1] +
        "<br><small>" + c[2] + "</small></dd></dl>";
    }).join("");
  }

  /* ---------------------------------------------------------------- provenance */

  function renderProvenance() {
    var m = state.manifest;
    var entry = current();
    el.provenance.innerHTML =
      "<code>" + entry.granule + "</code><br>" +
      m.mission.product + " · " + m.mission.maturity + " (" + m.mission.crid + ")<br>" +
      "track " + m.mission.track + " frame " + m.mission.frame + " " +
      m.mission.direction.toLowerCase() + " · EPSG:" + m.mission.epsg + "<br>" +
      m.processing.db + " · " + m.processing.speckle_filter +
      "<br>Generated " + m.generated_utc;
  }

  /* ------------------------------------------------------------------ controls */

  function setMode(mode) {
    state.mode = mode;
    Array.prototype.forEach.call(el.mode.querySelectorAll("button"), function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
    });
    render();
  }

  function setPol(pol) {
    state.pol = pol;
    Array.prototype.forEach.call(el.pol.querySelectorAll("button"), function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.pol === pol));
    });
    render();
  }

  function setIndex(i) {
    state.index = Math.max(0, Math.min(state.manifest.dates.length - 1, i));
    el.dateRange.value = String(state.index);
    el.dateOutput.textContent = fmtDate(current().date);
    render();
  }

  function wireControls() {
    el.mode.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-mode]");
      if (b) setMode(b.dataset.mode);
    });

    el.pol.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-pol]");
      if (b) setPol(b.dataset.pol);
    });

    el.dateRange.addEventListener("input", function () { setIndex(Number(el.dateRange.value)); });

    el.opacityRange.addEventListener("input", function () {
      state.opacity = Number(el.opacityRange.value) / 100;
      el.opacityOutput.textContent = Math.round(state.opacity * 100) + "%";
      ["before", "after", "change"].forEach(function (k) {
        if (layers[k]) layers[k].setOpacity(state.opacity);
      });
    });

    // Drag the swipe divider
    function pointerSplit(clientX) {
      var rect = el.map.getBoundingClientRect();
      var pct = ((clientX - rect.left) / rect.width) * 100;
      state.split = Math.max(2, Math.min(98, pct));
      applySplit();
    }

    el.map.addEventListener("pointerdown", function (e) {
      if (state.mode !== "swipe") return;
      if (e.target.closest(".leaflet-control")) return;
      dragging = true;
      el.map.setPointerCapture(e.pointerId);
      pointerSplit(e.clientX);
    });
    el.map.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      pointerSplit(e.clientX);
    });
    el.map.addEventListener("pointerup", function (e) {
      dragging = false;
      try { el.map.releasePointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    });
  }

  /* ---------------------------------------------------------------------- init */

  function initMap() {
    var b = state.manifest.grid.bounds; // [south, west, north, east]

    map = L.map("map", {
      zoomControl: true,
      attributionControl: true,
      maxZoom: 15,
      minZoom: 8
    });

    // Basemap tiles need a network connection; the radar overlays do not, so the app still works
    // offline - it just loses the background map.
    var tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19
    });
    tiles.on("tileerror", function () {
      // Silent: no tiles simply means we are offline.
    });
    tiles.addTo(map);

    map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: [12, 12] });
    map.attributionControl.setPrefix("");

    handleEl = document.getElementById("swipeHandle");
    tagLeft = document.getElementById("tagLeft");
    tagRight = document.getElementById("tagRight");
  }

  function boot() {
    el.map = document.getElementById("map");
    el.status = document.getElementById("status");
    el.mode = document.getElementById("mode");
    el.pol = document.getElementById("pol");
    el.dateRange = document.getElementById("dateRange");
    el.dateOutput = document.getElementById("dateOutput");
    el.opacityRange = document.getElementById("opacityRange");
    el.opacityOutput = document.getElementById("opacityOutput");
    el.legendBar = document.getElementById("legendBar");
    el.legendTicks = document.getElementById("legendTicks");
    el.legendCaption = document.getElementById("legendCaption");
    el.stats = document.getElementById("stats");
    el.provenance = document.getElementById("provenance");

    if (!MANIFEST) {
      showStatus("<div><strong>No web assets found.</strong><br>" +
        "Run <code>.venv\\Scripts\\python scripts\\05_export_web_assets.py</code> first, " +
        "then reload this page.</div>");
      return;
    }

    state.manifest = MANIFEST;
    state.index = MANIFEST.dates.length - 1;
    state.pol = MANIFEST.polarizations.indexOf("HV") >= 0 ? "HV" : MANIFEST.polarizations[0];

    // Populate polarization buttons from the manifest
    el.pol.innerHTML = MANIFEST.polarizations.map(function (p) {
      return '<button type="button" data-pol="' + p + '" aria-pressed="false">' + p + "</button>";
    }).join("");

    // Date slider
    el.dateRange.min = "0";
    el.dateRange.max = String(MANIFEST.dates.length - 1);
    el.dateRange.step = "1";

    initMap();
    wireControls();
    setPol(state.pol);
    setMode("swipe");
    setIndex(state.index);
    hideStatus();

    el.dateRange.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { e.preventDefault(); setIndex(state.index - 1); }
      if (e.key === "ArrowRight") { e.preventDefault(); setIndex(state.index + 1); }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
