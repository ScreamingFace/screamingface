/* The revision selector's decisions (OME-1708): labels, URL state, fallback and the empty-Latest
 * pointer. Pure functions from portal/revision-selector.js, asserted without a browser.
 *
 * STORY: as a researcher, after MMLU-Pro's revision moves, I see "Latest" by default, an honest
 * empty board with a link to the previous revision's results, and a URL I can share.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const R = require("../../portal/revision-selector.js");

function revision(overrides) {
  return Object.assign(
    {
      revision: "a41c09e2aaaaaaaa",
      first_seen_at: "2026-11-17T12:00:00Z",
      first_seen_inferred: false,
      until: null,
      case_count: 12032,
      case_count_inferred: false,
      result_count: 9,
      current: true,
    },
    overrides
  );
}

const LATEST = revision({});
const PREVIOUS = revision({
  revision: "32a91cf1e087f719",
  first_seen_at: "2026-10-09T09:00:00Z",
  first_seen_inferred: true,
  until: "2026-11-17T12:00:00Z",
  result_count: 12,
  current: false,
});
const OLDEST = revision({
  revision: "0f00ba11c0ffee00",
  first_seen_at: "2026-09-01T09:00:00Z",
  until: "2026-10-09T09:00:00Z",
  result_count: 1,
  current: false,
});

test("option labels name Latest, Previous and older revisions with dates, short ids and counts", () => {
  assert.deepEqual(
    [LATEST, PREVIOUS, OLDEST].map(R.optionLabel),
    [
      "Latest · since 17 Nov 2026 · a41c09e2 · 9 results",
      "Previous · about 9 Oct – 17 Nov 2026 · 32a91cf1 · 12 results",
      "1 Sep – 9 Oct 2026 · 0f00ba11 · 1 result",
    ]
  );
});

test("a range crossing a year names both years", () => {
  const old = revision({
    first_seen_at: "2025-12-20T00:00:00Z",
    until: "2026-01-05T00:00:00Z",
    current: false,
  });

  assert.equal(R.optionLabel(old), "Previous · 20 Dec 2025 – 5 Jan 2026 · a41c09e2 · 9 results");
});

// After a rollback or an empty Latest, Latest is listed first but is not the newest first
// sighting, so the newest earlier revision arrives with no end date.
test("an earlier revision with no end date reads 'from', not as a single day", () => {
  const open = revision({ first_seen_at: "2026-10-09T09:00:00Z", until: null, current: false });

  assert.equal(R.optionLabel(open, 1), "Previous · from 9 Oct 2026 · a41c09e2 · 9 results");
});

test("a single revision reads as plain text, not a one-item dropdown", () => {
  assert.equal(R.staticLabel(LATEST), "a41c09e2 · since 17 Nov 2026");
  assert.equal(
    R.staticLabel(revision({ first_seen_inferred: true })),
    "a41c09e2 · since about 17 Nov 2026"
  );
});

test("the selection is the requested revision, else Latest", () => {
  const all = [LATEST, PREVIOUS, OLDEST];

  assert.deepEqual(R.resolveSelection(all, null), { selected: LATEST, notFound: false });
  assert.deepEqual(R.resolveSelection(all, PREVIOUS.revision), {
    selected: PREVIOUS,
    notFound: false,
  });
  // INVARIANT: an id that is not on this board falls back to Latest and says so.
  assert.deepEqual(R.resolveSelection(all, "1234abcd5678ef90"), {
    selected: LATEST,
    notFound: true,
  });
});

test("the requested revision is read from the page URL", () => {
  assert.equal(R.requestedRevision("?id=mmlu_pro&revision=32a91cf1e087f719"), "32a91cf1e087f719");
  assert.equal(R.requestedRevision("?id=mmlu_pro"), null);
  assert.equal(R.requestedRevision("?id=mmlu_pro&revision="), null);
});

test("choosing a revision writes it to the URL; choosing Latest removes it", () => {
  assert.equal(
    R.searchWith("?id=mmlu_pro", PREVIOUS),
    "?id=mmlu_pro&revision=32a91cf1e087f719"
  );
  assert.equal(R.searchWith("?id=mmlu_pro&revision=32a91cf1e087f719", LATEST), "?id=mmlu_pro");
});

test("an empty Latest points to the newest earlier revision that has results", () => {
  const emptyLatest = revision({ result_count: 0 });
  const emptyPrevious = revision({ ...PREVIOUS, result_count: 0 });

  assert.deepEqual(R.emptyLatestPointer([emptyLatest, PREVIOUS, OLDEST], emptyLatest), {
    revision: PREVIOUS,
    text: "No results under this revision yet. 12 results under 32a91cf1 (previous).",
  });
  assert.deepEqual(R.emptyLatestPointer([emptyLatest, emptyPrevious, OLDEST], emptyLatest), {
    revision: OLDEST,
    text: "No results under this revision yet. 1 result under 0f00ba11.",
  });
  // No pointer when Latest has results, when an older revision is shown, or when none has any.
  assert.equal(R.emptyLatestPointer([LATEST, PREVIOUS], LATEST), null);
  assert.equal(R.emptyLatestPointer([emptyLatest, PREVIOUS], PREVIOUS), null);
  assert.equal(R.emptyLatestPointer([emptyLatest], emptyLatest), null);
});

test("the not-found notice names the requested id", () => {
  assert.equal(
    R.notFoundNotice("1234abcd5678ef90"),
    "Revision 1234abcd is not on this leaderboard. Showing the latest."
  );
});
