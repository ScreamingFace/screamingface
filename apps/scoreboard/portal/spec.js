/* ScreamingFace Leaderboard Portal — spec history page.
 *
 * Reads ?benchmark=<id>&spec=<spec_id>. The history endpoint deliberately
 * omits url4_expression, so the top "Run Locally" link is built from the most
 * recent submission's score detail via GET /v1/public/scores/{submissions[0].id}
 * (submissions are newest-first). That id is the same Score UUID the scores
 * route accepts. `/v1/scores/*` is behind Cloudflare Access in production, so an
 * anonymous page must not call it. This link intentionally uses the newest
 * submission, which may differ from the best-per-spec url4 shown on the
 * leaderboard row.
 */
(function (P) {
  "use strict";

  // Every run stays listed, with the revision it was graded under. An id the board lists
  // links to that revision's leaderboard; any other id (one its client sent but the board never
  // had, or every id when the list is unavailable) is plain text. Rows under an earlier revision
  // are dimmed.
  function revisionCell(s, benchmarkId, revisions) {
    var td = P.el("td", "mono", "");
    var revision = s.benchmark_revision;
    if (!revision) {
      td.textContent = "—";
      return td;
    }
    var short = String(revision).slice(0, 8);
    var listed = window.SFRevisionSelector
      ? window.SFRevisionSelector.listedRevision(revisions, revision)
      : null;
    if (!listed) {
      td.textContent = short;
      return td;
    }
    // The board's own address in whichever form this page is served at, always pinned to the row's
    // revision: a link copied today must open the same grading after the next bump. Only choosing
    // Latest in the board's own selector drops the parameter.
    var target = new URL(P.boardHref(benchmarkId), window.location.href);
    target.searchParams.set("revision", revision);
    td.appendChild(P.link(null, target.href, short));
    if (listed.current) td.appendChild(P.el("span", "revision-tag", "latest"));
    return td;
  }

  function historyRow(s, benchmarkId, revisions) {
    var tr = document.createElement("tr");
    // Dimmed only when the board lists the run's revision as an earlier one; an id the board never
    // listed is not known to be older.
    var listed = window.SFRevisionSelector && s.benchmark_revision
      ? window.SFRevisionSelector.listedRevision(revisions, s.benchmark_revision)
      : null;
    if (listed && !listed.current) tr.className = "revision-older";
    tr.appendChild(P.el("td", null, P.formatDate(s.submitted_at)));
    tr.appendChild(revisionCell(s, benchmarkId, revisions));
    tr.appendChild(P.el("td", "cell-wrap", P.formatSubmitter(s.submitted_by)));
    var authorsTd = P.el("td", "cell-wrap");
    authorsTd.appendChild(P.formatAuthors(s.authors, s.authors_metadata));
    tr.appendChild(authorsTd);
    tr.appendChild(P.el("td", "num", P.formatScore(s.score)));
    tr.appendChild(P.el("td", "num", P.formatQuestions(s.total_questions)));
    return tr;
  }

  // Best-effort: resolve the benchmark's display name from /v1/benchmarks.
  // Falls back to the raw id if the list cannot be loaded or has no match.
  function resolveBenchmarkName(benchmarkId) {
    return P.fetchJson("/v1/benchmarks").then(
      function (data) {
        var list = (data && data.benchmarks) || [];
        var match = list.filter(function (b) { return b.id === benchmarkId; })[0];
        return match ? (match.display_name || match.id) : benchmarkId;
      },
      function () { return benchmarkId; }
    );
  }

  // The history rows carry no paper link, so it comes from the same score
  // detail the run link uses (the newest submission). Nothing is added when there is no safe link.
  function renderPaperLink(contentNode, score) {
    var anchor = P.paperLink(score && score.paper_url);
    if (anchor !== null) {
      var line = P.el("p", "meta mono", "Paper: ");
      line.appendChild(anchor);
      contentNode.insertBefore(line, contentNode.querySelector("h2"));
    }
  }

  // The metadata edit time (E14 Q24) comes from the same detail and is shown on its own line,
  // so it also appears when the edit changed only the authors and there is no paper link.
  function renderMetadataEdited(contentNode, score) {
    if (score && score.metadata_updated_at) {
      contentNode.insertBefore(
        P.el("p", "meta mono", "Metadata edited " + P.formatDate(score.metadata_updated_at)),
        contentNode.querySelector("h2")
      );
    }
  }

  function renderRunLink(contentNode, regionNode, specId, latestId) {
    P.fetchJson("/v1/public/scores/" + encodeURIComponent(latestId)).then(
      function (score) {
        renderPaperLink(contentNode, score);
        renderMetadataEdited(contentNode, score);
        if (score && score.url4_expression) {
          P.clear(regionNode);
          regionNode.appendChild(P.createCopyButton(specId, score.url4_expression));
          regionNode.hidden = false;
        } else {
          regionNode.hidden = true;
        }
      },
      function () {
        // Hide the button and show a quiet note rather than a hard error.
        P.clear(regionNode);
        regionNode.appendChild(P.el("p", "quiet", "Run link unavailable for the latest run."));
        regionNode.hidden = false;
      }
    );
  }

  function init() {
    var statusNode = document.getElementById("spec-status");
    var contentNode = document.getElementById("spec-content");
    var specIdNode = document.getElementById("spec-id");
    var benchNode = document.getElementById("spec-benchmark");
    var backLink = document.getElementById("back-link");

    var benchmarkId, specId;
    try {
      benchmarkId = P.requireParam("benchmark");
      specId = P.requireParam("spec");
    } catch (e) {
      P.setStatus(statusNode, "error", "");
      statusNode.appendChild(document.createTextNode("Missing benchmark or submission. "));
      statusNode.appendChild(P.link(null, "index.html", "Return to the benchmark list."));
      return;
    }

    // The masthead and the breadcrumb name the same benchmark: set them together.
    function setBenchmarkName(name) {
      benchNode.textContent = name;
      backLink.textContent = name;
      backLink.hidden = false;
    }

    specIdNode.textContent = specId;
    backLink.setAttribute("href", P.boardHref(benchmarkId));
    setBenchmarkName(benchmarkId);
    document.title = specId + " — screamingface";

    P.showLoading(statusNode, "Loading submission history…");
    contentNode.hidden = true;

    resolveBenchmarkName(benchmarkId).then(setBenchmarkName);

    // The board's revisions come from /revisions (the history response itself is unchanged).
    // Best-effort: without them the column still shows each run's revision, unlinked and untagged.
    var boardRevisions = P.fetchJson(
      "/v1/leaderboard/" + encodeURIComponent(benchmarkId) + "/revisions"
    ).then(
      function (data) { return (data && data.revisions) || []; },
      function () { return []; }
    );

    P.fetchJson("/v1/leaderboard/" + encodeURIComponent(benchmarkId) + "/" + encodeURIComponent(specId) + "/history?limit=20").then(
      function (data) {
        var submissions = (data && data.submissions) || [];
        if (submissions.length === 0) {
          P.showEmpty(statusNode, "No runs of this submission yet.");
          return;
        }

        // Scores under different revisions are not comparable: the best score covers one revision,
        // and reads "—" while no single revision can be named. The card stays, so the strip keeps
        // its three columns.
        function renderBest(revisions) {
          var label = document.getElementById("best-score-label");
          var best = window.SFRevisionSelector
            ? window.SFRevisionSelector.historyBest(submissions, revisions)
            : { score: Math.max.apply(null, submissions.map(function (s) { return s.score; })), label: "Best score" };
          if (label) label.textContent = best ? best.label : "Best score";
          document.getElementById("best-score").textContent = best ? P.formatScore(best.score) : "—";
        }
        // Bare number: the .stats cell label ("Runs") carries the word.
        document.getElementById("submission-count").textContent = submissions.length.toLocaleString();

        var body = document.getElementById("history-body");
        function renderRows(revisions) {
          P.clear(body);
          submissions.forEach(function (s) { body.appendChild(historyRow(s, benchmarkId, revisions)); });
        }
        // The table never waits for the revision list: it draws now, unlinked, and gains the links,
        // tag and dimming when the list arrives.
        renderRows([]);
        renderBest([]);
        boardRevisions.then(function (revisions) {
          renderRows(revisions);
          renderBest(revisions);
        });

        P.setStatus(statusNode, null);
        contentNode.hidden = false;

        // Newest submission is submissions[0] (backend orders newest-first).
        renderRunLink(contentNode, document.getElementById("run-region"), specId, submissions[0].id);
      },
      function (err) {
        P.showError(statusNode, P.describeError(err, {
          notFound: "Benchmark not found.",
          generic: "Could not load submission history. Try again later.",
        }));
      }
    );
  }

  P.ready(init);
})(window.ScorePortal);
