/*
 * tour.js - the optional guided tour.
 *
 * A spotlight, a small card, and six stops. Never starts on its own: the
 * welcome card offers it once, the header button can replay it, and every
 * stop can be skipped, stepped back, or exited. Steps whose target is not
 * visible (a panel hidden at this width, story mode on a phone) are left out
 * of the run instead of pointing at nothing.
 */
window.VENUS_TOUR = (function () {
  "use strict";

  var UI = window.VENUS_UI;
  var WELCOME_KEY = "venus-welcome";
  var DONE_KEY = "venus-tour-done";

  var root = null;
  var shade = null;
  var card = null;
  var kicker = null;
  var title = null;
  var body = null;
  var backBtn = null;
  var nextBtn = null;
  var exitBtn = null;
  var welcome = null;

  var active = false;
  var index = 0;
  var steps = [];
  var openedEcho = false;
  var openedData = false;

  function t(key, vars) { return UI.t(key, vars); }
  function byId(id) { return document.getElementById(id); }
  function isMobile() { return window.matchMedia("(max-width: 1100px)").matches; }

  function visible(el) {
    if (!el) return false;
    var rect = el.getBoundingClientRect();
    var style = window.getComputedStyle(el);
    return rect.width > 2 && rect.height > 2 &&
      style.display !== "none" && style.visibility !== "hidden";
  }

  function read(key) {
    try { return window.localStorage.getItem(key); } catch (error) { return null; }
  }

  function write(key, value) {
    try { window.localStorage.setItem(key, value); } catch (error) { /* file:// */ }
  }

  var STEPS = [
    {
      key: "place",
      title: "tour_place_title",
      body: "tour_place_body",
      resolve: function () { return document.querySelector(".place-card"); }
    },
    {
      key: "controls",
      title: "tour_controls_title",
      body: "tour_controls_body",
      resolve: function () {
        return isMobile() ? byId("open-controls") : document.querySelector(".controls");
      }
    },
    {
      key: "legend",
      title: "tour_legend_title",
      body: "tour_legend_body",
      always: true,
      resolve: function () {
        return isMobile() ? byId("open-panel") : byId("legend-inset");
      },
      enter: function () {
        if (isMobile()) return;
        var toggle = byId("data-toggle");
        if (toggle && toggle.getAttribute("aria-expanded") === "false") {
          toggle.click();
          openedData = true;
        }
      },
      leave: function () {
        if (!openedData) return;
        var toggle = byId("data-toggle");
        if (toggle) toggle.click();
        openedData = false;
      }
    },
    {
      key: "timeline",
      title: "tour_timeline_title",
      body: "tour_timeline_body",
      resolve: function () { return document.querySelector(".mission-timeline"); }
    },
    {
      key: "story",
      title: "tour_story_title",
      body: "tour_story_body",
      resolve: function () { return document.querySelector(".story-strip"); }
    },
    {
      key: "echo",
      title: "tour_echo_title",
      body: "tour_echo_body",
      always: true,
      resolve: function () { return byId("echo-panel"); },
      enter: function () {
        if (window.VENUS_ECHO) {
          window.VENUS_ECHO.open();
          openedEcho = true;
        }
      },
      leave: function () {
        if (openedEcho && window.VENUS_ECHO) {
          window.VENUS_ECHO.close();
          openedEcho = false;
        }
      }
    }
  ];

  function collect() {
    return STEPS.filter(function (step) {
      return step.always || visible(step.resolve());
    });
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function overlapArea(a, b) {
    var x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
    var y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
    return x * y;
  }

  function panelRects(target) {
    var selectors = [
      ".place-card", ".controls", ".panel", "#legend-inset", ".locator",
      ".timebar", ".mission-timeline", ".story-strip", "#echo-panel"
    ];
    var rects = [];
    selectors.forEach(function (selector) {
      var el = document.querySelector(selector);
      if (!el || el === target || !visible(el)) return;
      var rect = el.getBoundingClientRect();
      if (rect.width > 2 && rect.height > 2) rects.push(rect);
    });
    return rects;
  }

  function positionCard() {
    var step = steps[index];
    if (!step) return;
    var target = step.resolve();
    var cardW = card.offsetWidth;
    var cardH = card.offsetHeight;
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var rect = target ? target.getBoundingClientRect() : null;

    if (!rect || rect.width < 2) {
      shade.hidden = true;
      card.style.left = Math.round((vw - cardW) / 2) + "px";
      card.style.top = Math.round((vh - cardH) / 2) + "px";
      return;
    }

    shade.hidden = false;
    var pad = 6;
    shade.style.left = Math.round(rect.left - pad) + "px";
    shade.style.top = Math.round(rect.top - pad) + "px";
    shade.style.width = Math.round(rect.width + pad * 2) + "px";
    shade.style.height = Math.round(rect.height + pad * 2) + "px";

    var gap = 16;
    var others = panelRects(target);
    var centred = clamp(rect.left + rect.width / 2 - cardW / 2, 12, vw - cardW - 12);
    var candidates = [];

    if (rect.bottom + gap + cardH <= vh - 12) {
      candidates.push({ x: centred, y: rect.bottom + gap });
    }
    if (rect.top - gap - cardH >= 12) {
      candidates.push({ x: centred, y: rect.top - gap - cardH });
    }
    if (rect.right + gap + cardW <= vw - 12) {
      candidates.push({ x: rect.right + gap, y: clamp(rect.top, 12, vh - cardH - 12) });
    }
    if (rect.left - gap - cardW >= 12) {
      candidates.push({ x: rect.left - gap - cardW, y: clamp(rect.top, 12, vh - cardH - 12) });
    }
    if (!candidates.length) {
      candidates.push({ x: centred, y: clamp(rect.bottom + gap, 12, vh - cardH - 12) });
    }

    var best = null;
    var bestScore = Infinity;
    candidates.forEach(function (candidate, order) {
      var box = { left: candidate.x, top: candidate.y, right: candidate.x + cardW, bottom: candidate.y + cardH };
      var score = order * 1000; // keep the preferred order on ties
      others.forEach(function (rectOfPanel) { score += overlapArea(box, rectOfPanel); });
      if (score < bestScore) { bestScore = score; best = candidate; }
    });

    card.style.left = Math.round(best.x) + "px";
    card.style.top = Math.round(best.y) + "px";
  }

  function render() {
    var step = steps[index];
    if (!step) { finish(); return; }

    kicker.textContent = t("tour_progress", { n: index + 1, total: steps.length });
    title.textContent = t(step.title);
    body.textContent = t(step.body);

    backBtn.hidden = index === 0;
    nextBtn.textContent = t(index === steps.length - 1 ? "tour_finish" : "tour_next");

    positionCard();
    // A panel that slides in (Echo) needs a moment before it can be measured.
    window.setTimeout(positionCard, 340);

    var target = step.resolve();
    if (target && typeof target.scrollIntoView === "function") {
      var rect = target.getBoundingClientRect();
      if (rect.top < 0 || rect.bottom > window.innerHeight) {
        target.scrollIntoView({ block: "center", inline: "nearest" });
        window.setTimeout(positionCard, 120);
      }
    }

    title.focus({ preventScroll: true });
  }

  function enterStep(step) {
    if (step && typeof step.enter === "function") step.enter();
  }

  function leaveStep(step) {
    if (step && typeof step.leave === "function") step.leave();
  }

  function start() {
    if (!root) return;
    steps = collect();
    if (!steps.length) return;
    index = 0;
    active = true;
    openedEcho = false;
    root.hidden = false;
    enterStep(steps[0]);
    render();
  }

  function close(completed) {
    if (!active) return;
    leaveStep(steps[index]);
    active = false;
    root.hidden = true;
    if (completed) write(DONE_KEY, "1");
    if (byId("tour-trigger")) byId("tour-trigger").focus({ preventScroll: true });
  }

  function finish() { close(true); }

  function next() {
    if (!active) return;
    if (index >= steps.length - 1) { finish(); return; }
    leaveStep(steps[index]);
    index += 1;
    enterStep(steps[index]);
    render();
  }

  function back() {
    if (!active || index === 0) return;
    leaveStep(steps[index]);
    index -= 1;
    render();
  }

  /* welcome offer, shown once */

  function hideWelcome() {
    if (!welcome) return;
    welcome.hidden = true;
    write(WELCOME_KEY, "1");
  }

  function initWelcome() {
    welcome = byId("welcome");
    if (!welcome) return;

    // Wire the offer whether or not it is shown, so it can be replayed.
    byId("welcome-tour").addEventListener("click", function () {
      hideWelcome();
      start();
    });
    byId("welcome-ask").addEventListener("click", function () {
      hideWelcome();
      if (window.VENUS_ECHO) window.VENUS_ECHO.open();
    });
    byId("welcome-close").addEventListener("click", hideWelcome);

    if (read(WELCOME_KEY) === "1") return;

    // Do not fight the intro animation or the map's first paint.
    window.setTimeout(function () { welcome.hidden = false; }, 1800);
  }

  function init() {
    root = byId("tour");
    shade = byId("tour-shade");
    card = byId("tour-card");
    kicker = byId("tour-kicker");
    title = byId("tour-title");
    body = byId("tour-body");
    backBtn = byId("tour-back");
    nextBtn = byId("tour-next");
    exitBtn = byId("tour-exit");
    if (!root || !card) return;

    byId("tour-trigger").addEventListener("click", start);
    nextBtn.addEventListener("click", next);
    backBtn.addEventListener("click", back);
    exitBtn.addEventListener("click", function () { close(false); });

    document.addEventListener("keydown", function (event) {
      if (!active) return;
      if (event.key === "Escape") { event.preventDefault(); close(false); }
      else if (event.key === "ArrowRight") { event.preventDefault(); next(); }
      else if (event.key === "ArrowLeft") { event.preventDefault(); back(); }
    });

    window.addEventListener("resize", function () { if (active) positionCard(); });

    initWelcome();
  }

  init();

  return { start: start, next: next, back: back, close: close };
})();
