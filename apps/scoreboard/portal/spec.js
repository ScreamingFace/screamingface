/* ScreamingFace Leaderboard Portal — spec history page.
 *
 * Reads ?benchmark=<id>&spec=<spec_id>. The history endpoint deliberately
 * omits url4_expression, so the top "Run Locally" link is built from the most
 * recent submission's score detail via GET /v1/scores/{submissions[0].id}
 * (submissions are newest-first). That id is the same Score UUID the scores
 * route accepts, so no backend change is needed. Per task line 41 this link
 * intentionally uses the NEWEST submission, which may differ from the
 * best-per-spec url4 shown on the leaderboard row.
 */
(function (P) {
  "use strict";

  function historyRow(s) {
    var tr = document.createElement("tr");
    tr.appendChild(P.el("td", null, P.formatDate(s.submitted_at)));
    tr.appendChild(P.el("td", "cell-wrap", P.formatSubmitter(s.submitted_by)));
    tr.appendChild(P.el("td", "cell-wrap", P.formatAuthors(s.authors)));
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

  function renderRunLink(regionNode, specId, latestId) {
    P.fetchJson("/v1/scores/" + encodeURIComponent(latestId)).then(
      function (score) {
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
        regionNode.appendChild(P.el("p", "quiet", "Run link unavailable for the latest submission."));
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
      P.showError(statusNode, "Missing benchmark or spec. Return to the leaderboard.");
      return;
    }

    specIdNode.textContent = specId;
    backLink.setAttribute("href", "benchmark.html?id=" + encodeURIComponent(benchmarkId));
    document.title = specId + " — screamingface";

    P.showLoading(statusNode, "Loading spec history…");
    contentNode.hidden = true;

    resolveBenchmarkName(benchmarkId).then(function (name) {
      benchNode.textContent = name;
    });

    P.fetchJson("/v1/leaderboard/" + encodeURIComponent(benchmarkId) + "/" + encodeURIComponent(specId) + "/history?limit=20").then(
      function (data) {
        var submissions = (data && data.submissions) || [];
        if (submissions.length === 0) {
          P.showEmpty(statusNode, "No submissions for this spec yet.");
          return;
        }

        var best = Math.max.apply(null, submissions.map(function (s) { return s.score; }));
        document.getElementById("best-score").textContent = P.formatScore(best);
        // Bare number: the .stats cell label ("Submissions") carries the word.
        document.getElementById("submission-count").textContent = submissions.length.toLocaleString();

        var body = document.getElementById("history-body");
        P.clear(body);
        submissions.forEach(function (s) { body.appendChild(historyRow(s)); });

        P.setStatus(statusNode, null);
        contentNode.hidden = false;

        // Newest submission is submissions[0] (backend orders newest-first).
        renderRunLink(document.getElementById("run-region"), specId, submissions[0].id);
      },
      function (err) {
        P.showError(statusNode, P.describeError(err, {
          notFound: "Benchmark not found.",
          generic: "Could not load spec history — try again later.",
        }));
      }
    );
  }

  P.ready(init);
})(window.ScorePortal);
