/* Reviewer fixes for the revision selector (OME-1708, PR #1943 review by Dmitry and Khoa): what
 * the board says when its revision list is missing, and a history best score that never mixes
 * revisions.
 *
 * STORY: as a researcher opening a shared link to an earlier revision while the revision list is
 * unavailable, I am still told which grading I am looking at; and the history page never ranks a
 * run under one grading against a run under another.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const R = require("../../portal/revision-selector.js");

const CURRENT = "a41c09e2aaaaaaaa";
const EARLIER = "32a91cf1e087f719";

test("without a revision list, the board names the revision it was asked for", () => {
  const board = { revision: CURRENT, visibility: "public" };

  assert.deepEqual(R.unlistedScopeNotice(EARLIER, { ...board, revision: EARLIER }), {
    text: "Showing revision 32a91cf1. The list of revisions could not be loaded.",
    clearRequest: false,
  });
  assert.deepEqual(R.unlistedScopeNotice(CURRENT, board), {
    text: "Showing revision a41c09e2. The list of revisions could not be loaded.",
    clearRequest: false,
  });
  // No revision asked for: Latest, nothing to say.
  assert.equal(R.unlistedScopeNotice(null, board), null);
});

// A private board lists no revisions and its board route ignores `revision`, so what is shown is
// Latest whatever the URL asked for.
test("a private board drops the requested revision and says it shows the latest", () => {
  assert.deepEqual(R.unlistedScopeNotice(EARLIER, { revision: CURRENT, visibility: "private" }), {
    text: "Earlier revisions are not shown on private boards. Showing the latest.",
    clearRequest: true,
  });
});

function run(score, revision) {
  return { score, benchmark_revision: revision };
}

test("the history best score covers one revision only", () => {
  const listed = [
    { revision: CURRENT, current: true },
    { revision: EARLIER, current: false },
  ];

  // All runs under one revision: the plain best score.
  assert.deepEqual(R.historyBest([run(0.5, CURRENT), run(0.7, CURRENT)], listed), {
    score: 0.7,
    label: "Best score",
  });
  // Mixed revisions: the best under the latest revision, labelled so.
  assert.deepEqual(R.historyBest([run(0.5, CURRENT), run(0.9, EARLIER)], listed), {
    score: 0.5,
    label: "Best score, latest revision",
  });
  // Mixed with no run under the latest revision, or no list yet: no single number is honest.
  assert.equal(R.historyBest([run(0.5, EARLIER), run(0.9, "1234abcd5678ef90")], listed), null);
  assert.equal(R.historyBest([run(0.5, CURRENT), run(0.9, EARLIER)], []), null);
  assert.equal(R.historyBest([], listed), null);
});
