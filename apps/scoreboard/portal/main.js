/* ScreamingFace Leaderboard Portal — shared utilities + index page.
 *
 * One global namespace, no modules/build tooling. `main.js` owns generic
 * fetching/formatting/DOM/badge/deep-link helpers (the "port" that
 * `benchmark.js` and `spec.js` depend on) plus the index-page rendering.
 *
 * Security posture: every value that originates from the API is community
 * submitted and therefore untrusted. It is written to the DOM exclusively via
 * textContent / createTextNode and attribute setters — never innerHTML — so a
 * malicious spec_id / url4_expression / submitter cannot inject markup.
 */
window.ScorePortal = (function () {
  "use strict";

  var EM_DASH = "—";
  var PORTAL_LOCALE = "en-US";

  /* ---- API base resolution -------------------------------------------- */
  // 1. Explicit override for local smoke tests or alternate deployments.
  // 2. Same-origin when served by the scoreboard app.
  // 3. Local dev fallback for file:// usage.
  function getApiBase() {
    if (window.SCOREBOARD_API_BASE) {
      return String(window.SCOREBOARD_API_BASE).replace(/\/$/, "");
    }
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
      return window.location.origin;
    }
    return "http://localhost:9106";
  }

  /* ---- fetch ----------------------------------------------------------- */
  // Throws an Error carrying `.status` (0 for network/parse failures) so each
  // page can map it to a specific user-facing message.
  function fetchJson(path) {
    var url = getApiBase() + path;
    return fetch(url, { headers: { Accept: "application/json" } }).then(
      function (response) {
        if (!response.ok) {
          var err = new Error("Request failed with status " + response.status);
          err.status = response.status;
          return response
            .text()
            .catch(function () { return ""; })
            .then(function (body) {
              err.body = body;
              throw err;
            });
        }
        return response.text().then(function (body) {
          if (!body) return null;
          try {
            return JSON.parse(body);
          } catch (e) {
            var perr = new Error("Invalid JSON response");
            perr.status = 0;
            throw perr;
          }
        });
      },
      function (networkErr) {
        var err = new Error(networkErr && networkErr.message ? networkErr.message : "Network error");
        err.status = 0;
        throw err;
      }
    );
  }

  /* ---- query params ---------------------------------------------------- */
  function getParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }
  function requireParam(name) {
    var value = getParam(name);
    if (value === null || value === "") {
      var err = new Error("Missing required query parameter: " + name);
      err.missingParam = name;
      throw err;
    }
    return value;
  }

  /* ---- DOM helpers ----------------------------------------------------- */
  function clear(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }
  // Create an element with an optional class and text content (text only).
  function el(tag, className, textValue) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (textValue !== undefined && textValue !== null) {
      node.textContent = String(textValue);
    }
    return node;
  }
  function link(className, href, label) {
    var a = document.createElement("a");
    if (className) a.className = className;
    a.setAttribute("href", href);
    a.textContent = String(label);
    return a;
  }
  // Returns a normalized http(s) URL string, or null for anything else.
  // Untrusted, API-provided absolute URLs (e.g. a benchmark's dataset_url) must
  // pass through this before becoming an anchor href, so a javascript:, data:,
  // or vbscript: URL can never be made clickable. Our own links are relative
  // (…html?…, "/") and do not use this — only externally-sourced absolute
  // URLs do.
  function httpUrlOrNull(value) {
    if (!value) return null;
    try {
      var u = new URL(String(value), window.location.href);
      return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
    } catch (e) {
      return null;
    }
  }

  /* ---- status / loading / error / empty -------------------------------- */
  // A status region is a single element that toggles between loading/error/
  // empty states. Passing kind === null hides it (data is ready to show).
  function setStatus(node, kind, message) {
    if (!node) return;
    if (kind === null) {
      node.hidden = true;
      node.className = "state";
      node.textContent = "";
      return;
    }
    node.hidden = false;
    node.className = "state state-" + kind;
    node.textContent = message;
    node.setAttribute("role", kind === "error" ? "alert" : "status");
  }
  function showLoading(node, message) { setStatus(node, "loading", message || "Loading…"); }
  function showError(node, message) { setStatus(node, "error", message || "Something went wrong."); }
  function showEmpty(node, message) { setStatus(node, "empty", message || "Nothing here yet."); }

  // Translate a fetch error into a page-appropriate message.
  function describeError(err, opts) {
    opts = opts || {};
    if (err && err.missingParam) return opts.missingParam || ("Missing “" + err.missingParam + "”.");
    if (err && err.status === 404) return opts.notFound || "Not found.";
    return opts.generic || "Could not load — try again later.";
  }

  /* ---- formatters ------------------------------------------------------ */
  function formatPercent(value) {
    if (typeof value !== "number" || isNaN(value)) return EM_DASH;
    return (value * 100).toFixed(1) + "%";
  }
  // A benchmark score is benchmark-native: fractional for
  // DRACO, negative for HealthBench — so it renders as a plain number, never as a
  // percentage. formatPercent stays for genuine shares (e.g. the frontier's
  // open_share); do not point it at a score again.
  // Up to 6 significant digits, mirroring the SDK's score formatter so a tester
  // sees the same figure in the notebook report, the submit receipt, the board
  // widget and this portal.
  function formatScore(value) {
    if (typeof value !== "number" || isNaN(value)) return EM_DASH;
    return String(parseFloat(value.toPrecision(6)));
  }
  function formatQuestions(total) {
    if (typeof total !== "number" || isNaN(total)) return EM_DASH;
    return total.toLocaleString(PORTAL_LOCALE);
  }
  function formatDate(value) {
    if (!value) return EM_DASH;
    var d = new Date(value);
    if (isNaN(d.getTime())) return EM_DASH;
    return d.toLocaleString(PORTAL_LOCALE, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  }
  function formatProviders(list) {
    if (!Array.isArray(list) || list.length === 0) return EM_DASH;
    return list.join(", ");
  }
  // Privacy note: a null submitter renders as an em dash. Never "Anonymous" —
  // let the absence speak for itself.
  function formatSubmitter(value) {
    if (value === null || value === undefined || value === "") return EM_DASH;
    return String(value);
  }
  function formatAuthors(values) {
    if (!Array.isArray(values) || values.length === 0) return EM_DASH;
    return values.map(String).join(", ");
  }
  function formatCount(value, singular, plural) {
    var count = typeof value === "number" && !isNaN(value) ? value : 0;
    return count.toLocaleString(PORTAL_LOCALE) + " " + (count === 1 ? singular : plural);
  }

  /* ---- badges & deep links -------------------------------------------- */
  // Returns a square gain-colored "verified" mark only when
  // verified_by_screamingface === true; otherwise an em dash (no badge —
  // absence means unverified).
  //
  function createVerifiedBadge(isVerified) {
    if (isVerified === true) return el("span", "badge-verified", "✓ verified");
    return document.createTextNode(EM_DASH);
  }
  // Copy-to-clipboard button that places the RAW url4_expression on the
  // clipboard — the exact string pasted into the desktop app's Eval Studio
  // "URL4 expression" field. We copy it verbatim (no encoding, no sf://run
  // wrapper): a url4 spec can contain / ( ) ! $ # : and must survive intact.
  function createCopyButton(specId, expression, opts) {
    opts = opts || {};
    var label = opts.label || "Copy";
    var btn = el("button", opts.compact ? "btn ghost" : "btn", label);
    btn.type = "button";
    btn.setAttribute("aria-label", "Copy the URL4 expression for " + specId);
    btn.addEventListener("click", function () {
      function done(ok) {
        btn.textContent = ok ? "✓ copied" : "copy failed";
        setTimeout(function () { btn.textContent = label; }, 1600);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(expression).then(
          function () { done(true); },
          function () { done(false); }
        );
      } else {
        done(false);
      }
    });
    return btn;
  }

  /* ---- benchmark tab strip (shared by benchmark.html) ------------------ */
  // A curated shortlist leads the strip as prominent tabs; the long tail folds into one
  // "More benchmarks" dropdown so the page reads tight instead of wrapping ~65 equal-weight links
  // across eight rows. Which boards lead (and in what order) is editorial curation sourced from
  // leaderboard-logic's FEATURED_BENCHMARK_IDS — not hardcoded here; this renderer still draws
  // only what partitionFeatured hands it, catalog-driven as before.
  function renderTabStrip(container, benchmarks, activeId) {
    if (!container) return;
    clear(container);
    var split = window.SFLeaderboardLogic.partitionFeatured(benchmarks || []);
    split.featured.forEach(function (b) {
      var a = link(null, "benchmark.html?id=" + encodeURIComponent(b.id), b.display_name || b.id);
      if (b.id === activeId) a.setAttribute("aria-current", "page");
      container.appendChild(a);
    });
    if (split.rest.length) {
      container.appendChild(buildMoreSelect(split.rest, activeId));
    }
  }

  // The non-featured boards as a native <select>: keyboard- and screen-reader-operable for free,
  // and no menu widget to build. On change it navigates to the chosen board.
  //
  // WHY the active board is pre-selected when it is non-featured: landing on e.g. ?id=mmlu leaves
  // no featured tab marked, so the control itself must show the current board's name rather than a
  // bare "More benchmarks" placeholder — otherwise the reader has no on-screen cue for where they
  // are. An empty-valued, disabled placeholder leads for every featured board.
  function buildMoreSelect(rest, activeId) {
    var select = el("select", "tabstrip-more");
    select.setAttribute("aria-label", "More benchmarks");
    var activeIsRest = rest.some(function (b) { return b.id === activeId; });

    var placeholder = el("option", null, "More benchmarks…");
    placeholder.value = "";
    placeholder.disabled = true;
    if (!activeIsRest) placeholder.selected = true;
    select.appendChild(placeholder);

    rest.forEach(function (b) {
      // textContent via el(), never innerHTML — display_name is community-submitted (see header).
      var opt = el("option", null, b.display_name || b.id);
      opt.value = b.id;
      if (b.id === activeId) opt.selected = true;
      select.appendChild(opt);
    });

    select.addEventListener("change", function () {
      var id = select.value;
      if (id) window.location.assign("benchmark.html?id=" + encodeURIComponent(id));
    });
    return select;
  }

  /* ---- ready ----------------------------------------------------------- */
  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  /* ---- index page ------------------------------------------------------ */
  // "Subtitle" is not an explicit Benchmark field, so description is its single source here.
  function benchmarkSubtitle(b) {
    return b.description || null;
  }

  // One catalogue card. The whole card is the link to the board: title + focus + up to 100
  // characters of description + best reproducible. Every value is written via textContent (el),
  // never innerHTML — display_name / focus / description are community-submitted (see file header).
  function benchmarkCard(b, board) {
    var card = document.createElement("a");
    card.className = "card";
    card.setAttribute("href", "benchmark.html?id=" + encodeURIComponent(b.id));

    card.appendChild(el("div", "card-title", b.display_name || b.id));
    // Focus: short editorial line; omitted (not em-dashed) on a card so an absent one leaves no gap.
    if (b.focus) card.appendChild(el("div", "card-focus", b.focus));
    var desc = benchmarkSubtitle(b);
    if (desc) card.appendChild(el("div", "card-desc", SFLeaderboardLogic.truncate(desc, 100)));

    // Best reproducible: formatScore, not formatPercent — scores are benchmark-native and can be
    // fractional or negative. Em dash when the board is empty or the fetch failed.
    var best = board && typeof board.best === "number" ? board.best : null;
    var bestRow = el("div", "card-best");
    bestRow.appendChild(el("span", "card-best-label", "Best reproducible"));
    bestRow.appendChild(el("span", "card-best-val mono", best === null ? EM_DASH : formatScore(best)));
    card.appendChild(bestRow);
    return card;
  }

  // No aggregate submission-count endpoint exists, so this makes one leaderboard request per
  // benchmark. `/v1/leaderboard` returns best-per-spec entries (not every raw submission), so this
  // reads
  // as a fusion/spec count, the closest honest proxy for "# submissions" without a
  // dedicated endpoint.
  // top=200 is the route's own MAX_LEADERBOARD_TOP — the true ceiling, not a
  // number picked here.
  //
  // This response already carries the ranked entries, so the catalogue's "Best reproducible"
  // figure is read from the payload we were fetching anyway — no second request.
  function fetchBoard(benchmarkId) {
    return fetchJson("/v1/leaderboard/" + encodeURIComponent(benchmarkId) + "?top=200").then(
      function (data) {
        // The entries-not-baselines decision lives in leaderboard-logic.js so it stays
        // assertable without a browser — see bestEntryScore there.
        return {
          count: ((data && data.entries) || []).length,
          best: window.SFLeaderboardLogic.bestEntryScore(data)
        };
      },
      function () { return null; } // board unknown, not empty — row still renders
    );
  }

  // Show the catalogue `page` cards at a time: hide every card, reveal the first page, and let
  // "Show more" reveal the next page on each click. The button hides itself once all are shown,
  // and never appears when a single page already covers the whole catalogue.
  function revealCardsInBatches(cardsNode, moreNode, page) {
    var cards = cardsNode.children;
    var shown = 0;
    for (var i = 0; i < cards.length; i++) cards[i].hidden = true;
    function revealNext() {
      for (var end = Math.min(shown + page, cards.length); shown < end; shown++) {
        cards[shown].hidden = false;
      }
      moreNode.hidden = shown >= cards.length;
    }
    moreNode.addEventListener("click", revealNext);
    revealNext();
  }

  function initIndex() {
    var statusNode = document.getElementById("benchmark-status");
    var cardsNode = document.getElementById("benchmark-cards");
    var moreNode = document.getElementById("benchmark-more");
    showLoading(statusNode, "Loading benchmarks…");
    cardsNode.hidden = true;
    moreNode.hidden = true;

    fetchJson("/v1/benchmarks").then(
      function (data) {
        // Filter BEFORE the per-board fetches below, so the page does not request a
        // board it will never draw. `/v1/benchmarks` deliberately keeps returning every board —
        // `sf.leaderboards` needs the private ones so challenge participants can submit against
        // them — so the catalogue is trimmed here rather than at the API.
        var listed = SFLeaderboardLogic.listedBenchmarks((data && data.benchmarks) || []);
        // Same curated shortlist as the tab strip, surfaced first here too: the featured cards
        // lead (in FEATURED_BENCHMARK_IDS order), then the rest in catalogue order. Every listed
        // board still renders — the catalogue is exhaustive; only the order and the first-page
        // cutoff change.
        var split = SFLeaderboardLogic.partitionFeatured(listed);
        var benchmarks = split.featured.concat(split.rest);
        if (benchmarks.length === 0) {
          showEmpty(statusNode, "No listed benchmarks yet. The API is live; cards will appear here as soon as benchmark specs are registered.");
          return;
        }
        return Promise.all(benchmarks.map(function (b) { return fetchBoard(b.id); })).then(
          function (boards) {
            clear(cardsNode);
            benchmarks.forEach(function (b, i) { cardsNode.appendChild(benchmarkCard(b, boards[i])); });
            setStatus(statusNode, null);
            cardsNode.hidden = false;
            // Show ~10 at first; "Show more" reveals the next 10 per click (the long tail stays
            // folded so the catalogue reads tight rather than as one endless grid).
            revealCardsInBatches(cardsNode, moreNode, 10);
          }
        );
      },
      function (err) {
        showError(statusNode, describeError(err, { generic: "Could not load benchmarks — try again later." }));
      }
    ).catch(function (err) {
      // WHY: the handler above is the second argument to the *first* `.then`, so it
      // only sees a `/v1/benchmarks` rejection. Anything thrown later — a malformed
      // benchmark entry, a DOM failure, a rejection inside the Promise.all
      // continuation — would otherwise become an unhandled rejection and leave the
      // page stuck on "Loading benchmarks…" with the cards hidden and no error state.
      showError(statusNode, describeError(err, { generic: "Could not load benchmarks — try again later." }));
    });
  }

  /* ---- public surface -------------------------------------------------- */
  var api = {
    getApiBase: getApiBase,
    fetchJson: fetchJson,
    getParam: getParam,
    requireParam: requireParam,
    clear: clear,
    el: el,
    link: link,
    httpUrlOrNull: httpUrlOrNull,
    setStatus: setStatus,
    showLoading: showLoading,
    showError: showError,
    showEmpty: showEmpty,
    describeError: describeError,
    formatPercent: formatPercent,
    formatScore: formatScore,
    formatQuestions: formatQuestions,
    formatDate: formatDate,
    formatProviders: formatProviders,
    formatSubmitter: formatSubmitter,
    formatAuthors: formatAuthors,
    formatCount: formatCount,
    createVerifiedBadge: createVerifiedBadge,
    createCopyButton: createCopyButton,
    renderTabStrip: renderTabStrip,
    ready: ready,
    EM_DASH: EM_DASH,
  };

  // Self-bootstrap the index page when its container is present. benchmark.html
  // and spec.html have no #benchmark-cards, so this is a no-op there.
  ready(function () {
    if (document.getElementById("benchmark-cards")) initIndex();
  });

  return api;
})();
