/* ScreamingFace Leaderboard Portal — benchmark (top-N) page.
 *
 * Reads ?id=<benchmark_id>, fetches /v1/leaderboard/{id}, and renders a
 * client-side sortable table. Default sort is score DESC. The Rank column
 * always shows the backend-provided rank (best-per-spec), even when the user
 * sorts by another column — we only reorder rows for display, never recompute
 * the backend's best-per-spec selection (which breaks score ties by newest
 * submission).
 */
(function (P) {
  "use strict";

  // Column definitions. `sort` null => not sortable. `dir` is the default
  // direction applied the first time a column is selected.
  var COLUMNS = [
    { key: "rank", label: "Rank", sort: "number", dir: "asc", cls: "num" },
    // The mark slot is its own column rather than a span inside the spec cell.
    // A column keeps marked and unmarked spec names aligned without hand-tuned widths,
    // which measurably failed (an in-cell slot sized to the badge text grew when
    // the badge was enhanced, shifting that row's name ~64px right of the rest,
    // and it stole width from `.cell-wrap`'s 192px cap, wrapping long spec names).
    { key: "__mark", label: "", sort: null, cls: "col-mark" },
    // Nothing in the payload names a fusion; `spec_id` is the available identifier.
    // The header stays "Spec" so it describes what the cell actually holds; the
    // SOTA mark slot leads this cell, which is the "mark leads the name" part.
    { key: "spec_id", label: "Spec", sort: "string", dir: "asc" },
    // Likewise "Models": `ran_with_providers` is provider names, not model
    // identities, and providers.length > 1 is not a valid fusion/solo test.
    // Keeping the honest label until a backend field exists.
    { key: "ran_with_providers", label: "Backends", sort: null },
    { key: "submitted_by", label: "Submitter", sort: "string", dir: "asc" },
    { key: "authors", label: "Authors", sort: "string", dir: "asc" },
    { key: "score", label: "Score", sort: "number", dir: "desc", cls: "num" },
    // WHY: total_questions remains on each spec's detail page rather than widening this table
    // and pushing the primary "Run Locally" action farther off-screen. Cost does not use the
    // generic numeric sort: it arrives as a fixed-precision string, and absent cost sorts last
    // rather than as zero. See compare() and leaderboard-logic.js.
    { key: "run_cost_usd", label: "Cost", sort: "cost", dir: "asc", cls: "num" },
    { key: "submitted_at", label: "Submitted", sort: "date", dir: "desc" },
    { key: "__run", label: "Run Locally", sort: null, cls: "col-run" },
  ];

  var state = { entries: [], benchmarkId: null, sortKey: "score", sortDir: "desc" };

  function compare(a, b, key, type, dir) {
    // Cost never reaches the generic numeric branch below. That branch is
    // `(av || 0) - (bv || 0)`, which coerces a null cost to 0 and would sort an unpriced row
    // as the cheapest on the board — the "a null cost never reads as zero" rule the whole
    // frontier rests on. compareCost also converts the fixed-6dp string before comparing, and
    // applies `dir` itself, so this returns straight out.
    if (type === "cost") return L.compareCost(a, b, dir);
    var av = a[key], bv = b[key], res = 0;
    if (type === "string") {
      res = String(av).localeCompare(String(bv));
    } else if (type === "bool") {
      res = (av === true ? 1 : 0) - (bv === true ? 1 : 0);
    } else if (type === "date") {
      res = new Date(av).getTime() - new Date(bv).getTime();
    } else { // number
      res = (av || 0) - (bv || 0);
    }
    return dir === "desc" ? -res : res;
  }

  function sortedEntries() {
    var col = COLUMNS.filter(function (c) { return c.key === state.sortKey; })[0];
    if (!col || !col.sort) return state.entries.slice();
    var copy = state.entries.slice();
    copy.sort(function (a, b) { return compare(a, b, state.sortKey, col.sort, state.sortDir); });
    return copy;
  }

  function renderHead(headNode) {
    P.clear(headNode);
    var tr = document.createElement("tr");
    COLUMNS.forEach(function (col) {
      var th = document.createElement("th");
      if (col.cls) th.className = col.cls;
      if (!col.sort) {
        th.textContent = col.label;
      } else {
        var active = col.key === state.sortKey;
        th.setAttribute("aria-sort", active ? (state.sortDir === "desc" ? "descending" : "ascending") : "none");
        var btn = P.el("button", "sort-button");
        btn.type = "button";
        btn.appendChild(document.createTextNode(col.label + " "));
        btn.appendChild(P.el("span", "arrow", active ? (state.sortDir === "desc" ? "▼" : "▲") : "↕"));
        btn.addEventListener("click", function () {
          if (state.sortKey === col.key) {
            state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
          } else {
            state.sortKey = col.key;
            state.sortDir = col.dir;
          }
          renderHead(headNode);
          renderBody(document.getElementById("leaderboard-body"));
        });
        th.appendChild(btn);
      }
      tr.appendChild(th);
    });
    headNode.appendChild(tr);
  }

  var L = window.SFLeaderboardLogic;

  // The widest score bar on screen. Deliberately the best score of ALL
  // entries, verified or not — the bar is a like-for-like visual comparison of
  // the rows present, so scaling it to the reproducible-only maximum would let
  // an unverified row overflow its own track.
  function bestScore(entries) {
    if (!entries.length) return null;
    return Math.max.apply(null, entries.map(function (e) { return e.score; }));
  }

  // Scores are benchmark-native, so a board with negative values needs its own floor;
  // barWidth shifts the origin to min(0, lowest).
  function lowestScore(entries) {
    if (!entries.length) return null;
    return Math.min.apply(null, entries.map(function (e) { return e.score; }));
  }

  // Render the mark cell on every row so the column exists structurally. The server decides
  // frontier membership; this function only renders that answer. Colour is never the only
  // carrier: the diamond shows the mark and the
  // sr-only text names it. The gold row background stays the SEPARATE highest-score
  // signal, so a row can carry one, both or neither.
  function renderMarkSlot(entry) {
    var td = P.el("td", "col-mark");
    if (!L.isParetoMarked(entry)) return td;
    var mark = P.el("span", "pareto-mark");
    mark.setAttribute("aria-hidden", "true");
    td.appendChild(mark);
    td.appendChild(
      P.el("span", "sr-only", "on the Pareto frontier: no submission has an equal-or-higher score at an equal-or-lower cost, with one strict improvement")
    );
    return td;
  }

  // The vendored .score-cell recipe: the number plus a proportional track. Its
  // documented markup is
  //   <span class="score-cell"><span class="num">84.3</span>
  //     <span class="score-track"><span class="score-fill" style="width:88%"></span></span></span>
  // The track is decoration — the adjacent number is the accessible value, so it
  // carries aria-hidden rather than duplicating the figure to a screen reader.
  //
  // The `.grad` fill variant animates and is reserved for the single
  // hero win in the design system, so plain `.score-fill` is used per row here.
  function renderScoreCell(score, barMin, barMax) {
    var td = P.el("td", "num");
    var cell = P.el("span", "score-cell");
    cell.appendChild(P.el("span", "num", P.formatScore(score)));
    var track = P.el("span", "score-track");
    track.setAttribute("aria-hidden", "true");
    var fill = P.el("span", "score-fill");
    fill.style.width = L.barWidth(score, barMin, barMax).toFixed(1).replace(/\.0$/, "") + "%";
    track.appendChild(fill);
    cell.appendChild(track);
    td.appendChild(cell);
    return td;
  }

  function renderBody(bodyNode) {
    P.clear(bodyNode);
    var barMax = bestScore(state.entries);
    var barMin = lowestScore(state.entries);
    sortedEntries().forEach(function (entry) {
      var tr = document.createElement("tr");
      // Gold marks the row with the highest score on screen, not a reproduction claim. The
      // accessible text below uses the same precise wording rather than promising verification.
      var isLeader = barMax !== null && entry.score === barMax;
      if (isLeader) tr.className = "sota";

      tr.appendChild(P.el("td", "num", entry.rank));
      tr.appendChild(renderMarkSlot(entry));

      var specTd = P.el("td", "cell-wrap");
      specTd.appendChild(P.link("mono", "spec.html?benchmark=" + encodeURIComponent(state.benchmarkId) + "&spec=" + encodeURIComponent(entry.spec_id), entry.spec_id));
      // Colour must not be the only carrier of the meaning — and the wording is
      // deliberately "highest score", not "state of the art": this row may be
      // unverified.
      if (isLeader) specTd.appendChild(P.el("span", "sr-only", " (highest score)"));
      tr.appendChild(specTd);

      tr.appendChild(P.el("td", null, P.formatProviders(entry.ran_with_providers)));
      tr.appendChild(P.el("td", null, P.formatSubmitter(entry.submitted_by)));
      tr.appendChild(P.el("td", null, P.formatAuthors(entry.authors)));
      tr.appendChild(renderScoreCell(entry.score, barMin, barMax));
      // WHY the title: the cell rounds to cents, but the frontier compares the full stored
      // Decimal — so two rows inside one cent render identically while only one is marked. The
      // exact figure has to be recoverable, or the board contradicts itself with nothing on the
      // page to explain it.
      var costTd = P.el("td", "num", L.formatCost(entry));
      if (L.costNumber(entry) !== null) costTd.title = "$" + entry.run_cost_usd;
      tr.appendChild(costTd);
      tr.appendChild(P.el("td", null, P.formatDate(entry.submitted_at)));

      var runTd = document.createElement("td");
      runTd.className = "col-run";
      // Guard like spec.js: a missing expression renders as absence, never as
      // a Copy button that would put "undefined" on the clipboard.
      if (entry.url4_expression) {
        runTd.appendChild(P.createCopyButton(entry.spec_id, entry.url4_expression, { compact: true }));
      } else {
        runTd.textContent = P.EM_DASH;
      }
      tr.appendChild(runTd);

      bodyNode.appendChild(tr);
    });
  }

  function renderSummary(entries) {
    var summaryNode = document.getElementById("leaderboard-summary");
    if (!summaryNode) return;
    if (!entries.length) {
      summaryNode.hidden = true;
      return;
    }

    var best = bestScore(entries);
    // Bare numbers: the .stats cell labels ("Specs shown") already carry the words.
    document.getElementById("summary-best").textContent = P.formatScore(best);
    document.getElementById("summary-specs").textContent = entries.length.toLocaleString();
    summaryNode.hidden = false;
  }

  // Show how much of this benchmark's score frontier is held by open-reproducible stacks
  // versus proprietary ones. Fetched and rendered
  // independently of the main leaderboard call — a failure here must not
  // block or error out the leaderboard itself, it's a supplementary stat.
  function renderFrontier(data) {
    var card = document.getElementById("summary-frontier-card");
    var node = document.getElementById("summary-frontier");
    if (!card || !node || !data) return;
    // WHY count on open_count/closed_count, not data.current: a benchmark with
    // imported Baselines but zero Score submissions yet has a real, meaningful
    // open_share (Baselines count toward the split) even though current is null
    // (Baselines never become the server-side trend holder). Gating on
    // current alone would silently hide the stat for every baseline-only benchmark.
    var total = (data.open_count || 0) + (data.closed_count || 0);
    if (total === 0) return;
    var pct = Math.round((data.open_share || 0) * 100);
    node.textContent = pct + "% open";
    node.title = data.current
      ? "Frontier currently held by a " + data.current.openness +
        " entry (" + data.current.label + ")"
      : "";
    // `.stats--two` lays out the two cards that are always visible. This optional card is the
    // third, so
    // the modifier must come off the moment it is shown, or the strip wraps it onto
    // its own row at >=621px. Removing it restores the vendored three-column layout;
    // the strip keeps two columns for as long as this card stays hidden.
    var strip = document.getElementById("leaderboard-summary");
    if (strip) strip.classList.remove("stats--two");
    card.hidden = false;
  }

  // Climb score bars (brand viz-a direction): one row per spec, the SOTA
  // entry carries the sota (gain) fill — same story color as tr.sota.
  // Purely visual: aria-hidden, the table is the accessible representation.
  //
  // The fill keys off the shared barWidth normalization, matching the table's
  // score cells — both mean "leading", neither claims reproduction. Raw
  // multiplying score by 100 would give negative boards an invalid CSS width.
  function renderClimb(entries) {
    var section = document.getElementById("leaderboard-climb-section");
    var node = document.getElementById("leaderboard-climb");
    if (!section || !node) return;
    if (!entries.length) {
      section.hidden = true;
      return;
    }
    var best = bestScore(entries);
    var floor = lowestScore(entries);
    P.clear(node);
    L.orderRows(entries)
      .forEach(function (entry) {
        var row = P.el("div", "row");
        row.appendChild(P.el("span", "lbl", entry.spec_id));
        var track = P.el("span", "track");
        var fill = P.el("span", "fill " + (entry.score === best ? "sota" : "base"));
        fill.style.width = L.barWidth(entry.score, floor, best).toFixed(1).replace(/\.0$/, "") + "%";
        track.appendChild(fill);
        row.appendChild(track);
        row.appendChild(P.el("span", "val", P.formatScore(entry.score)));
        node.appendChild(row);
      });
    section.hidden = false;
  }
  // The chart module owns modelling and SVG; this page owns only
  // lifecycle wiring. Keeping it separate holds benchmark.js below the repo's focused-file limit.
  function renderParetoChart(entries) {
    var section = document.getElementById("pareto-chart-section");
    var container = document.getElementById("pareto-chart");
    if (!section || !container || !window.SFParetoChart) return;
    window.SFParetoChart.render({
      section: section,
      container: container,
      meta: document.getElementById("pareto-chart-meta"),
      entries: entries,
      formatScore: P.formatScore,
      formatCost: L.formatCost,
    });
  }

  // Tab strip renders across all pages regardless of whether the current
  // `id` is valid — even a 404/missing-id state should let the reader jump
  // to a real benchmark, not dead-end.
  function initTabStrip(activeId) {
    var tabsNode = document.getElementById("benchmark-tabs");
    if (!tabsNode) return;
    P.fetchJson("/v1/benchmarks").then(
      function (data) { P.renderTabStrip(tabsNode, (data && data.benchmarks) || [], activeId); },
      function () { /* tab strip is a nav convenience, not load-bearing — fail silent */ }
    );
  }

  // An unknown or missing benchmark id must not be a dead end: the status
  // region gets a real link back to the catalog, not just text.
  function showNotFound(statusNode, message) {
    P.setStatus(statusNode, "error", "");
    statusNode.appendChild(document.createTextNode(message + " "));
    statusNode.appendChild(P.link(null, "index.html", "Return to the benchmark list."));
  }

  function init() {
    var statusNode = document.getElementById("leaderboard-status");
    var wrap = document.getElementById("leaderboard-wrap");
    var legend = document.getElementById("leaderboard-legend");
    var legendPareto = document.getElementById("legend-pareto");
    var nameNode = document.getElementById("benchmark-name");
    var descNode = document.getElementById("benchmark-desc");

    var id;
    try {
      id = P.requireParam("id");
    } catch (e) {
      showNotFound(statusNode, "No benchmark specified.");
      initTabStrip(null);
      return;
    }
    state.benchmarkId = id;
    initTabStrip(id);

    P.showLoading(statusNode, "Loading leaderboard…");
    wrap.hidden = true;
    legend.hidden = true;

    P.fetchJson("/v1/leaderboard/" + encodeURIComponent(id) + "?top=50").then(
      function (data) {
        var b = data && data.benchmark;
        if (b) {
          nameNode.textContent = b.display_name || b.id;
          descNode.textContent = b.description || "";
          document.title = (b.display_name || b.id) + " — screamingface";
        }
        state.entries = (data && data.entries) || [];
        if (state.entries.length === 0) {
          // The table shell renders on the zero-entry path too, so a benchmark with no
          // submissions still shows the column structure. renderSummary/renderClimb
          // hide themselves when passed an empty list, so the reader gets the
          // column headers plus the empty-state line and nothing misleading.
          renderSummary(state.entries);
          renderClimb(state.entries);
          renderParetoChart(state.entries);
          renderHead(document.getElementById("leaderboard-head"));
          P.clear(document.getElementById("leaderboard-body"));
          P.showEmpty(statusNode, "No submissions yet. Be the first.");
          wrap.hidden = false;
          // No rows at all: the key would point at nothing.
          legend.hidden = true;
          return;
        }
        renderSummary(state.entries);
        renderClimb(state.entries);
        renderParetoChart(state.entries);
        renderHead(document.getElementById("leaderboard-head"));
        renderBody(document.getElementById("leaderboard-body"));
        P.setStatus(statusNode, null);
        wrap.hidden = false;
        // The frontier key appears only when a row actually carries the mark. If frontier
        // publication is unavailable, or every cost is null, nothing is
        // marked — and a key for a symbol that appears nowhere reads as 'no submission
        // here is good value', which is the opposite of what the gate is saying.
        legendPareto.hidden = !state.entries.some(L.isParetoMarked);
        legend.hidden = false;
      },
      function (err) {
        if (err && err.status === 404) {
          showNotFound(statusNode, "Benchmark not found.");
          return;
        }
        P.showError(statusNode, P.describeError(err, {
          generic: "Could not load leaderboard — try again later.",
        }));
      }
    );

    // Independent of the fetch above: a failure here just leaves the card
    // hidden (its default state in the markup), never surfaces an error.
    P.fetchJson("/v1/leaderboard/" + encodeURIComponent(id) + "/frontier").then(
      renderFrontier,
      function () {}
    );
  }

  P.ready(init);
})(window.ScorePortal);
