/*
 * ui.js - panels, controls and text. Owns the DOM outside the map; app.js owns the map and the layers.
 * Reads window.VENUS (data), window.VENUS_STRINGS (text) and window.VENUS_CHARTS (inline SVG).
 * No fetch(), no modules. Missing data is reported in place, never silently skipped.
 */
window.VENUS_UI = (function () {
  "use strict";

  var LANG = "en";
  var handlers = {};

  /* ----------------------------------------------------------------- text */

  function t(key, vars) {
    var dict = (window.VENUS_STRINGS && window.VENUS_STRINGS[LANG]) || {};
    var text = dict[key];
    if (text === undefined) return key;
    if (vars) {
      Object.keys(vars).forEach(function (name) {
        text = text.split("{" + name + "}").join(String(vars[name]));
      });
    }
    return text;
  }

  function applyStrings() {
    document.documentElement.lang = LANG;
    document.querySelectorAll("[data-i18n]").forEach(function (node) {
      node.textContent = t(node.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-label]").forEach(function (node) {
      node.setAttribute("aria-label", t(node.getAttribute("data-i18n-label")));
    });
  }

  /* ----------------------------------------------------------- formatting */

  function fmtDate(iso) {
    var d = new Date(iso + "T00:00:00Z");
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  }

  function fmtShort(iso) {
    var d = new Date(iso + "T00:00:00Z");
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" });
  }

  function fmt(value, digits) {
    var n = Number(value);
    return isFinite(n) ? n.toFixed(digits === undefined ? 1 : digits) : t("info_none");
  }

  function signed(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) return t("info_none");
    return (n > 0 ? "+" : "") + n.toFixed(digits === undefined ? 2 : digits);
  }

  /* ------------------------------------------------------------- controls */

  // The date select, the time slider and the tick labels always show the same index.
  function initDates(dates, index, reference, outage) {
    var select = document.getElementById("date-select");
    var left = document.getElementById("left-date");
    var range = document.getElementById("time-range");
    var ticks = document.getElementById("time-ticks");
    select.innerHTML = "";
    left.innerHTML = "";
    ticks.innerHTML = "";
    dates.forEach(function (day, i) {
      [select, left].forEach(function (sel) {
        var option = document.createElement("option");
        option.value = String(i);
        option.textContent = fmtDate(day) + (day === reference ? " (" + t("date_reference") + ")" : "");
        sel.appendChild(option);
      });
      var li = document.createElement("li");
      li.textContent = fmtShort(day);
      if (outage && day > outage.end && i > 0 && dates[i - 1] < outage.start) li.className = "after-gap";
      ticks.appendChild(li);
    });
    range.max = String(dates.length - 1);
    range.value = String(index);
    select.value = String(index);
    left.value = "0";
  }

  function setDateIndex(i) {
    document.getElementById("date-select").value = String(i);
    document.getElementById("time-range").value = String(i);
  }

  function setLeftIndex(i) {
    document.getElementById("left-date").value = String(i);
  }

  function selectedLayer() {
    var checked = document.querySelector('input[name="layer"]:checked');
    return checked ? checked.value : "backscatter";
  }

  function selectedPol() {
    var checked = document.querySelector('input[name="pol"]:checked');
    return checked ? checked.value : "HV";
  }

  function selectedDateIndex() {
    return Number(document.getElementById("date-select").value);
  }

  function selectedLeftIndex() {
    return Number(document.getElementById("left-date").value);
  }

  function selectedLeftLayer() {
    return document.getElementById("left-layer").value;
  }

  function isChecked(id) {
    return document.getElementById(id).checked;
  }

  function setPol(pol) {
    var input = document.querySelector('input[name="pol"][value="' + pol + '"]');
    if (input) input.checked = true;
  }

  function setLayer(kind) {
    var input = document.querySelector('input[name="layer"][value="' + kind + '"]');
    if (input) input.checked = true;
  }

  function setPolHint(pol) {
    document.getElementById("pol-hint").textContent = t(pol === "HV" ? "pol_hv_hint" : "pol_hh_hint");
  }

  function setPlaying(playing) {
    var button = document.getElementById("play-btn");
    button.setAttribute("aria-pressed", String(playing));
    button.textContent = t(playing ? "pause" : "play");
  }

  function setSwipeOpen(open) {
    document.getElementById("swipe-toggle").checked = open;
    document.getElementById("swipe-controls").hidden = !open;
    document.getElementById("swipe-hint").hidden = !open;
  }

  function setBandAvailable(available) {
    document.getElementById("band-toggle-wrap").hidden = !available;
  }

  function bind(options) {
    handlers = options;
    var fire = function () { if (handlers.onChange) handlers.onChange(); };
    document.querySelectorAll('input[name="layer"], input[name="pol"]').forEach(function (input) {
      input.addEventListener("change", fire);
    });
    ["date-select", "left-date", "left-layer", "band-toggle", "patches-toggle", "swipe-toggle"].forEach(function (id) {
      document.getElementById(id).addEventListener("change", fire);
    });
    document.getElementById("time-range").addEventListener("input", function (event) {
      if (handlers.onTime) handlers.onTime(Number(event.target.value));
    });
    document.getElementById("play-btn").addEventListener("click", function () {
      if (handlers.onPlay) handlers.onPlay();
    });
    document.getElementById("swipe-range").addEventListener("input", function (event) {
      if (handlers.onSplit) handlers.onSplit(Number(event.target.value));
    });
  }

  /* -------------------------------------------------------------- notices */

  function showNotice(text) {
    var el = document.getElementById("basemap-notice");
    el.textContent = text;
    el.hidden = false;
  }

  function hideNotice() {
    document.getElementById("basemap-notice").hidden = true;
  }

  function setLayerNote(text) {
    var el = document.getElementById("layer-note");
    el.textContent = text || "";
    el.hidden = !text;
  }

  var outageTimer = null;
  function flashOutage(show) {
    var el = document.getElementById("outage-note");
    if (outageTimer) clearTimeout(outageTimer);
    el.hidden = !show;
    if (show) {
      outageTimer = setTimeout(function () { el.hidden = true; }, 6000);
    }
  }

  /* --------------------------------------------------------------- legend */

  function addTick(container, label, position) {
    var span = document.createElement("span");
    span.textContent = label;
    span.className = "tick tick-" + position;
    container.appendChild(span);
  }

  /*
   * def: the right-hand layer (or null). scale: change limits from the manifest.
   * extra: {band, patches, leftLabel, rightLabel} for the notes shown with the legend.
   */
  function renderLegend(def, scale, extra) {
    var bar = document.getElementById("legend-bar");
    var ticks = document.getElementById("legend-ticks");
    var caption = document.getElementById("legend-caption");
    var text = document.getElementById("legend-text");
    var more = document.getElementById("legend-extra");
    ticks.innerHTML = "";
    more.textContent = "";
    extra = extra || {};

    if (!def) {
      bar.style.display = "none";
      text.textContent = "";
      caption.textContent = "";
    } else {
      bar.style.display = "";
      if (def.kind === "backscatter") {
        bar.className = "legend-bar legend-grey";
        bar.setAttribute("aria-label", t("legend_backscatter") + ": " + fmt(def.vmin) + " to " + fmt(def.vmax) + " " + t("units_db"));
        text.textContent = t("legend_backscatter");
        addTick(ticks, fmt(def.vmin) + " " + t("units_db"), "start");
        addTick(ticks, fmt(def.vmax) + " " + t("units_db"), "end");
        caption.textContent = t("legend_backscatter_caption");
      } else if (def.kind === "change") {
        var limit = def.vmax !== undefined ? def.vmax : scale;
        bar.className = "legend-bar legend-change";
        bar.setAttribute("aria-label", t("legend_change_words") + ", plus or minus " + fmt(limit) + " " + t("units_db"));
        text.textContent = t("legend_change") + ". " + t("legend_change_words");
        addTick(ticks, "-" + fmt(limit) + " " + t("units_db"), "start");
        addTick(ticks, "0", "middle");
        addTick(ticks, "+" + fmt(limit) + " " + t("units_db"), "end");
        caption.textContent = t("legend_change_caption");
        more.textContent = t("legend_change_offset");
      } else {
        bar.className = "legend-bar legend-water";
        bar.setAttribute("aria-label", t("legend_water"));
        text.textContent = t("legend_water");
        caption.textContent = t("legend_water_caption", { band: fmt(extra.bandDb) });
      }
    }
    if (extra.patches) {
      more.textContent = (more.textContent ? more.textContent + " " : "") +
        t("legend_patches", { threshold: fmt(extra.patchThreshold) });
    }
    if (extra.bandText) {
      more.textContent = (more.textContent ? more.textContent + " " : "") + extra.bandText;
    }
    if (extra.leftLabel) {
      more.textContent = (more.textContent ? more.textContent + " " : "") +
        t("legend_swipe_both", { left: extra.leftLabel, right: extra.rightLabel });
    }
  }

  /* ---------------------------------------------------------- layer info */

  function row(list, label, value) {
    var dt = document.createElement("dt");
    dt.textContent = label;
    var dd = document.createElement("dd");
    dd.textContent = value;
    list.appendChild(dt);
    list.appendChild(dd);
  }

  // Shared rows for one layer. Everything is read from the manifest entry.
  function layerRows(list, def, manifest) {
    row(list, t("info_date"), fmtDate(def.date) + (def.date === manifest.reference_date ? " (" + t("date_reference") + ")" : ""));
    if (def.reference) row(list, t("info_reference"), fmtDate(def.reference));
    row(list, t("info_product"), def.product + ": " + def.label);
    row(list, t("info_crid"), def.crid + " (" + def.maturity + ")");
    row(list, t("info_track"), "track " + def.track + ", frame " + def.frame + ", " + String(def.direction).toLowerCase());
    row(list, t("info_pol"), def.polarization);
    row(list, t("info_crs"), "native " + def.native_crs + "; display " + def.display_crs);
    row(list, t("info_scale"), def.colormap + (def.vmin !== undefined ? " (" + fmt(def.vmin, 2) + " to " + fmt(def.vmax, 2) + " dB)" : ""));
    row(list, t("info_offset"), def.offset_applied_db !== undefined ? signed(def.offset_applied_db) + " " + t("units_db") : t("info_none"));
    if (def.threshold_db !== undefined) row(list, t("info_threshold"), fmt(def.threshold_db, 2) + " " + t("units_db"));
    if (def.area_km2 !== undefined) {
      row(list, t("info_area"), fmt(def.area_km2, 1) + " " + t("units_km2") +
        " (" + fmt(def.band_low_km2, 1) + " to " + fmt(def.band_high_km2, 1) + " " + t("units_km2") + ")");
    }
    row(list, t("info_multilook"), def.display_multilook > 1
      ? (20 * def.display_multilook) + " m (" + def.display_multilook + "x" + def.display_multilook + " multilook)"
      : "20 m");
  }

  function renderInfo(def, manifest, leftDef) {
    var list = document.getElementById("layer-info");
    var steps = document.getElementById("layer-steps");
    list.innerHTML = "";
    steps.innerHTML = "";
    if (!def) {
      row(list, t("info_none"), "");
      return;
    }
    if (leftDef) {
      row(list, t("info_left"), leftDef.label + ", " + fmtDate(leftDef.date));
      row(list, t("info_right"), def.label + ", " + fmtDate(def.date));
    }
    layerRows(list, def, manifest);
    (def.processing || []).forEach(function (step) {
      var li = document.createElement("li");
      li.textContent = step;
      steps.appendChild(li);
    });
  }

  /* ------------------------------------------------------ water area chart */

  // Area series for the primary method (B) and HH, read from the water statistics file.
  function areaSeries(stats, dates) {
    var byDate = {};
    stats.dates.forEach(function (d) { byDate[d.date] = d; });
    return dates.map(function (day) {
      var entry = byDate[day] || {};
      var b = (entry.methods || {}).B || {};
      var hh = entry.hh_comparison || {};
      return { date: day, area: b.area_km2, low: b.low_km2, high: b.high_km2, hh: hh.area_km2 };
    });
  }

  function renderAreaChart(stats, manifest, bandDb) {
    var host = document.getElementById("area-chart");
    host.innerHTML = "";
    if (!stats || !stats.dates) {
      host.textContent = t("error_missing_data", { name: "water_stats.js" });
      return;
    }
    var dates = manifest.dates;
    var rows = areaSeries(stats, dates);
    var all = [];
    rows.forEach(function (r) {
      [r.low, r.high, r.area, r.hh].forEach(function (v) { if (isFinite(v)) all.push(v); });
    });
    // Non-zero baseline, chosen from the data, and labelled as such.
    var yMin = Math.floor(Math.min.apply(null, all) / 10) * 10 - 10;
    var yMax = Math.ceil(Math.max.apply(null, all) / 10) * 10 + 5;
    var ticks = [];
    for (var v = yMin; v <= yMax; v += 10) ticks.push(v);

    var gap = outageIndices(dates);
    var labels = dates.map(fmtShort);
    var svg = window.VENUS_CHARTS.lineChart({
      width: 320, height: 240, labels: labels, yMin: yMin, yMax: yMax, yTicks: ticks,
      yFormat: function (x) { return String(x); },
      series: [
        { values: rows.map(function (r) { return r.area; }), color: "#E2B862", width: 2.4 },
        { values: rows.map(function (r) { return r.hh; }), color: "#A9B8DA", dashed: true, width: 1.6 }
      ],
      band: {
        low: rows.map(function (r) { return isFinite(r.low) ? r.low : r.area; }),
        high: rows.map(function (r) { return isFinite(r.high) ? r.high : r.area; }),
        color: "#E2B862"
      },
      shade: gap ? { from: gap.from, to: gap.to, color: "#33466f", label: t("chart_outage_label") } : null
    });
    var summary = t("chart_area_aria", { band: fmt(bandDb, 1), baseline: yMin });
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", summary);
    svg.setAttribute("aria-hidden", "false");
    svg.removeAttribute("focusable");
    host.appendChild(svg);

    document.getElementById("area-axis-note").textContent = t("chart_axis_note", { baseline: yMin });
    document.getElementById("area-legend").textContent =
      t("chart_band_legend", { band: fmt(bandDb, 1) }) + ". " + t("chart_hh_legend") + ". " + t("chart_reliability_note");

    var tbody = document.querySelector("#area-table tbody");
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      [fmtDate(r.date), fmt(r.area, 1) + " (" + fmt(r.low, 1) + " to " + fmt(r.high, 1) + ")", fmt(r.hh, 1)].forEach(function (text) {
        var td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });

    var cd = stats.change_detection && stats.change_detection.B;
    document.getElementById("detection-text").textContent =
      (stats.primary_verdict || "") + (cd ? " " + t("detection_hypothesis_note") : "");
  }

  // Index range of the outage: last date before it, first date after it.
  function outageIndices(dates) {
    var start = "2026-07-27", end = "2026-08-10";
    var from = -1, to = -1;
    dates.forEach(function (day, i) {
      if (day < start) from = i;
      if (day > end && to < 0) to = i;
    });
    return from >= 0 && to >= 0 ? { from: from, to: to, start: start, end: end } : null;
  }

  /* ------------------------------------------------------------ offset chart */

  function renderOffsetChart(offsets, manifest) {
    var host = document.getElementById("offset-chart");
    host.innerHTML = "";
    if (!offsets || !offsets.offsets) {
      host.textContent = t("error_missing_data", { name: "offsets.js" });
      return;
    }
    var dates = manifest.dates;
    var series = function (pol) {
      return dates.map(function (day) {
        var row = offsets.offsets.filter(function (r) { return r.date === day && r.pol === pol; })[0];
        return row && row.offset_dB !== null ? Number(row.offset_dB) : null;
      });
    };
    var hh = series("HH"), hv = series("HV");
    var all = hh.concat(hv).filter(function (v) { return v !== null; });
    var lim = Math.max.apply(null, all.map(Math.abs).concat([0.5]));
    var yMax = Math.ceil(lim * 10) / 10;
    var ticks = [-yMax, -yMax / 2, 0, yMax / 2, yMax];
    var gap = outageIndices(dates);
    host.appendChild(window.VENUS_CHARTS.lineChart({
      width: 320, height: 220, labels: dates.map(fmtShort), yMin: -yMax, yMax: yMax,
      yTicks: ticks, yFormat: function (x) { return x.toFixed(1); }, baselineZero: true,
      series: [
        { values: hh, color: "#A9B8DA", dashed: true },
        { values: hv, color: "#E2B862" }
      ],
      shade: gap ? { from: gap.from, to: gap.to, color: "#33466f", label: t("chart_outage_label") } : null
    }));
    var svg = host.querySelector("svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", t("offset_aria"));
    document.getElementById("offset-legend").textContent = t("offset_hh_legend") + " / " + t("offset_hv_legend") + " (" + t("units_db") + ")";
    var hvRow = offsets.offsets.filter(function (r) { return r.pol === "HV" && r.MAD_dB; })[0];
    document.getElementById("offset-mad").textContent = hvRow ? t("offset_mad_note", { mad: fmt(hvRow.MAD_dB, 2) }) : "";
  }

  /* ------------------------------------------------------------ patch panel */

  // Featured patches: the ones Leyan marked use_in_pitch. Empty state says so plainly.
  function renderFeatured(features, onSelect) {
    var list = document.getElementById("featured-list");
    list.innerHTML = "";
    var featured = (features || []).filter(function (f) { return f.properties.use_in_pitch === "yes"; });
    if (!featured.length) {
      var li = document.createElement("li");
      li.className = "muted";
      li.textContent = t("featured_empty");
      list.appendChild(li);
      return;
    }
    featured.forEach(function (feature) {
      var p = feature.properties;
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-quiet featured-btn";
      button.textContent = p.id + " - " + fmt(p.area_km2, 3) + " " + t("units_km2") +
        (p.hypothesis ? " - " + t("patch_hypothesis_prefix") + " " + p.confidence : "");
      button.addEventListener("click", function () { onSelect(feature); });
      item.appendChild(button);
      list.appendChild(item);
    });
  }

  function renderPatch(feature, manifest) {
    var body = document.getElementById("patch-body");
    body.innerHTML = "";
    document.getElementById("patch-panel").open = true;
    if (!feature) {
      body.innerHTML = "";
      var p = document.createElement("p");
      p.className = "muted";
      p.textContent = t("patch_none_selected");
      body.appendChild(p);
      return;
    }
    var props = feature.properties;
    var h = document.createElement("h4");
    h.className = "sub-title";
    h.textContent = props.id;
    body.appendChild(h);

    var list = document.createElement("dl");
    list.className = "info-list";
    row(list, t("patch_area"), fmt(props.area_km2, 3) + " " + t("units_km2"));
    row(list, t("patch_first"), props.first_date ? fmtDate(props.first_date) : t("info_none"));
    row(list, t("patch_dates"), String(props.n_dates));
    row(list, t("patch_sign"), props.sign === "brighter" ? t("patch_sign_brighter") : t("patch_sign_darker"));
    body.appendChild(list);

    // Sparkline of median change per date, HH and HV, from the patch time series.
    var ts = props.timeseries || [];
    var dates = manifest.dates;
    var values = function (pol) {
      return dates.map(function (day) {
        if (day === manifest.reference_date) return 0;
        var r = ts.filter(function (x) { return x.date === day && x.pol === pol; })[0];
        return r && r.delta_db !== null && r.delta_db !== undefined ? Number(r.delta_db) : null;
      });
    };
    var hhV = values("HH"), hvV = values("HV");
    var all = hhV.concat(hvV).filter(function (v) { return v !== null; });
    var lim = Math.max.apply(null, all.map(Math.abs).concat([1]));
    var yMax = Math.ceil(lim);
    var gap = outageIndices(dates);
    var wrap = document.createElement("div");
    wrap.className = "chart-wrap";
    wrap.appendChild(window.VENUS_CHARTS.sparkline({
      labels: dates.map(fmtShort), yMin: -yMax, yMax: yMax, yTicks: [-yMax, 0, yMax],
      yFormat: function (x) { return String(x); },
      series: [{ values: hhV, color: "#A9B8DA", dashed: true }, { values: hvV, color: "#E2B862" }],
      shade: gap ? { from: gap.from, to: gap.to, color: "#33466f" } : null
    }));
    var svg = wrap.querySelector("svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", t("patch_sparkline"));
    body.appendChild(wrap);
    var legend = document.createElement("p");
    legend.className = "muted";
    legend.textContent = t("patch_sparkline") + " (" + t("units_db") + "): HH dashed, HV solid.";
    body.appendChild(legend);

    // Human fields: always labelled; a hypothesis always carries the word "Hypothesis:" and a confidence.
    var human = document.createElement("div");
    if (props.hypothesis) {
      var hyp = document.createElement("p");
      hyp.textContent = t("patch_hypothesis_prefix") + " " + props.hypothesis;
      human.appendChild(hyp);
      var conf = document.createElement("p");
      conf.className = "muted";
      conf.textContent = t("patch_confidence") + ": " + (props.confidence || t("info_none"));
      human.appendChild(conf);
    } else {
      var na = document.createElement("p");
      na.className = "muted";
      na.textContent = t("patch_not_assessed");
      human.appendChild(na);
    }
    body.appendChild(human);

    var close = document.createElement("button");
    close.type = "button";
    close.className = "btn btn-quiet";
    close.setAttribute("data-i18n", "patch_close");
    close.textContent = t("patch_close");
    close.addEventListener("click", function () { if (handlers.onPatchClose) handlers.onPatchClose(); });
    body.appendChild(close);
  }

  /* -------------------------------------------------------------- footer */

  function renderFooter(license) {
    if (license) {
      document.getElementById("footer-credit").textContent = license.data_credit + " " + license.statement;
    }
  }

  function missingNotice(name) {
    return t("error_missing_data", { name: name });
  }

  return {
    t: t,
    applyStrings: applyStrings,
    fmtDate: fmtDate,
    fmt: fmt,
    initDates: initDates,
    setDateIndex: setDateIndex,
    setLeftIndex: setLeftIndex,
    setLayer: setLayer,
    setPol: setPol,
    setPolHint: setPolHint,
    setPlaying: setPlaying,
    setSwipeOpen: setSwipeOpen,
    setBandAvailable: setBandAvailable,
    selectedLayer: selectedLayer,
    selectedPol: selectedPol,
    selectedDateIndex: selectedDateIndex,
    selectedLeftIndex: selectedLeftIndex,
    selectedLeftLayer: selectedLeftLayer,
    isChecked: isChecked,
    bind: bind,
    showNotice: showNotice,
    hideNotice: hideNotice,
    setLayerNote: setLayerNote,
    flashOutage: flashOutage,
    renderLegend: renderLegend,
    renderInfo: renderInfo,
    renderAreaChart: renderAreaChart,
    renderOffsetChart: renderOffsetChart,
    renderPatch: renderPatch,
    renderFeatured: renderFeatured,
    renderFooter: renderFooter,
    outageIndices: outageIndices,
    missingNotice: missingNotice
  };
})();
