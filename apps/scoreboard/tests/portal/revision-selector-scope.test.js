/* What the board says about the revision it shows (OME-1708, PR #1943 review round 2): the line
 * for an inferred Case count, and the empty-board text for a past revision.
 *
 * STORY: as a researcher browsing an old revision, I am told when its Case count was inferred
 * from results, and an empty old revision never invites me to submit to it.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const R = require("../../portal/revision-selector.js");

const LATEST = { revision: "a41c09e2aaaaaaaa", current: true, case_count_inferred: false };
const BACKFILLED = { revision: "32a91cf1e087f719", current: false, case_count_inferred: true };
const RECORDED = { revision: "0f00ba11c0ffee00", current: false, case_count_inferred: false };

test("a revision whose Case count was inferred says so; a recorded one says nothing", () => {
  assert.equal(R.scopeNote(BACKFILLED), "Case count inferred from results.");
  assert.equal(R.scopeNote(RECORDED), null);
  assert.equal(R.scopeNote(LATEST), null);
  assert.equal(R.scopeNote(null), null);
});

test("an empty board invites a first run only on the current revision", () => {
  assert.equal(R.emptyBoardText(LATEST), "No submissions yet. Be the first.");
  assert.equal(R.emptyBoardText(RECORDED), "No complete runs under this revision.");
  // Without a revision list the page cannot tell, and keeps its original line.
  assert.equal(R.emptyBoardText(null), "No submissions yet. Be the first.");
});
