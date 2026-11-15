/*
 * legend.js - one legend entry per kind of visual, built from window.VENUS.ramps (the same constants
 * the renderer uses), the manifest, water_stats and offsets. Every swatch carries a text label, so the
 * legend never relies on colour alone.
 */
window.VENUS_LEGEND = (function () {
  "use strict";

  var SUPPORTED = ["rgb", "single_pol", "backscatter", "change", "water", "band", "patches", "context"];
  var UI = window.VENUS_UI;
  var R = function () { return (window.VENUS && window.VENUS.ramps) || {}; };

  function t(key, vars) { return UI.t(key, vars); }
  function fmt(value, digits) { return UI.fmt(value, digits); }

  function swatch(colour, label) {
    return '<span class="lg-swatch" style="background:' + colour + '" aria-hidden="true"></span>' +
      '<span class="lg-swatch-label">' + label + "</span>";
  }

  function entry(title, body, help) {
    var html = '<section class="lg-entry"><h4 class="lg-title">' + title;
    if (help) html += '<button type="button" class="lg-help" aria-expanded="false" aria-label="' +
      t("legend_help") + '">?</button>';
    html += "</h4>";
    if (help) html += '<p class="lg-help-text" hidden>' + help + "</p>";
    return html + body + "</section>";
  }

  function limits(def) {
    if (def.vmin === undefined || def.vmax === undefined) return "";
    return '<p class="lg-note">' + t("legend_limits_short", {
      min: fmt(def.vmin), max: fmt(def.vmax), unit: t("units_db")
    }) + "</p>";
  }

  function rgbEntry(def) {
    var stops = (R().single_pol || {}).hex || [];
    if (def.polarization === "HH" && stops.length === 4) {
      return entry(t("legend_single_pol_title"),
        '<div class="lg-bar">' + stops.map(function (hex, i) {
          return swatch(hex, t(["legend_ramp_low", "legend_ramp_lowmid", "legend_ramp_highmid", "legend_ramp_high"][i]));
        }).join("") + "</div>" + limits(def) +
        '<p class="lg-note">' + t("legend_single_pol_note") + "</p>",
        t("legend_help_single_pol"));
    }
    return entry(t("legend_rgb_title"),
      '<div class="lg-bar">' + [
        swatch("#3FA34D", t("legend_rgb_green")),
        swatch("#E08A2E", t("legend_rgb_orange")),
        swatch("#2F6FD0", t("legend_rgb_blue")),
        swatch("#C0392B", t("legend_rgb_red"))
      ].join("") + "</div>" + limits(def) +
      '<p class="lg-note">' + t("legend_rgb_note") + "</p>" +
      '<p class="lg-note lg-neutral">' + t("legend_rgb_neutral") + "</p>",
      t("legend_help_rgb"));
  }

  function backscatterEntry(def) {
    var grey = R().grey || { min: "#05070D", max: "#F4F6FB" };
    return entry(t("legend_backscatter_title"),
      '<div class="lg-grey" style="background:linear-gradient(90deg,' + grey.min + "," + grey.max + ')"></div>' +
      limits(def) + '<p class="lg-note">' + t("legend_backscatter_note") + "</p>",
      t("legend_help_backscatter"));
  }

  function changeEntry(def) {
    var change = R().change || { hex: ["#3B82F6", "#D9DEE8", "#F59E0B"] };
    return entry(t("legend_change_title"),
      '<div class="lg-bar">' + swatch(change.hex[0], t("legend_change_down")) +
      swatch(change.hex[1], t("legend_change_none")) + swatch(change.hex[2], t("legend_change_up")) +
      "</div>" + limits(def) +
      '<p class="lg-note">' + t("legend_change_offset", { offset: fmt(def.offset_applied_db, 2) }) + "</p>",
      t("legend_help_change"));
  }

  function waterEntry(def, stats) {
    var water = R().water || { hex: "#22D3EE" };
    var band = t("units_km2");
    var note = "";
    if (def.area_km2 !== undefined) {
      note = t("legend_water_numbers", {
        threshold: fmt(def.threshold_db, 2),
        area: fmt(def.area_km2, 1),
        low: fmt(def.band_low_km2, 1),
        high: fmt(def.band_high_km2, 1),
        unit: band
      });
    }
    return entry(t("legend_water_title"),
      '<div class="lg-bar">' + swatch(water.hex, t("legend_water_swatch")) + "</div>" +
      '<p class="lg-note">' + (note || t("legend_water_no_numbers")) + "</p>",
      t("legend_help_water"));
  }

  function bandEntry(def) {
    var band = R().band || { hex: "#FACC15" };
    return entry(t("legend_band_title"),
      '<div class="lg-bar">' + swatch(band.hex, t("legend_band_swatch")) + "</div>" +
      '<p class="lg-note">' + t("legend_band_note", { band: fmt(def.band_db, 1) }) + "</p>",
      t("legend_help_band"));
  }

  function patchesEntry() {
    return entry(t("legend_patches_title"),
      '<p class="lg-note"><span class="lg-outline" aria-hidden="true"></span>' +
      t("legend_patches_note") + "</p>", null);
  }

  function contextEntry() {
    var context = R().context || { hex: "#8899AA" };
    return entry(t("legend_context_title"),
      '<div class="lg-bar">' + swatch(context.hex, t("legend_context_swatch")) + "</div>" +
      '<p class="lg-note">' + t("legend_context_note") + "</p>", null);
  }

  function render(def, manifest, stats, offsets, state) {
    var host = document.getElementById("legend-v4");
    if (!host) return;
    var wanted = [];
    if (def) {
      wanted.push(def.kind);
      if (def.kind === "rgb" && def.polarization === "HH") wanted.push("single_pol");
    }
    if (state && state.context) wanted.push("context");
    if (state && state.patches) wanted.push("patches");
    var html = wanted.map(function (kind) {
      if (kind === "rgb") return rgbEntry(def);
      if (kind === "single_pol") return "";
      if (kind === "backscatter") return backscatterEntry(def);
      if (kind === "change") return changeEntry(def);
      if (kind === "water") return waterEntry(def, stats);
      if (kind === "band") return bandEntry(def);
      if (kind === "patches") return patchesEntry();
      if (kind === "context") return contextEntry();
      return "";
    }).join("");
    host.innerHTML = html;
    host.querySelectorAll(".lg-help").forEach(function (button) {
      button.addEventListener("click", function () {
        var text = button.closest(".lg-entry").querySelector(".lg-help-text");
        var open = button.getAttribute("aria-expanded") === "true";
        button.setAttribute("aria-expanded", String(!open));
        if (text) text.hidden = open;
      });
    });
  }

  function guide() {
    var dialog = document.getElementById("legend-guide");
    if (!dialog) return;
    var body = document.getElementById("legend-guide-body");
    body.innerHTML = [
      [t("legend_rgb_title"), t("legend_rgb_note") + " " + t("legend_rgb_neutral")],
      [t("legend_single_pol_title"), t("legend_single_pol_note")],
      [t("legend_backscatter_title"), t("legend_backscatter_note")],
      [t("legend_change_title"), t("legend_change_guide")],
      [t("legend_water_title"), t("legend_water_guide")],
      [t("legend_band_title"), t("legend_band_note", { band: "1.5" })],
      [t("legend_patches_title"), t("legend_patches_note")],
      [t("legend_context_title"), t("legend_context_note")],
      [t("legend_chips_title"), t("legend_chips_note")],
      [t("legend_mapon_title"), t("legend_mapon_note")]
    ].map(function (row) { return "<dt>" + row[0] + "</dt><dd>" + row[1] + "</dd>"; }).join("");
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function init() {
    var button = document.getElementById("legend-guide-button");
    if (button) button.addEventListener("click", guide);
    var close = document.getElementById("legend-guide-close");
    if (close) close.addEventListener("click", function () {
      var dialog = document.getElementById("legend-guide");
      if (dialog && dialog.close) dialog.close(); else if (dialog) dialog.removeAttribute("open");
    });
  }

  return { render: render, guide: guide, init: init, kinds: SUPPORTED };
})();
