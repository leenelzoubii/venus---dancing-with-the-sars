/*
 * echo.js - the in-app guide ("Echo").
 *
 * Two answering paths, on purpose:
 *   1. live  - POST /api/chat, a Vercel function that holds the OpenAI key and
 *              receives only the facts of the current view;
 *   2. local - a small, honest answer set built from the same strings. It is
 *              used when the function is missing, offline, rate-limited or slow,
 *              so a demo never dead-ends on a spinner.
 *
 * No data is copied here: numbers are read from window.VENUS (the manifest,
 * water stats) at send time. No fetch happens until someone asks a question.
 */
window.VENUS_ECHO = (function () {
  "use strict";

  var UI = window.VENUS_UI;
  var ENDPOINT = "/api/chat";
  var TIMEOUT_MS = 25000;
  var MAX_HISTORY = 8;

  var panel = null;
  var trigger = null;
  var messagesHost = null;
  var input = null;
  var contextLine = null;
  var suggestions = null;

  var history = [];
  var busy = false;
  var isOpen = false;

  function t(key, vars) { return UI.t(key, vars); }
  function el(id) { return document.getElementById(id); }

  /* ------------------------------------------------------------- the view */

  function checkedValue(name) {
    var input = document.querySelector('input[name="' + name + '"]:checked');
    return input ? input.value : null;
  }

  function currentIndex() {
    var select = el("date-select");
    return select ? Number(select.value) || 0 : 0;
  }

  function layerFor(manifest, kind, pol, date) {
    var layers = manifest.layers || [];
    var exact = layers.filter(function (entry) {
      if (entry.kind !== kind) return false;
      if (kind !== "rgb" && entry.polarization !== pol) return false;
      return entry.date === date;
    });
    if (exact.length) return exact[0];
    var any = layers.filter(function (entry) {
      return entry.kind === kind && (kind === "rgb" || entry.polarization === pol);
    });
    return any.length ? any[0] : null;
  }

  function waterRow(venus, date) {
    var stats = venus.place_water_stats || {};
    var rows = stats.dates || [];
    for (var i = rows.length - 1; i >= 0; i -= 1) {
      if (rows[i].date === date) return rows[i];
    }
    return rows.length ? rows[rows.length - 1] : null;
  }

  function waterSeries(venus) {
    var rows = (venus.place_water_stats || {}).dates || [];
    if (!rows.length) return undefined;
    var step = Math.max(1, Math.ceil(rows.length / 12));
    var out = [];
    for (var i = 0; i < rows.length; i += step) {
      var method = (rows[i].methods || {}).B || {};
      if (method.area_km2 !== undefined) {
        out.push({ date: rows[i].date, area_km2: method.area_km2 });
      }
    }
    return out;
  }

  function layerName(kind) {
    if (kind === "rgb") return t("layer_rgb");
    if (kind === "change") return t("layer_change");
    if (kind === "water") return t("layer_water");
    return t("layer_backscatter");
  }

  function layerMeaning(kind) {
    if (kind === "rgb") return t("echo_layer_rgb");
    if (kind === "change") return t("echo_layer_change");
    if (kind === "water") return t("echo_layer_water");
    return t("echo_layer_backscatter");
  }

  /* Everything the answer may rely on. Nothing is invented here. */
  function facts() {
    var venus = window.VENUS || {};
    var manifest = venus.place_manifest || {};
    var dates = manifest.dates || [];
    var index = Math.max(0, Math.min(dates.length - 1, currentIndex()));
    var date = dates[index] || "";
    var kind = checkedValue("layer") || "backscatter";
    var pol = checkedValue("pol") || "VH";
    var def = layerFor(manifest, kind, pol, date);
    var row = waterRow(venus, date);
    var method = row && row.methods ? row.methods.B || {} : {};
    var swipe = el("swipe-toggle");

    var resolution = def
      ? def.px_size_m_3857 || (def.native_px_m || 30) * (def.display_multilook || 1)
      : undefined;

    var out = {
      place: (manifest.study_area || {}).title,
      place_key: (manifest.study_area || {}).name,
      date: date,
      reference_date: manifest.reference_date,
      first_date: dates[0],
      last_date: dates[dates.length - 1],
      n_dates: dates.length,
      layer: kind,
      polarization: kind === "rgb" ? def && def.polarization : pol,
      product: manifest.product,
      series: manifest.series,
      maturity: manifest.maturity,
      resolution_m: resolution,
      track: manifest.track,
      direction: manifest.direction,
      swipe: Boolean(swipe && swipe.checked),
      verdict: (venus.place_water_stats || {}).primary_verdict,
      layer_meaning: layerMeaning(kind),
      water_series: waterSeries(venus)
    };

    if (method.area_km2 !== undefined) {
      out.water_area_km2 = method.area_km2;
      out.water_band_km2 = [method.low_km2, method.high_km2];
      out.threshold_db = method.threshold_db;
    }
    if (def && def.vmin !== undefined && def.vmax !== undefined) {
      out.color_limits_db = [def.vmin, def.vmax];
    }
    return out;
  }

  function updateContextLine() {
    if (!contextLine) return;
    var f = facts();
    var kindLabel = layerName(f.layer);
    var polLabel = f.layer === "rgb" ? (f.polarization || "VV+VH") : f.polarization;
    contextLine.textContent = t("echo_context", {
      place: f.place || t("app_mark"),
      date: f.date ? UI.fmtDate(f.date) : "",
      layer: kindLabel,
      pol: polLabel
    });
  }

  /* ------------------------------------------------------- local answers */

  var RULES = [
    { key: "echo_kb_deformation", test: /subsid|deform|sinkhole|earthquake|insar|uplift|ground.*(move|moved)|height change/i },
    { key: "echo_kb_water_dark", test: /dark|black|why.*(lake|water)|water.*(dark|black)|ripple|wind/i },
    { key: "echo_kb_pol", test: /\bvh\b|\bvv\b|polar|co-pol|cross-pol/i },
    { key: "echo_kb_band", test: /band|uncertain|amber|noise|threshold|error bar/i },
    { key: "echo_kb_change", test: /change|differ|compare|before|after|blue|orange|shore|coast|edge/i },
    { key: "echo_kb_rgb", test: /rgb|false colou?r|composite|colou?r/i },
    { key: "echo_kb_ponds", test: /pond|potash|evaporat|salt|industry|indus/i },
    { key: "echo_kb_numbers", test: /area|km2|km²|how (much|big)|size of the lake|water.*(much|area)/i },
    { key: "echo_kb_resolution", test: /resolution|pixel|metre|meter|how (sharp|detailed)|30 m/i },
    { key: "echo_kb_dates", test: /date|when|cadence|how many|gap|decade|time series|timeline/i },
    { key: "echo_kb_source", test: /sentinel|nisar|source|dataset|data.*from|where.*from|opera|satellite/i },
    { key: "echo_kb_limits", test: /limit|reliab|trust|accura|careful|caveat/i },
    { key: "echo_kb_what", test: /what am i|looking at|explain|this (map|image|layer)|tell me about/i }
  ];

  function localVars(f) {
    var vars = {
      place: f.place || "",
      date: f.date ? UI.fmtDate(f.date) : "",
      layer: layerName(f.layer),
      pol: f.polarization || "",
      product: f.product || "",
      maturity: f.maturity || "",
      res: f.resolution_m ? Math.round(f.resolution_m) : 30,
      n: f.n_dates || 0,
      first: f.first_date ? UI.fmtDate(f.first_date) : "",
      last: f.last_date ? UI.fmtDate(f.last_date) : "",
      track: f.track || "",
      direction: String(f.direction || "").toLowerCase()
    };
    if (f.water_area_km2 !== undefined) {
      vars.area = UI.fmt(f.water_area_km2, 1);
      vars.low = UI.fmt(f.water_band_km2 && f.water_band_km2[0], 1);
      vars.high = UI.fmt(f.water_band_km2 && f.water_band_km2[1], 1);
    }
    return vars;
  }

  function localAnswer(question) {
    var f = facts();
    var vars = localVars(f);
    var missing = function (value) {
      return value === undefined || value === null || value === "";
    };
    for (var i = 0; i < RULES.length; i += 1) {
      if (!RULES[i].test.test(question)) continue;
      if (RULES[i].key === "echo_kb_numbers" && missing(vars.area)) {
        return t("echo_kb_limits", vars);
      }
      return t(RULES[i].key, vars);
    }
    return t("echo_kb_default", vars);
  }

  /* --------------------------------------------------------------- server */

  function post(question) {
    var body = {
      messages: history.slice(-MAX_HISTORY),
      context: facts()
    };
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, TIMEOUT_MS) : null;

    return fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller ? controller.signal : undefined
    }).then(function (response) {
      if (!response.ok) {
        var error = new Error("HTTP " + response.status);
        error.status = response.status;
        throw error;
      }
      return response.json();
    }).then(function (data) {
      if (!data || typeof data.reply !== "string" || !data.reply.trim()) {
        throw new Error("empty reply");
      }
      return data.reply.trim();
    }).finally(function () {
      if (timer) clearTimeout(timer);
    });
  }

  /* ------------------------------------------------------------------ UI */

  function scrollToEnd() {
    if (messagesHost) messagesHost.scrollTop = messagesHost.scrollHeight;
  }

  function addMessage(role, text, note) {
    var wrap = document.createElement("div");
    wrap.className = "echo-msg echo-msg-" + role;
    if (role === "assistant") {
      var mark = document.createElement("span");
      mark.className = "echo-msg-mark";
      mark.setAttribute("aria-hidden", "true");
      wrap.appendChild(mark);
    }
    var body = document.createElement("p");
    body.className = "echo-msg-body";
    body.textContent = text;
    wrap.appendChild(body);
    if (note) {
      var footnote = document.createElement("p");
      footnote.className = "echo-msg-note";
      footnote.textContent = note;
      wrap.appendChild(footnote);
    }
    messagesHost.appendChild(wrap);
    scrollToEnd();
    return wrap;
  }

  function addThinking() {
    var wrap = document.createElement("div");
    wrap.className = "echo-msg echo-msg-assistant echo-msg-thinking";
    wrap.setAttribute("aria-label", t("echo_thinking"));
    for (var i = 0; i < 3; i += 1) {
      var dot = document.createElement("span");
      dot.setAttribute("aria-hidden", "true");
      wrap.appendChild(dot);
    }
    messagesHost.appendChild(wrap);
    scrollToEnd();
    return wrap;
  }

  function setBusy(value) {
    busy = value;
    if (input) input.disabled = value;
    var send = el("echo-send");
    if (send) send.disabled = value;
    panel.classList.toggle("is-busy", value);
  }

  function showSuggestions() {
    if (suggestions) suggestions.hidden = false;
  }

  function ask(question) {
    question = String(question || "").trim();
    if (!question || busy) return;
    addMessage("user", question);
    history.push({ role: "user", content: question });
    setBusy(true);
    var pending = addThinking();

    post(question).then(function (reply) {
      pending.remove();
      addMessage("assistant", reply);
      history.push({ role: "assistant", content: reply });
    }).catch(function (error) {
      pending.remove();
      var status = error && error.status;
      var note = status === 429 ? t("echo_rate_limited") : t("echo_offline_note");
      addMessage("assistant", localAnswer(question), note);
      if (window.console && console.info) {
        console.info("Echo: using the built-in answer (" + (error && error.message) + ")");
      }
    }).then(function () {
      setBusy(false);
      if (input) input.focus();
    });
  }

  function openPanel() {
    isOpen = true;
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    updateContextLine();
    if (!messagesHost.childElementCount && !history.length) {
      addMessage("assistant", t("echo_intro"));
    }
    if (input) {
      input.value = "";
      input.focus();
    }
    showSuggestions();
    scrollToEnd();
  }

  function closePanel() {
    isOpen = false;
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    trigger.focus();
  }

  function toggle() {
    if (isOpen) closePanel();
    else openPanel();
  }

  /* ----------------------------------------------------------------- init */

  function init() {
    if (!UI) return;
    panel = el("echo-panel");
    trigger = el("echo-trigger");
    messagesHost = el("echo-messages");
    input = el("echo-input");
    contextLine = el("echo-context");
    suggestions = el("echo-suggest");
    if (!panel || !trigger || !messagesHost || !input) return;

    trigger.addEventListener("click", toggle);
    el("echo-close").addEventListener("click", closePanel);

    el("echo-form").addEventListener("submit", function (event) {
      event.preventDefault();
      var value = input.value;
      input.value = "";
      ask(value);
    });

    if (suggestions) {
      suggestions.addEventListener("click", function (event) {
        var button = event.target.closest("[data-q]");
        if (!button) return;
        ask(t(button.getAttribute("data-q")));
      });
    }

    // Re-read the view whenever the panel is reopened; a cheap snapshot.
    ["date-select", "place-select"].forEach(function (id) {
      var node = el(id);
      if (node) node.addEventListener("change", updateContextLine);
    });
    document.querySelectorAll('input[name="layer"], input[name="pol"]').forEach(function (node) {
      node.addEventListener("change", updateContextLine);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen) closePanel();
    });
  }

  init();

  return { ask: ask, open: openPanel, close: closePanel, facts: facts };
})();
