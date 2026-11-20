/* Review fixes for the revision selector (OME-1708, PR #1943): telling an unknown revision from an
 * unknown benchmark, and linking history rows only to revisions the board lists.
 *
 * STORY: as a researcher opening a mistyped board link, I am told the benchmark is missing, not
 * that a revision is; and a history row never links me to a revision its board does not have.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const R = require("../../portal/revision-selector.js");

const LATEST = { revision: "a41c09e2aaaaaaaa", current: true };
const PREVIOUS = { revision: "32a91cf1e087f719", current: false };

// The board answers 404 both for an unknown revision and for an unknown benchmark. Only the first
// may fall back to Latest; the second must say the benchmark is missing, with no revision notice.
function failure(status, body) {
  const err = new Error("Request failed with status " + status);
  err.status = status;
  err.body = body;
  return err;
}

test("only the board's own revision 404 counts as an unknown revision", () => {
  assert.equal(
    R.isRevisionNotFound(failure(404, JSON.stringify({ detail: "Revision not found for this benchmark" }))),
    true
  );
  assert.equal(R.isRevisionNotFound(failure(404, JSON.stringify({ detail: "Benchmark not found" }))), false);
  assert.equal(R.isRevisionNotFound(failure(404, "<html>not json</html>")), false);
  assert.equal(R.isRevisionNotFound(failure(500, "")), false);
  assert.equal(R.isRevisionNotFound(null), false);
});

// A run's revision comes from its client, so the history page links only ids the board lists.
test("a history row links only a revision the board lists, and tags only the current one", () => {
  const rows = [LATEST, PREVIOUS];

  assert.deepEqual(R.listedRevision(rows, LATEST.revision), { current: true });
  assert.deepEqual(R.listedRevision(rows, PREVIOUS.revision), { current: false });
  assert.equal(R.listedRevision(rows, "1234abcd5678ef90"), null);
  // An unreadable or private board lists nothing, so nothing is linked or tagged.
  assert.equal(R.listedRevision([], LATEST.revision), null);
});
