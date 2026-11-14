/*
 * ui.js - panels, controls and text. Owns the DOM outside the map; app.js owns the map and layers.
 * Reads window.VENUS (data) and window.VENUS_STRINGS (text). No fetch(), no modules.
 */
window.VENUS_UI = (function () {
  "use strict";

  var LANG = "en";
  var handlers = {};

  /* ----------------------------------------------------------------- text */

  function t(key, vars) {
    var dict = (window.VENUS_STRINGS && window.VENUS_STRINGS[LANG]) || {};
    var text = dict[key];
    if (text === undefined) {
      return key; // a missing key is shown, never hidden
    }
    if (vars) {
      Object.keys(vars).forEach(function (name) {
        text = text.split("{" + name + "}").join(String(vars[name]));
      });
    }
    return text;
  }

  function applyStrings() {
    document.documentElement.lang = LANG;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-label]").forEach(function (el) {
      el.setAttribute("aria-label", t(el.getAttribute("data-i18n-label")));
    });
  }

  /* ----------------------------------------------------------- formatting */

  function fmtDate(iso) {
    var d = new Date(iso + "T00:00:00Z");
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  }

  function fmt(value, digits) {
    var n = Number(value);
    return isFinite(n) ? n.toFixed(digits === undefined ? 1 : digits) : "not available";
  }

  function signed(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) return "not available";
    return (n > 0 ? "+" : "") + n.toFixed(digits === undefined ? 2 : digits);
  }

  /* ------------------------------------------------------------- controls */

  function populateDates(dates, index) {
    var select = document.getElementById("date-select");
    select.innerHTML = "";
    dates.forEach(function (day, i) {
      var option = document.createElement("option");
      option.value = String(i);
      option.textContent = fmtDate(day) + (i === 0 ? " (" + t("date_reference") + ")" : "");
      select.appendChild(option);
    });
    select.value = String(index);
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

  function setPol(pol) {
    var input = document.querySelector('input[name="pol"][value="' + pol + '"]');
    if (input) input.checked = true;
  }

  function setPolHint(pol) {
    document.getElementById("pol-hint").textContent = t(pol === "HV" ? "pol_hv_hint" : "pol_hh_hint");
  }

  function setLayer(kind) {
    var input = document.querySelector('input[name="layer"][value="' + kind + '"]');
    if (input) input.checked = true;
  }

  function bind(options) {
    handlers = options;
    document.querySelectorAll('input[name="layer"]').forEach(function (input) {
      input.addEventListener("change", function () { handlers.onChange && handlers.onChange(); });
    });
    document.querySelectorAll('input[name="pol"]').forEach(function (input) {
      input.addEventListener("change", function () { handlers.onChange && handlers.onChange(); });
    });
    document.getElementById("date-select").addEventListener("change", function () {
      handlers.onChange && handlers.onChange();
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
    if (!text) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.textContent = text;
    el.hidden = false;
  }

  /* --------------------------------------------------------------- legend */

  function renderLegend(def, changeLimit) {
    var bar = document.getElementById("legend-bar");
    var ticks = document.getElementById("legend-ticks");
    var caption = document.getElementById("legend-caption");
    var text = document.getElementById("legend-text");
    ticks.innerHTML = "";

    if (!def) {
      bar.className = "legend-bar";
      bar.style.display = "none";
      text.textContent = "";
      caption.textContent = "";
      return;
    }
    bar.style.display = "";

    if (def.kind === "backscatter") {
      bar.className = "legend-bar legend-grey";
      bar.setAttribute("aria-label", t("legend_backscatter") + ", " + fmt(def.vmin) + " to " + fmt(def.vmax) + " " + t("units_db"));
      text.textContent = t("legend_backscatter");
      addTick(ticks, fmt(def.vmin) + " " + t("units_db"), "start");
      addTick(ticks, fmt(def.vmax) + " " + t("units_db"), "end");
      caption.textContent = t("legend_backscatter_caption");
    } else if (def.kind === "change") {
      var limit = changeLimit;
      bar.className = "legend-bar legend-change";
      bar.setAttribute("aria-label", t("legend_change") + ", plus or minus " + fmt(limit) + " " + t("units_db"));
      text.textContent = t("legend_change");
      addTick(ticks, "-" + fmt(limit) + " " + t("units_db"), "start");
      addTick(ticks, "0", "middle");
      addTick(ticks, "+" + fmt(limit) + " " + t("units_db"), "end");
      caption.textContent = t("legend_change_caption");
    } else {
      bar.className = "legend-bar legend-water";
      bar.setAttribute("aria-label", t("legend_water"));
      text.textContent = t("legend_water");
      caption.textContent = t("legend_water_caption");
    }
  }

  function addTick(container, label, position) {
    var span = document.createElement("span");
    span.textContent = label;
    span.className = "tick tick-" + position;
    container.appendChild(span);
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

  function renderInfo(def, manifest) {
    var list = document.getElementById("layer-info");
    var steps = document.getElementById("layer-steps");
    list.innerHTML = "";
    steps.innerHTML = "";
    if (!def) {
      row(list, t("info_none"), "");
      return;
    }
    row(list, t("info_date"), fmtDate(def.date) + (def.date === manifest.reference_date ? " (" + t("date_reference") + ")" : ""));
    if (def.reference) row(list, t("info_reference"), fmtDate(def.reference));
    row(list, t("info_product"), def.product + " - " + def.label);
    row(list, t("info_crid"), def.crid + " (" + def.maturity + ")");
    row(list, t("info_track"), "track " + def.track + ", frame " + def.frame + ", " + String(def.direction).toLowerCase());
    row(list, t("info_pol"), def.polarization);
    row(list, t("info_crs"), "native " + def.native_crs + "; display " + def.display_crs);
    row(list, t("info_scale"), def.colormap + (def.vmin !== undefined ? " (" + fmt(def.vmin, 2) + " to " + fmt(def.vmax, 2) + " dB)" : ""));
    row(list, t("info_offset"), def.offset_applied_db !== undefined ? signed(def.offset_applied_db) + " dB" : t("info_none"));
    if (def.threshold_db !== undefined) row(list, t("info_threshold"), fmt(def.threshold_db, 2) + " dB");
    if (def.area_km2 !== undefined) {
      row(list, t("info_area"), fmt(def.area_km2, 1) + " " + t("units_km2") +
        " (" + fmt(def.band_low_km2, 1) + " to " + fmt(def.band_high_km2, 1) + " " + t("units_km2") + ")");
    }
    row(list, t("info_multilook"), def.display_multilook > 1
      ? (20 * def.display_multilook) + " m (" + def.display_multilook + "x" + def.display_multilook + " multilook)"
      : "20 m");
    (def.processing || []).forEach(function (step) {
      var li = document.createElement("li");
      li.textContent = step;
      steps.appendChild(li);
    });
  }

  /* -------------------------------------------------------- detection / footer */

  function renderDetection(stats) {
    var el = document.getElementById("detection-text");
    if (!stats || !stats.primary_verdict) return;
    el.textContent = stats.primary_caption + ". " + stats.primary_verdict;
  }

  function renderFooter(license, manifest) {
    if (license) {
      document.getElementById("footer-credit").textContent = license.data_credit + " " + license.statement;
    }
    document.getElementById("footer-basemap").textContent = t("basemap_attribution");
    document.getElementById("pol-hint").textContent = t("pol_hv_hint");
  }

  return {
    t: t,
    applyStrings: applyStrings,
    fmtDate: fmtDate,
    populateDates: populateDates,
    selectedLayer: selectedLayer,
    selectedPol: selectedPol,
    selectedDateIndex: selectedDateIndex,
    setPol: setPol,
    setLayer: setLayer,
    setPolHint: setPolHint,
    bind: bind,
    showNotice: showNotice,
    hideNotice: hideNotice,
    setLayerNote: setLayerNote,
    renderLegend: renderLegend,
    renderInfo: renderInfo,
    renderDetection: renderDetection,
    renderFooter: renderFooter
  };
})();
