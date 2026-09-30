/* Tests for the "N reported results" link of a leaderboard row (E14, OME-1307, SC-22).
 *
 * WHY a file of its own: the append-only gate cannot parse JS, so an edit of an existing JS test
 * file fails it. This file is wired into the gate by name at both call sites
 * (tests/unit/test_portal_ci_wiring.py).
 *
 * INVARIANT: a row shows the link only from two results (one result is the row itself), and the
 * entry is untrusted API text: the score id is percent-encoded into the path, never trusted.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const R = require("../../portal/reported-results.js");

test("reportedResultsLink: shows count and link only from two results", () => {
  assert.equal(R.reportedResultsLink({ score_id: "abc", reported_results_count: 1 }), null);
  assert.deepEqual(R.reportedResultsLink({ score_id: "abc", reported_results_count: 2 }), {
    text: "2 reported results",
    href: "/v1/scores/abc/results",
  });
  assert.equal(R.reportedResultsLink({ score_id: "abc", reported_results_count: 17 }).text, "17 reported results");
});

test("reportedResultsLink: a score id with a slash is encoded", () => {
  const link = R.reportedResultsLink({ score_id: "a/b?c", reported_results_count: 3 });
  assert.equal(link.href, "/v1/scores/a%2Fb%3Fc/results");
});

for (const [label, entry] of [
  ["missing id", { reported_results_count: 5 }],
  ["numeric id", { score_id: 7, reported_results_count: 5 }],
  ["missing count", { score_id: "abc" }],
  ["zero", { score_id: "abc", reported_results_count: 0 }],
  ["string count", { score_id: "abc", reported_results_count: "5" }],
  ["fractional count", { score_id: "abc", reported_results_count: 2.5 }],
  ["null entry", null],
  ["undefined entry", undefined],
]) {
  test(`reportedResultsLink: ${label} gives no link`, () => {
    assert.equal(R.reportedResultsLink(entry), null);
  });
}
