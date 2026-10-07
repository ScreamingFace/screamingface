/* Tests for the index catalogue card helpers — currently the description clamp.
 *
 * Runs on Node's built-in runner; NAMED EXPLICITLY in the scoreboard card gate list and in
 * scoreboard-tests.yml (OME-798). A dedicated file (not appended to leaderboard-logic.test.js)
 * because the append-only gate cannot parse a .js edit to prove it is additive.
 *
 * The index catalogue is a grid of cards; each shows up to 100 characters of the benchmark's
 * description, so a long paragraph cannot blow out a card's height.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../../portal/leaderboard-logic.js");

test("truncate returns a short string unchanged", () => {
  assert.equal(L.truncate("A crisp one-liner.", 100), "A crisp one-liner.");
});

test("truncate returns a string exactly at the limit unchanged (no stray ellipsis)", () => {
  const exact = "x".repeat(100);
  assert.equal(L.truncate(exact, 100), exact);
});

test("truncate clips an over-long description to <= max chars plus an ellipsis", () => {
  const long = "y".repeat(250);
  const out = L.truncate(long, 100);
  assert.equal(out.slice(0, 100), "y".repeat(100), "keeps the first 100 characters");
  assert.equal(out.endsWith("…"), true, "marks the clip with an ellipsis");
  assert.equal(out.length, 101, "100 chars of description + one ellipsis glyph");
});

test("truncate does not leave a space stranded before the ellipsis", () => {
  // Clip lands on a space; trim it so the result reads "…word…" not "word …".
  const text = "word ".repeat(40); // "word word word ..."
  const out = L.truncate(text, 100);
  assert.equal(/\s…$/.test(out), false, "no whitespace immediately before the ellipsis");
  assert.equal(out.endsWith("d…"), true);
});

test("truncate treats a missing or non-string description as empty", () => {
  assert.equal(L.truncate(undefined, 100), "");
  assert.equal(L.truncate(null, 100), "");
  assert.equal(L.truncate(42, 100), "");
});
