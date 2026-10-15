/* Plausible wiring for the leaderboard portal.
 *
 * Every page loads the Plausible site script (async) and then this file, synchronously, in <head>.
 * It owns the two things the script cannot work out on its own:
 *
 *   1. Which leaderboard a pageview is for. Boards are `benchmark.html?id=<id>` and Plausible drops
 *      query strings, so without help every board reads as one `/benchmark.html` row. Each event
 *      carries a `benchmark` custom property taken from `?id=`.
 *   2. Where on the page people click. One delegated listener sends `Section Click` for every link
 *      or button click, with `section` (the nearest `data-section` region) and `label` (what was
 *      clicked). Outbound links are still also counted by the script's own outbound tracking.
 *
 *   3. Team self-exclusion. `?plausible_ignore=1` sets Plausible's per-browser opt-out
 *      (localStorage `plausible_ignore`), `=0` clears it; the script reads the flag on every event.
 *      With `&hop=1` on the production host the page then forwards to the docs site so one click
 *      covers both origins (screamingface.ai starts the chain, docs ends it). Dev and preview hosts
 *      set the flag for themselves only and never hop.
 *
 * Every call is guarded: a blocked or missing script must never break a page.
 *
 * Loaded as a plain <script> in the browser (exposing window.SFAnalytics) and via require() in
 * tests, the same shape as leaderboard-logic.js. No build step.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.SFAnalytics = api;
    api.install(root);
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var EVENT_SECTION_CLICK = "Section Click";
  var LABEL_MAX = 60;
  var CLICKABLE = "a, button, summary, [role='button']";
  var IGNORE_KEY = "plausible_ignore";
  var PRODUCTION_HOST = "leaderboard.screamingface.ai";
  var NEXT_HOP = "https://docs.screamingface.ai/";

  // What `?plausible_ignore=` asks for: `ignore` is "1" (opt out), "0" (opt back in) or null (nothing
  // asked); `next` is the docs URL to continue to, only for a production page asked to `hop`.
  function selfExclusion(search, hostname) {
    var q = new URLSearchParams(search || "");
    var ig = q.get(IGNORE_KEY);
    if (ig !== "1" && ig !== "0") return { ignore: null, next: null };
    var hop = q.get("hop") === "1" && hostname === PRODUCTION_HOST;
    return { ignore: ig, next: hop ? NEXT_HOP + "?" + IGNORE_KEY + "=" + encodeURIComponent(ig) + "&hop=1" : null };
  }

  // Apply the request to this browser, then forward if the chain continues.
  function applySelfExclusion(root) {
    var r = selfExclusion(root.location && root.location.search, root.location && root.location.hostname);
    if (r.ignore === "1") root.localStorage.setItem(IGNORE_KEY, "true");
    if (r.ignore === "0") root.localStorage.removeItem(IGNORE_KEY);
    if (r.next) root.location.replace(r.next);
    return r;
  }

  // The board a URL's query string points at, or null. Pages without `?id=` are not boards.
  function benchmarkFromSearch(search) {
    var id = new URLSearchParams(search || "").get("id");
    return id ? id : null;
  }

  // Region name for a click: the nearest `data-section` value, or "page" outside every region.
  function sectionFor(sectionAttr) {
    return sectionAttr ? sectionAttr : "page";
  }

  function clean(text) {
    var s = String(text || "").replace(/\s+/g, " ").trim();
    return s.length > LABEL_MAX ? s.slice(0, LABEL_MAX - 1) + "…" : s;
  }

  // What was clicked, in a form a dashboard can group on. A catalogue card's text is a whole
  // description, so a link to a board labels as that board's id instead.
  function labelFor(info) {
    if (info.trackLabel) return clean(info.trackLabel);
    var board = info.href && /(?:^|\/)benchmark\.html\?/.test(info.href)
      ? benchmarkFromSearch(info.href.slice(info.href.indexOf("?")))
      : null;
    if (board) return board;
    var text = clean(info.ariaLabel) || clean(info.text);
    return text || "(unlabelled)";
  }

  function plausible(root) {
    return typeof root.plausible === "function" ? root.plausible : null;
  }

  function onClick(root, event) {
    var target = event.target && event.target.closest ? event.target.closest(CLICKABLE) : null;
    if (!target) return;
    var region = target.closest("[data-section]");
    var send = plausible(root);
    if (!send) return;
    try {
      send(EVENT_SECTION_CLICK, {
        props: {
          section: sectionFor(region && region.getAttribute("data-section")),
          label: labelFor({
            trackLabel: target.getAttribute("data-track-label"),
            href: target.getAttribute("href"),
            ariaLabel: target.getAttribute("aria-label"),
            text: target.textContent,
          }),
        },
      });
    } catch (e) {
      /* analytics unavailable, ignore */
    }
  }

  // Browser entry point: the Plausible queue stub (so calls made before the async script arrives
  // are kept), init with the board property, and the click listener.
  function install(root) {
    try {
      applySelfExclusion(root);
    } catch (e) {
      /* storage or location unavailable, ignore */
    }
    try {
      root.plausible = root.plausible || function () {
        (root.plausible.q = root.plausible.q || []).push(arguments);
      };
      root.plausible.init = root.plausible.init || function (options) {
        root.plausible.o = options || {};
      };
      root.plausible.init({
        customProperties: function () {
          var board = benchmarkFromSearch(root.location && root.location.search);
          return board ? { benchmark: board } : {};
        },
      });
      root.document.addEventListener("click", function (event) { onClick(root, event); }, true);
    } catch (e) {
      /* analytics unavailable, ignore */
    }
  }

  return {
    EVENT_SECTION_CLICK: EVENT_SECTION_CLICK,
    benchmarkFromSearch: benchmarkFromSearch,
    sectionFor: sectionFor,
    labelFor: labelFor,
    selfExclusion: selfExclusion,
    applySelfExclusion: applySelfExclusion,
    install: install,
  };
});
