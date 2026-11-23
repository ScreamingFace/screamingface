/* ScreamingFace Leaderboard Portal — benchmark (top-N) page.
 *
 * Reads the board id from /benchmarks/<id>/ or ?id=<id>, fetches /v1/leaderboard/{id}, and renders a
 * client-side sortable table. Default sort is score DESC. Community top-N results
 * and imported baselines are merged before selecting the displayed top N. Ranks
 * describe that score ordering and stay fixed when another column is sorted.
 * The backend still selects the best submission per spec; imported references
 * supply no recipe and do not participate in cost-based frontier claims.
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
    // WHY the header says "Submission": visitors read each row as one submission, so the
    // visible word is "Submission" while the payload key stays `spec_id`. The SOTA mark
    // slot leads this cell, which is the "mark leads the name" part.
    { key: "spec_id", label: "Submission", sort: "string", dir: "asc" },
    // Likewise "Models": `ran_with_providers` is provider names, not model
    // identities, and providers.length > 1 is not a valid fusion/solo test,
    // so the header says what the cell holds.
    { key: "ran_with_providers", label: "Backends", sort: null },
    { key: "authors", label: "Authors", sort: "string", dir: "asc" },
    { key: "score", label: "Score", sort: "number", dir: "desc", cls: "num" },
    // WHY: total_questions remains on each spec's detail page rather than widening this table
    // and pushing the primary "Run Locally" action farther off-screen. Cost does not use the
    // generic numeric sort: it arrives as a fixed-precision string, and absent cost sorts last
    // rather than as zero. See compare() and leaderboard-logic.js.
    { key: "run_cost_usd", label: "Cost", sort: "cost", dir: "asc", cls: "num" },
    { key: "submitted_at", label: "Added", sort: "date", dir: "desc" },
    { key: "__run", label: "Run Locally", sort: null, cls: "col-run" },
  ];

  var state = { entries: [], rows: [], benchmarkId: null, sortKey: "score", sortDir: "desc" };

  // The Reproduce button's switch, on since the SDK release whose `evaluate(pinned_cache=...)` runs
  // the copied snippet. WHY a constant and not a server setting: the page cannot read server
  // settings, and this flips exactly once.
  var SHOW_REPRODUCE_BUTTON = true;
  var REPRODUCE_HOVER = "Replays recorded answers and checks the published score; requires a replay-capable Engine and Gateway";

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
    if (!col || !col.sort) return state.rows.slice();
    var copy = state.rows.slice();
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

  // The SFDS `.status` recipe, a square plus the lowercase weight label. Deliberately NOT
  // `.status.on`: that state is success green, and green means verified in SFDS, which this is
  // not. `.status--open` keeps the square neutral ink at full tone; `.status--closed` keeps the
  // recipe's muted square with its word at --ink-2, which passes WCAG AA where the whisper
  // off-state did not; unknown is a faint dash with the reason in its title.
  function renderOpenness(entry) {
    var label = L.opennessLabel(entry);
    var line = P.el("span", "weights-line");
    if (label.tone === "unknown") {
      var unknown = P.el("span", "faint", label.text);
      unknown.title = label.title;
      line.appendChild(unknown);
      line.appendChild(P.el("span", "sr-only", " (" + label.title + ")"));
      return line;
    }
    var status = P.el("span", label.tone === "open" ? "status status--open" : "status status--closed");
    var square = P.el("span", "sq");
    square.setAttribute("aria-hidden", "true");
    status.appendChild(square);
    status.appendChild(document.createTextNode(label.text));
    line.appendChild(status);
    return line;
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

  // The Run column: Copy url4 for reusing the recipe live, and, for a fully captured run when the
  // switch is on, Reproduce stacked under it, copying the replay snippet. Same button recipe and
  // the same copied/failed feedback for both; no new colour.
  function renderRunCell(entry, showReproduce) {
    var runTd = document.createElement("td");
    runTd.className = "col-run";
    // Guard like spec.js: a missing expression renders as absence, never as
    // a Copy button that would put "undefined" on the clipboard.
    if (!entry.url4_expression) {
      runTd.textContent = P.EM_DASH;
      return runTd;
    }
    var copy = P.createCopyButton(entry.spec_id, entry.url4_expression, { compact: true });
    var cache = L.reproduceCache(entry, showReproduce);
    if (cache === null) {
      runTd.appendChild(copy);
      return runTd;
    }
    var stack = P.el("div", "run-actions");
    stack.appendChild(copy);
    stack.appendChild(P.createCopyButton(entry.spec_id, L.reproduceSnippet(cache), {
      compact: true,
      label: "Reproduce",
      // The accessible name starts with the visible label (WCAG 2.5.3), so "click Reproduce" works.
      ariaLabel: "Reproduce " + entry.spec_id + ": copy the replay code",
      title: REPRODUCE_HOVER,
    }));
    runTd.appendChild(stack);
    return runTd;
  }

  function renderBody(bodyNode) {
    P.clear(bodyNode);
    var barMax = bestScore(state.rows);
    var barMin = lowestScore(state.rows);
    sortedEntries().forEach(function (entry) {
      if (entry.external) {
        bodyNode.appendChild(window.SFExternalResults.renderRow(entry,
          renderScoreCell(entry.score, barMin, barMax)));
        return;
      }
      var tr = document.createElement("tr");
      // Gold marks the row with the highest score on screen, not a reproduction claim. The
      // accessible text below uses the same precise wording rather than promising verification.
      var isLeader = barMax !== null && entry.score === barMax;
      if (isLeader) tr.className = "sota";

      tr.appendChild(P.el("td", "num", entry.rank));
      tr.appendChild(renderMarkSlot(entry));

      var specTd = P.el("td", "cell-wrap");
      specTd.appendChild(P.link("mono", P.pageHref("spec.html?benchmark=" + encodeURIComponent(state.benchmarkId) + "&spec=" + encodeURIComponent(entry.spec_id)), entry.spec_id));
      // Colour must not be the only carrier of the meaning — and the wording is
      // deliberately "highest score", not "state of the art": this row may be
      // unverified.
      if (isLeader) specTd.appendChild(P.el("span", "sr-only", " (highest score)"));
      // The Pareto chart's circle/square/triangle composition-type encoding stays
      // `aria-hidden` — the chart is a visual summary and the table is the
      // documented accessible data source, so the row that already names this submission is
      // where a screen reader has to learn the same fact the chart's shape gives a sighted
      // reader. Always present (never only for fusion/unknown): "single model" is itself an
      // answer, not the absence of one, so omitting it on the common case would read as missing
      // data rather than as a stated verdict.
      specTd.appendChild(
        P.el("span", "sr-only", " (" + L.candidateKindLabel(entry).toLowerCase() + ")")
      );
      tr.appendChild(specTd);

      // The entry's open/closed verdict rides in this cell as a second line. With the
      // Pareto mark it answers "which entries win the open frontier". Not its own column: the
      // table fits its container exactly, and another column would push "Run locally", the
      // board's primary action, behind a horizontal scroll. This cell is also where a reader
      // looks for what an entry runs on.
      var backendsTd = P.el("td", null, P.formatProviders(entry.ran_with_providers));
      backendsTd.appendChild(renderOpenness(entry));
      tr.appendChild(backendsTd);
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

      tr.appendChild(renderRunCell(entry, SHOW_REPRODUCE_BUTTON));

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
    // Bare numbers: the .stats cell labels ("Results shown") already carry the words.
    document.getElementById("summary-best").textContent = P.formatScore(best);
    document.getElementById("summary-specs").textContent = entries.length.toLocaleString();
    summaryNode.hidden = false;
  }

  // Show how much of this benchmark's cost/score Pareto frontier (the rows the table marks)
  // declares only open-weights models. Fetched and rendered
  // independently of the main leaderboard call — a failure here must not
  // block or error out the leaderboard itself, it's a supplementary stat.
  function renderFrontier(data) {
    var card = document.getElementById("summary-frontier-card");
    var node = document.getElementById("summary-frontier");
    if (!card || !node || !data) return;
    // The decision of what to claim lives in leaderboard-logic.js, where it is
    // tested; this only paints it. A null summary leaves the card hidden.
    var summary = L.frontierSummary(data);
    if (!summary) return;
    node.textContent = summary.text;
    node.title = summary.title;
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
        var fill = P.el("span", "fill " + (entry.score === best && !entry.external ? "sota" : "base"));
        fill.style.width = L.barWidth(entry.score, floor, best).toFixed(1).replace(/\.0$/, "") + "%";
        track.appendChild(fill);
        row.appendChild(track);
        row.appendChild(P.el("span", "val", P.formatScore(entry.score)));
        node.appendChild(row);
      });
    section.hidden = false;
  }
  // The chart module owns modelling and SVG; this page owns only
  // lifecycle wiring, keeping chart concerns separate from page rendering.
  // WHY guarded: the chart is a visual summary of the table, never a gate on it. Any error
  // while drawing (an unforeseen score range, a missing browser API) hides the chart and
  // leaves the table, summary and legend exactly as they would be without it.
  function renderParetoChart(entries) {
    var section = document.getElementById("pareto-chart-section");
    var container = document.getElementById("pareto-chart");
    if (!section || !container || !window.SFParetoChart) return;
    var meta = document.getElementById("pareto-chart-meta");
    try {
      window.SFParetoChart.render({
        section: section,
        container: container,
        meta: meta,
        entries: entries,
        formatScore: P.formatScore,
        formatCost: L.formatCost,
      });
    } catch (err) {
      P.clear(container);
      if (meta) meta.textContent = "";
      section.hidden = true;
      if (window.console && console.error) console.error("Pareto chart not drawn:", err);
    }
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
    statusNode.appendChild(P.link(null, P.pageHref("index.html"), "Return to the benchmark list."));
  }

  // The breadcrumb names the benchmark being shown. With no benchmark (missing id, 404) the
  // crumb and its separator stay hidden rather than showing a stale or misleading label.
  // Fold a long benchmark description to three lines behind a "Show more" button, and return the
  // function that re-checks the fold (call it whenever the description text changes).
  //
  // Stage 1 — clamp first: the three-line clamp must be on before measuring, because an unclamped
  //   paragraph is always exactly as tall as its text and so never "overflows".
  // Stage 2 — measure: the text overflows when its full height (scrollHeight) is more than the
  //   clamped box (clientHeight). One pixel of slack absorbs sub-pixel rounding.
  // Stage 3 — apply: descriptionFoldState (leaderboard-logic.js) turns "overflows" and "expanded"
  //   into the clamp class, the button's visibility, its label and aria-expanded.
  //
  // The clamp lives in a class this function adds, never in the markup, so a page whose scripts
  // did not run shows the whole description rather than three lines nobody can open.
  var DESCRIPTION_CLAMP_CLASS = "is-clamped";
  var OVERFLOW_SLACK_PX = 1;
  function initDescriptionFold(fold, desc, button) {
    if (!fold || !desc || !button) return function () {};
    var expanded = false;
    function sync() {
      // Stage 1
      if (!expanded) fold.classList.add(DESCRIPTION_CLAMP_CLASS);
      // Stage 2
      var overflows = desc.scrollHeight > desc.clientHeight + OVERFLOW_SLACK_PX;
      // Stage 3
      var state = L.descriptionFoldState(overflows, expanded);
      if (state.clamped) fold.classList.add(DESCRIPTION_CLAMP_CLASS);
      else fold.classList.remove(DESCRIPTION_CLAMP_CLASS);
      button.hidden = state.buttonHidden;
      button.textContent = state.label;
      button.setAttribute("aria-expanded", String(state.expanded));
    }
    button.addEventListener("click", function () {
      expanded = !expanded;
      sync();
    });
    // A narrower window wraps the text onto more lines, so a description that fitted can start to
    // overflow (and the reverse). An open description is left alone: it has nothing to measure.
    // A drag-resize fires many events per second; coalesce them to one sync per frame instead of
    // re-measuring (layout read + DOM write) on every single event.
    var resizePending = false;
    if (window.addEventListener) {
      window.addEventListener("resize", function () {
        if (expanded || resizePending) return;
        if (!window.requestAnimationFrame) {
          sync();
          return;
        }
        resizePending = true;
        window.requestAnimationFrame(function () {
          resizePending = false;
          sync();
        });
      });
    }
    return sync;
  }

  function setBenchmarkCrumb(crumbNode, name) {
    var nav = crumbNode.parentNode;
    crumbNode.textContent = name;
    nav.hidden = !name;
    nav.previousElementSibling.hidden = !name;
  }

  function init() {
    var statusNode = document.getElementById("leaderboard-status");
    var wrap = document.getElementById("leaderboard-wrap");
    var legend = document.getElementById("leaderboard-legend");
    var legendPareto = document.getElementById("legend-pareto");
    var nameNode = document.getElementById("benchmark-name");
    var descNode = document.getElementById("benchmark-desc");
    var crumbNode = document.getElementById("crumb-benchmark");
    var syncDescriptionFold = initDescriptionFold(
      document.getElementById("benchmark-desc-fold"),
      descNode,
      document.getElementById("benchmark-desc-toggle")
    );
    // At /benchmarks/<id>/ the server already wrote the description, so fold it now: waiting for
    // the leaderboard answer shows the whole paragraph while it loads, then collapses it under the
    // reader (PR #1983 review). The fetch below syncs again when it replaces the text.
    syncDescriptionFold();

    var id = P.boardId();
    if (!id) {
      showNotFound(statusNode, "No benchmark specified.");
      initTabStrip(null);
      return;
    }
    state.benchmarkId = id;
    setBenchmarkCrumb(crumbNode, id);
    initTabStrip(id);

    var R = window.SFRevisionSelector;
    var revisions = [];

    // Each load takes a number; a response that arrives after a newer load started is dropped, so a
    // slow answer for an earlier choice can never paint over the revision now selected.
    var generation = 0;
    // The generation whose board is on screen, so the status line can be redone when the revision
    // list arrives after the board.
    var loaded = 0;
    // Set when the URL named a revision and the revision list could not be read (or the board is
    // private, where the list is never served): the board then says which revision it shows.
    var listUnavailable = false;
    var hasRevision = false;
    var hasSubmissions = false;

    // The line above the table, decided from community runs only: imported reference rows appear
    // under every revision, so they never stand in for this revision's own results.
    function showBoardStatus() {
      if (hasSubmissions) {
        P.setStatus(statusNode, null);
        return;
      }
      // Versioned boards count their own submissions, independently of imported references.
      // Unversioned boards retain their ordinary external-only table presentation.
      if (hasRevision || state.rows.length === 0) showEmptyBoard(statusNode);
      else P.setStatus(statusNode, null);
    }

    // Everything a board fills in, back to its state before any board loaded. A switch, or a switch
    // that fails, must not leave the previous revision's numbers under the new selection.
    function clearBoard() {
      wrap.hidden = true;
      legend.hidden = true;
      var summary = document.getElementById("leaderboard-summary");
      if (summary) {
        summary.hidden = true;
        // The strip is two columns until a frontier card is shown (see renderFrontier).
        summary.classList.add("stats--two");
      }
      ["summary-frontier-card", "leaderboard-climb-section", "pareto-chart-section", "external-comparison"]
        .forEach(function (nodeId) {
          var node = document.getElementById(nodeId);
          if (node) node.hidden = true;
        });
    }

    // `?revision=` scopes the board and the frontier; absent means Latest, exactly as
    // before. Every switch re-runs this load, so it resets what a previous revision left behind.
    function load(revision) {
      var mine = ++generation;
      var scope = revision ? "&revision=" + encodeURIComponent(revision) : "";
      P.showLoading(statusNode, "Loading leaderboard…");
      clearBoard();
      showScopeNote();

      P.fetchJson("/v1/leaderboard/" + encodeURIComponent(id) + "?top=50" + scope).then(
        function (data) {
          if (mine !== generation) return;
          var b = data && data.benchmark;
          hasRevision = !!(b && b.revision);
          if (listUnavailable && revision && R) {
            // No selector to show the scope, so a line does; on a private board the URL's revision
            // was ignored, and goes.
            var unlisted = R.unlistedScopeNotice(revision, b);
            if (unlisted) {
              showRevisionNotice(unlisted.text);
              if (unlisted.clearRequest) replaceSearch(null);
            }
          }
          if (b) {
            var name = b.display_name || b.id;
            nameNode.textContent = name;
            setBenchmarkCrumb(crumbNode, name);
            descNode.textContent = b.description || "";
            syncDescriptionFold();
            // At /benchmarks/<id>/ the server already wrote this board's title, with the words a
            // search result shows. Only the shared benchmark.html still needs one from here.
            if (!P.atBoardAddress()) document.title = name + " — screamingface";
          }
          state.entries = (data && data.entries) || [];
          // A populated cohort stays populated even when imports displace every visible row.
          hasSubmissions = state.entries.length > 0;
          // Keep the fetched community points even when imports displace table rows.
          var chartEntries = state.entries;
          state.rows = window.SFExternalResults
            ? window.SFExternalResults.selectRows(state.entries, data && data.baselines, 50)
            : state.entries;
          if (window.SFExternalResults) {
            window.SFExternalResults.renderComparisonNotes(
              document.getElementById("external-comparison"), state.rows
            );
          }
          // Cost-based comparisons still require recorded runs, not imported reference numbers.
          state.entries = state.rows.filter(function (row) { return !row.external; });
          if (state.rows.length === 0) {
            // The table shell renders on the zero-entry path too, so a benchmark with no
            // submissions still shows the column structure. renderSummary/renderClimb
            // hide themselves when passed an empty list, so the reader gets the
            // column headers plus the empty-state line and nothing misleading.
            renderSummary(state.rows);
            renderClimb(state.rows);
            renderHead(document.getElementById("leaderboard-head"));
            P.clear(document.getElementById("leaderboard-body"));
            loaded = mine;
            showBoardStatus();
            wrap.hidden = false;
            // No rows at all: the key would point at nothing.
            legend.hidden = true;
            renderParetoChart(chartEntries);
            return;
          }
          renderSummary(state.rows);
          renderClimb(state.rows);
          renderHead(document.getElementById("leaderboard-head"));
          renderBody(document.getElementById("leaderboard-body"));
          loaded = mine;
          showBoardStatus();
          wrap.hidden = false;
          // The frontier key appears only when a row actually carries the mark. If frontier
          // publication is unavailable, or every cost is null, nothing is
          // marked — and a key for a symbol that appears nowhere reads as 'no submission
          // here is good value', which is the opposite of what the gate is saying.
          legendPareto.hidden = !state.entries.some(L.isParetoMarked);
          legend.hidden = state.entries.length === 0;
          var leaderKey = document.getElementById("legend-highest");
          if (leaderKey) leaderKey.hidden = !state.entries.some(function (row) {
            return row.score === bestScore(state.rows);
          });
          // Last, after the table is visible: the chart can only ever add to the page.
          renderParetoChart(chartEntries);
        },
        function (err) {
          if (mine !== generation) return;
          if (revision && R && R.isRevisionNotFound(err)) {
            // The revision list was unavailable and the URL named an id the board does not have:
            // fall back to Latest and say so, rather than calling the benchmark missing.
            showRevisionNotice(R.notFoundNotice(revision));
            replaceSearch(null);
            // A listed revision can still vanish between the two reads; the dropdown follows the board.
            var select = document.getElementById("revision-select");
            var latestRow = currentSelection();
            if (select && latestRow) select.value = latestRow.revision;
            load(null);
            return;
          }
          if (err && err.status === 404) {
            showRevisionNotice("");
            setBenchmarkCrumb(crumbNode, "");
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
      P.fetchJson(
        "/v1/leaderboard/" + encodeURIComponent(id) + "/frontier" + (scope ? "?" + scope.slice(1) : "")
      ).then(
        function (data) {
          if (mine === generation) renderFrontier(data);
        },
        function () {}
      );
    }

    // An empty Latest after a bump points to the earlier revision's results
    // instead of switching to it silently; any other empty board keeps the original line.
    function showEmptyBoard(node) {
      if (showRevisionPointer(node)) return;
      P.showEmpty(node, R ? R.emptyBoardText(currentSelection()) : "No submissions yet. Be the first.");
    }

    // Says when the shown revision's Case count was inferred from its runs rather than recorded.
    function showScopeNote() {
      var note = document.getElementById("revision-scope-note");
      if (!note) return;
      var text = R ? R.scopeNote(currentSelection()) : null;
      note.textContent = text || "";
      note.hidden = !text;
    }

    // True when Latest has no community runs and an earlier revision has some: the line and its
    // button are shown in `node`.
    function showRevisionPointer(node) {
      var pointer = R ? R.emptyLatestPointer(revisions, currentSelection()) : null;
      if (!pointer) return false;
      P.showEmpty(node, pointer.text + " ");
      var button = P.el("button", "revision-pointer", "Show them");
      button.type = "button";
      button.addEventListener("click", function () {
        choose(pointer.revision);
        // The button disappears with the load it starts; keep keyboard focus on the selector.
        var select = document.getElementById("revision-select");
        if (select && !select.hidden) select.focus();
      });
      node.appendChild(button);
      return true;
    }

    function currentSelection() {
      var requested = R.requestedRevision(window.location.search);
      return R.resolveSelection(revisions, requested).selected;
    }

    function replaceSearch(row) {
      if (!window.history || !window.history.replaceState) return;
      var search = row ? R.searchWith(window.location.search, row) : (function () {
        var params = new URLSearchParams(window.location.search);
        params.delete("revision");
        var text = params.toString();
        return text ? "?" + text : "";
      })();
      window.history.replaceState(null, "", window.location.pathname + search + window.location.hash);
    }

    function showRevisionNotice(text) {
      var notice = document.getElementById("revision-notice");
      if (!notice) return;
      notice.textContent = text;
      notice.hidden = !text;
    }

    function choose(row) {
      var select = document.getElementById("revision-select");
      if (select) select.value = row.revision;
      replaceSearch(row);
      showRevisionNotice("");
      load(row.current ? null : row.revision);
    }

    // The selector sits under the title and scopes everything below it.
    function renderRevisionSelector(selected) {
      var box = document.getElementById("revision-selector");
      var select = document.getElementById("revision-select");
      var plain = document.getElementById("revision-static");
      if (!box || !select || !plain || !revisions.length) return;
      if (revisions.length === 1) {
        plain.textContent = R.staticLabel(revisions[0]);
        plain.hidden = false;
        select.hidden = true;
      } else {
        P.clear(select);
        revisions.forEach(function (row, index) {
          var option = P.el("option", null, R.optionLabel(row, index));
          option.value = row.revision;
          select.appendChild(option);
        });
        select.value = selected.revision;
        select.onchange = function () {
          for (var i = 0; i < revisions.length; i++) {
            if (revisions[i].revision === select.value) choose(revisions[i]);
          }
        };
        select.hidden = false;
        plain.hidden = true;
      }
      box.hidden = false;
    }

    if (!R) {
      load(null);
      return;
    }
    var revisionsUrl = "/v1/leaderboard/" + encodeURIComponent(id) + "/revisions";
    if (!R.requestedRevision(window.location.search)) {
      // No revision in the URL means Latest, so the board need not wait for the list. The list
      // adds the selector when it arrives, and redoes the status line, which may point back to an
      // earlier revision's runs.
      load(null);
      P.fetchJson(revisionsUrl).then(
        function (data) {
          revisions = (data && data.revisions) || [];
          var selected = R.resolveSelection(revisions, null).selected;
          if (selected) renderRevisionSelector(selected);
          showScopeNote();
          if (loaded === generation) showBoardStatus();
        },
        function () {}
      );
      return;
    }
    // A revision in the URL is checked against the list before the board loads. If the list cannot
    // be read, the board still loads, scoped by the URL alone.
    P.fetchJson(revisionsUrl).then(
      function (data) {
        revisions = (data && data.revisions) || [];
        var requested = R.requestedRevision(window.location.search);
        var resolution = R.resolveSelection(revisions, requested);
        if (resolution.notFound) {
          showRevisionNotice(R.notFoundNotice(requested));
          replaceSearch(null);
        }
        if (resolution.selected) renderRevisionSelector(resolution.selected);
        // Explicit links stay pinned even when this list calls their revision current:
        // the benchmark may move between the list read and the board/frontier reads.
        load(resolution.notFound ? null : requested);
      },
      function () {
        listUnavailable = true;
        load(R.requestedRevision(window.location.search));
      }
    );
  }

  // Read by the portal's tests: the switch's shipped value, the Run cell for either setting, and
  // the description fold.
  window.SFBenchmarkPage = {
    SHOW_REPRODUCE_BUTTON: SHOW_REPRODUCE_BUTTON,
    renderRunCell: renderRunCell,
    initDescriptionFold: initDescriptionFold,
  };

  P.ready(init);
})(window.ScorePortal);
