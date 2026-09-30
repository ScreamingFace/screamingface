/* The "N reported results" link of a leaderboard row.
 *
 * A row stands for one system, and the runs reported for that system are listed at
 * `GET /v1/scores/{id}/results`. The leaderboard row carries `score_id` and
 * `reported_results_count` only from TWO results (one result is the row itself). This file
 * decides whether the row shows a link and where it points.
 *
 * WHY separate from benchmark.js: the decision is pure, so it is assertable under Node without a
 * browser, like leaderboard-logic.js.
 *
 * The entry is untrusted API text. The score id is percent-encoded into the path, and the result
 * is a `{ text, href }` pair for `P.link`, which sets text only, never `innerHTML`.
 *
 * Loaded as a plain <script> (exposing window.SFReportedResults) and via require() in tests.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SFReportedResults = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // The link target is the JSON endpoint: there is no portal results page yet.
  function reportedResultsLink(entry) {
    if (!entry) return null;
    var count = entry.reported_results_count;
    if (typeof count !== "number" || !Number.isInteger(count) || count < 2) return null;
    if (typeof entry.score_id !== "string" || entry.score_id === "") return null;
    return {
      text: count + " reported results",
      href: "/v1/scores/" + encodeURIComponent(entry.score_id) + "/results",
    };
  }

  return { reportedResultsLink: reportedResultsLink };
});
