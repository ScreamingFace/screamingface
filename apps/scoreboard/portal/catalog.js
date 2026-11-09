/* Homepage only: one compact response, then local search/filter/paging. */
(function () {
  "use strict";
  var P = window.ScorePortal;
  var L = window.SFLeaderboardLogic;
  var PAGE_SIZE = 9;
  var SCORED_PREFERENCE = "sf_catalog_has_scores";

  function init() {
    var nodes = {};
    ["status", "cards", "more", "search", "scored", "count", "controls"].forEach(function (name) {
      nodes[name] = document.getElementById("benchmark-" + name);
    });
    if (!nodes.cards) return;
    // STORY: retain the visitor's filter across refreshes in this tab session.
    nodes.scored.checked = true;
    try {
      nodes.scored.checked = window.sessionStorage.getItem(SCORED_PREFERENCE) !== "false";
    } catch (_) {
      // WHY: blocked storage must not prevent browsing with the default filter.
    }
    var catalog = [];
    var matches = [];
    var shown = 0;
    P.showLoading(nodes.status, "Loading benchmarks…");
    nodes.cards.hidden = true;
    nodes.more.hidden = true;
    nodes.controls.hidden = true;

    function showNext() {
      var end = Math.min(shown + PAGE_SIZE, matches.length);
      for (; shown < end; shown++) {
        var b = matches[shown];
        nodes.cards.appendChild(P.benchmarkCard(b, { best: b.best_score }));
      }
      nodes.more.hidden = shown >= matches.length;
    }

    function applyFilters() {
      var searched = L.filterBenchmarks(catalog, nodes.search.value);
      // Zero and negative values are scores; null is not zero.
      matches = nodes.scored.checked ? searched.filter(function (b) {
        return typeof b.best_score === "number" && Number.isFinite(b.best_score);
      }) : searched;
      shown = 0;
      P.clear(nodes.cards);
      nodes.cards.hidden = false;
      nodes.count.textContent = matches.length + " matching benchmark" + (matches.length === 1 ? "" : "s") +
        (nodes.scored.checked ? " with scores" : "");
      if (!matches.length) {
        P.showEmpty(nodes.status, searched.length ?
          "Matching benchmarks have no scores yet. Uncheck “Has scores” to see them." :
          "No benchmarks match your search.");
      } else P.setStatus(nodes.status, null);
      showNext();
    }

    nodes.more.addEventListener("click", showNext);
    nodes.search.addEventListener("input", applyFilters);
    function changeScoredFilter() {
      try {
        window.sessionStorage.setItem(SCORED_PREFERENCE, String(nodes.scored.checked));
      } catch (_) {
        // WHY: filtering still works when storage is denied or full.
      }
      applyFilters();
    }
    nodes.scored.addEventListener("change", changeScoredFilter);

    P.fetchJson("/v1/benchmarks/summary").then(function (data) {
      // No fallback to 86 detailed requests: a failed summary has an explicit error state.
      if (!data || !Array.isArray(data.benchmarks)) throw new Error("Invalid catalog response");
      catalog = data.benchmarks.slice().sort(function (a, b) {
        return (a.display_name || a.id).localeCompare(b.display_name || b.id, "en", { sensitivity: "base" }) ||
          a.id.localeCompare(b.id, "en");
      });
      nodes.controls.hidden = false;
      applyFilters();
      if (!catalog.length) P.showEmpty(nodes.status, "No listed benchmarks yet.");
    }).catch(function (err) {
      nodes.controls.hidden = true;
      nodes.cards.hidden = true;
      nodes.more.hidden = true;
      P.showError(nodes.status, P.describeError(err, { generic: "Could not load benchmarks — try again later." }));
    });
  }
  P.ready(init);
})();
