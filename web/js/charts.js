/*
 * charts.js - tiny inline-SVG charts. No library. Every value shown comes in as data from the caller.
 * Exposes window.VENUS_CHARTS.lineChart(options) and window.VENUS_CHARTS.sparkline(options).
 * Each returns an <svg> element. The caller adds accessible labels and a text table next to it.
 */
window.VENUS_CHARTS = (function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";

  function el(name, attrs, text) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Map a value to a pixel position on a linear scale.
  function scale(value, domainMin, domainMax, rangeMin, rangeMax) {
    var span = domainMax - domainMin || 1;
    return rangeMin + ((value - domainMin) / span) * (rangeMax - rangeMin);
  }

  // Build the path for a line that skips missing (null) values.
  function linePath(values, xOf, yOf) {
    var d = "";
    var pen = false;
    values.forEach(function (v, i) {
      if (v === null || v === undefined || !isFinite(v)) { pen = false; return; }
      d += (pen ? " L " : " M ") + xOf(i).toFixed(1) + " " + yOf(v).toFixed(1);
      pen = true;
    });
    return d;
  }

  /*
   * options: {
   *   width, height, labels: [string per x index], yMin, yMax, yTicks: [numbers], yFormat: fn,
   *   series: [{values, color, dashed, label}], band: {low, high, color} (optional),
   *   shade: {from, to, color, label} (optional, x index range), baselineZero: bool
   * }
   */
  function lineChart(opt) {
    var W = opt.width || 640, H = opt.height || 260;
    var m = { left: 56, right: 14, top: 14, bottom: 44 };
    var plotW = W - m.left - m.right, plotH = H - m.top - m.bottom;
    var n = opt.labels.length;
    var xOf = function (i) { return m.left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW); };
    var yOf = function (v) { return m.top + plotH - scale(v, opt.yMin, opt.yMax, 0, plotH); };

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "xMidYMid meet", class: "chart", focusable: "false", "aria-hidden": "true" });

    if (opt.shade) {
      var x0 = xOf(opt.shade.from), x1 = xOf(opt.shade.to);
      svg.appendChild(el("rect", { x: x0, y: m.top, width: x1 - x0, height: plotH, fill: opt.shade.color || "#33466f", opacity: "0.45" }));
      if (opt.shade.label) {
        svg.appendChild(el("text", { x: (x0 + x1) / 2, y: m.top + 12, "text-anchor": "middle", class: "chart-shade-label" }, opt.shade.label));
      }
    }

    (opt.yTicks || []).forEach(function (tick) {
      var y = yOf(tick);
      svg.appendChild(el("line", { x1: m.left, x2: W - m.right, y1: y, y2: y, stroke: "#33466f", "stroke-width": "1" }));
      svg.appendChild(el("text", { x: m.left - 6, y: y + 4, "text-anchor": "end", class: "chart-tick" }, opt.yFormat ? opt.yFormat(tick) : String(tick)));
    });

    if (opt.baselineZero && opt.yMin < 0 && opt.yMax > 0) {
      var y0 = yOf(0);
      svg.appendChild(el("line", { x1: m.left, x2: W - m.right, y1: y0, y2: y0, stroke: "#A9B8DA", "stroke-width": "1.2", "stroke-dasharray": "2 3" }));
    }

    if (opt.band) {
      var upper = opt.band.high.map(function (v, i) { return xOf(i).toFixed(1) + " " + yOf(v).toFixed(1); });
      var lower = opt.band.low.map(function (v, i) { return xOf(i).toFixed(1) + " " + yOf(v).toFixed(1); }).reverse();
      svg.appendChild(el("path", { d: "M " + upper.join(" L ") + " L " + lower.join(" L ") + " Z", fill: opt.band.color, opacity: "0.35", stroke: "none" }));
    }

    opt.series.forEach(function (s) {
      var attrs = { d: linePath(s.values, xOf, yOf), fill: "none", stroke: s.color, "stroke-width": s.width || 2.2, "stroke-linejoin": "round" };
      if (s.dashed) attrs["stroke-dasharray"] = "6 4";
      svg.appendChild(el("path", attrs));
      s.values.forEach(function (v, i) {
        if (v === null || v === undefined || !isFinite(v)) return;
        svg.appendChild(el("circle", { cx: xOf(i), cy: yOf(v), r: s.dashed ? 2.4 : 3, fill: s.color }));
      });
    });

    opt.labels.forEach(function (label, i) {
      var show = n <= 9 || i % 2 === 0;
      if (!show) return;
      svg.appendChild(el("text", { x: xOf(i), y: H - 22, "text-anchor": "end", transform: "rotate(-35 " + xOf(i) + " " + (H - 22) + ")", class: "chart-tick" }, label));
    });

    return svg;
  }

  /* Small chart for one patch: values per date for HH and HV, with the outage shaded. */
  function sparkline(opt) {
    return lineChart({
      width: opt.width || 300,
      height: opt.height || 150,
      labels: opt.labels,
      yMin: opt.yMin,
      yMax: opt.yMax,
      yTicks: opt.yTicks || [opt.yMin, 0, opt.yMax],
      yFormat: opt.yFormat,
      series: opt.series,
      shade: opt.shade,
      baselineZero: true
    });
  }

  return { lineChart: lineChart, sparkline: sparkline };
})();
