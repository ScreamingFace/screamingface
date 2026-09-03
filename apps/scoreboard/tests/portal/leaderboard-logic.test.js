/* Tests for the leaderboard's pure ranking/SOTA decisions (OME-769, OME-866).
 *
 * Runs on Node's built-in runner — `node --test tests/portal/` — so it needs no
 * package.json, no dependency, and no new toolchain. Wiring it into
 * scoreboard-tests.yml + the sdlc card's gate list is deliberately a separate
 * unit of work; until that lands these run locally and in review.
 *
 * WHY these three functions are pure and live outside the DOM code: the board's
 * two load-bearing judgements — "which row, if any, earns the SOTA medal" and
 * "how long is the score bar" — decide what a public leaderboard *claims*.
 * They must be assertable without a browser.
 *
 * OME-866: entries carry a benchmark-native `score` (fractional for DRACO,
 * negative for HealthBench worst-30), not a 0..1 `accuracy` — the assertions on
 * negative and mixed ranges pin that the board renders them without a universal
 * percentage assumption.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../../portal/leaderboard-logic.js");

// A leaderboard entry, trimmed to the fields these decisions actually read.
function entry(spec_id, score, verified) {
  return { spec_id, score, verified_by_screamingface: verified };
}

test("sotaScore: no entries means no SOTA", () => {
  assert.equal(L.sotaScore([]), null);
});

test("sotaScore: entries but none reproducible means no SOTA at all", () => {
  // INVARIANT: the medal never falls back to an unverified row. A board with
  // nothing reproduced shows no medal — it must not imply OpenMined reproduced
  // a self-reported score. This is the whole point of OME-769's "top
  // reproducible fusion" wording.
  const entries = [entry("a", 0.9, false), entry("b", 0.8, false)];
  assert.equal(L.sotaScore(entries), null);
});

test("sotaScore: picks the best score among reproducible entries", () => {
  const entries = [entry("a", 0.5, true), entry("b", 0.7, true)];
  assert.equal(L.sotaScore(entries), 0.7);
});

test("sotaScore: a higher-score unverified entry does NOT take the medal", () => {
  // The D2 invariant, stated as a test: 0.99 unverified must lose to 0.40
  // verified. Today's board (pre-OME-769) would wrongly mark the 0.99 row.
  const entries = [entry("cheater", 0.99, false), entry("honest", 0.4, true)];
  assert.equal(L.sotaScore(entries), 0.4);
});

test("sotaScore: all-negative reproducible entries still produce a SOTA", () => {
  // OME-866: on the HealthBench worst-30 board EVERY serious score is negative;
  // "best" is the least negative, and the medal logic must not treat a negative
  // number as falsy or missing.
  const entries = [entry("a", -1.143, true), entry("b", -0.4, true)];
  assert.equal(L.sotaScore(entries), -0.4);
});

test("isSota: true only for a reproducible entry at the SOTA score", () => {
  const sota = 0.7;
  assert.equal(L.isSota(entry("a", 0.7, true), sota), true);
  assert.equal(L.isSota(entry("b", 0.7, false), sota), false, "unverified at the same score");
  assert.equal(L.isSota(entry("c", 0.6, true), sota), false, "verified but below");
});

test("isSota: nothing is SOTA when there is no SOTA score", () => {
  assert.equal(L.isSota(entry("a", 0.9, true), null), false);
});

test("isSota: ties at the top all carry the medal", () => {
  // Deliberate: with a genuine tie there is no non-arbitrary single winner, so
  // both reproducible rows are marked rather than picking one by input order.
  const sota = 0.7;
  assert.equal(L.isSota(entry("a", 0.7, true), sota), true);
  assert.equal(L.isSota(entry("b", 0.7, true), sota), true);
});

test("orderRows: sorts by score descending", () => {
  const entries = [entry("mid", 0.5, false), entry("top", 0.9, false), entry("low", 0.1, false)];
  assert.deepEqual(
    L.orderRows(entries).map((e) => e.spec_id),
    ["top", "mid", "low"],
  );
});

test("orderRows: negative and mixed scores rank high-to-low too", () => {
  // OME-866: higher is always better within a benchmark, whatever the range.
  const entries = [entry("worst", -1.143, false), entry("best", 0.399, false), entry("mid", -0.2, false)];
  assert.deepEqual(
    L.orderRows(entries).map((e) => e.spec_id),
    ["best", "mid", "worst"],
  );
});

test("orderRows: ties keep their original relative order (stable)", () => {
  const entries = [entry("first", 0.5, false), entry("second", 0.5, false)];
  assert.deepEqual(
    L.orderRows(entries).map((e) => e.spec_id),
    ["first", "second"],
  );
});

test("orderRows: does not mutate its input", () => {
  const entries = [entry("mid", 0.5, false), entry("top", 0.9, false)];
  L.orderRows(entries);
  assert.deepEqual(
    entries.map((e) => e.spec_id),
    ["mid", "top"],
    "caller's array order must be untouched",
  );
});

test("barWidth: a classic 0..1 board keeps its absolute zero origin", () => {
  // The floor is min(0, minScore), so positive boards render exactly as they
  // did before OME-866 — the bar still means "share of the best on screen".
  assert.equal(L.barWidth(0.5, 0.1, 1), 50);
  assert.equal(L.barWidth(1, 0.1, 1), 100);
  assert.equal(L.barWidth(0.25, 0.25, 0.5), 50, "relative to the max shown, not to 100%");
});

test("barWidth: zero score on a positive board is a zero-width bar", () => {
  assert.equal(L.barWidth(0, 0, 0.8), 0);
});

test("barWidth: a zero maximum cannot divide by zero", () => {
  // Reachable: a benchmark where every submission scored 0.
  assert.equal(L.barWidth(0, 0, 0), 0);
});

test("barWidth: never exceeds 100 even if handed a value above the max", () => {
  assert.equal(L.barWidth(1.5, 0, 1), 100);
});

test("barWidth: negative scores shift the origin instead of rendering negative widths", () => {
  // OME-866: an all-negative HealthBench board spans floor..max. The lowest row
  // is 0-width, the best is full, and NOTHING is negative (a negative CSS width
  // is invalid and collapses the track).
  assert.equal(L.barWidth(-1.143, -1.143, 0.399), 0);
  assert.equal(L.barWidth(0.399, -1.143, 0.399), 100);
  const mid = L.barWidth(-0.372, -1.143, 0.399);
  assert.ok(mid > 49 && mid < 51, `midpoint of the span is ~50, got ${mid}`);
  assert.ok(L.barWidth(-0.4, -1.143, 0.399) >= 0);
});

test("barWidth: an all-equal negative board renders empty tracks, not negatives", () => {
  assert.equal(L.barWidth(-1.143, -1.143, -1.143), 0);
});

test("barWidth: a missing max is a zero-width bar, never NaN in CSS", () => {
  assert.equal(L.barWidth(0.5, undefined, undefined), 0);
  assert.equal(L.barWidth(NaN, 0, 1), 0);
});

/* --- bestEntryScore: the catalogue's "Best reproducible" figure (OME-874) --- */

test("bestEntryScore: an empty or missing board has no best", () => {
  assert.equal(L.bestEntryScore(null), null);
  assert.equal(L.bestEntryScore({}), null);
  assert.equal(L.bestEntryScore({ entries: [] }), null);
});

test("bestEntryScore: null, never 0, when there is nothing to report", () => {
  // 0 is a real score on a benchmark that can go negative, so it must not double as
  // "no submissions" — the portal renders an em dash for null and the number for 0.
  assert.equal(L.bestEntryScore({ entries: [] }), null);
  assert.equal(L.bestEntryScore({ entries: [entry("spec/zero", 0, false)] }), 0);
});

test("bestEntryScore: takes the highest entry, not the first", () => {
  // The route orders by score descending, so the head is normally the answer. Scanning
  // guards against a future reordering silently reporting the wrong benchmark best.
  const board = {
    entries: [entry("spec/a", 0.2, false), entry("spec/b", 0.9, false), entry("spec/c", 0.4, false)],
  };

  assert.equal(L.bestEntryScore(board), 0.9);
});

test("bestEntryScore: negative boards report their least-negative entry", () => {
  // HealthBench worst-30 is negative for every serious entry (OME-866).
  const board = { entries: [entry("spec/a", -1.143, false), entry("spec/b", -0.2, false)] };

  assert.equal(L.bestEntryScore(board), -0.2);
});

test("bestEntryScore: baselines never count as our best", () => {
  // INVARIANT: a baseline is an imported third-party number with no submitter. Letting one
  // win this cell would publish an outside board's figure as our best result.
  const board = {
    entries: [entry("spec/a", 0.4, false)],
    baselines: [{ model_name: "GPT-5.2", score: 0.99 }],
  };

  assert.equal(L.bestEntryScore(board), 0.4);
});

test("bestEntryScore: a malformed entry is skipped, not propagated", () => {
  const board = {
    entries: [{ spec_id: "spec/bad" }, entry("spec/good", 0.5, false), { spec_id: "x", score: NaN }],
  };

  assert.equal(L.bestEntryScore(board), 0.5);
});


/* ---- OME-923 part B: the Pareto frontier mark ------------------------------ */

test("isParetoMarked marks a row the server flagged", () => {
  assert.equal(L.isParetoMarked({ on_pareto_frontier: true }), true);
});

test("isParetoMarked does not mark an unflagged row", () => {
  assert.equal(L.isParetoMarked({ on_pareto_frontier: false }), false);
});

test("isParetoMarked does not mark when the field is absent", () => {
  // INVARIANT: an older server, or any response without the field, must render as
  // "not marked" rather than throwing or guessing. The board makes no cost claim it
  // was not handed.
  assert.equal(L.isParetoMarked({ score: 0.9 }), false);
  assert.equal(L.isParetoMarked({}), false);
});

test("isParetoMarked is strict, so a truthy non-true value never marks", () => {
  // WHY strict === true, mirroring isReproducible: the mark asserts a public claim
  // about money. A truthy check would mark on "false", 1, or any junk the field
  // ever carried across a version skew.
  assert.equal(L.isParetoMarked({ on_pareto_frontier: "false" }), false);
  assert.equal(L.isParetoMarked({ on_pareto_frontier: 1 }), false);
});

test("isParetoMarked tolerates a missing entry", () => {
  assert.equal(L.isParetoMarked(null), false);
  assert.equal(L.isParetoMarked(undefined), false);
});


/* ---- OME-923 / OME-770 pass 2: the Cost column ----------------------------- */

test("costNumber parses the fixed-6dp wire string", () => {
  assert.equal(L.costNumber({ run_cost_usd: "12.400000" }), 12.4);
  assert.equal(L.costNumber({ run_cost_usd: "0.000000" }), 0);
  assert.equal(L.costNumber({ run_cost_usd: "1000.000000" }), 1000);
});

test("costNumber treats an absent cost as unknown, never zero", () => {
  // INVARIANT (OME-770 D8): null means "not reported". Returning 0 here would make an
  // unpriced row the cheapest on the board.
  assert.equal(L.costNumber({ run_cost_usd: null }), null);
  assert.equal(L.costNumber({}), null);
  assert.equal(L.costNumber({ run_cost_usd: "" }), null);
  assert.equal(L.costNumber(null), null);
});

test("costNumber rejects a non-numeric value rather than coercing it", () => {
  assert.equal(L.costNumber({ run_cost_usd: "free" }), null);
  assert.equal(L.costNumber({ run_cost_usd: "NaN" }), null);
});

test("compareCost orders by real magnitude, not lexicographically", () => {
  // WHY this test exists: the wire form is a STRING at fixed 6dp, and "1000.000000" <
  // "3.500000" is true in JavaScript. OME-770 section 2.4 requires converting before
  // comparing, and says the frontier logic must be tested on values of differing integer
  // width precisely to catch this.
  const dear = { run_cost_usd: "1000.000000" };
  const cheap = { run_cost_usd: "3.500000" };
  assert.ok(L.compareCost(cheap, dear, "asc") < 0);
  assert.ok(L.compareCost(dear, cheap, "asc") > 0);
});

test("compareCost sorts an unpriced row last in BOTH directions", () => {
  // INVARIANT: unknown is not cheap and not dear. benchmark.js's generic numeric compare is
  // `(av || 0) - (bv || 0)`, which would rank a null row as the cheapest on the board — the
  // exact "a null cost never reads as zero" rule the frontier depends on.
  const priced = { run_cost_usd: "5.000000" };
  const unpriced = { run_cost_usd: null };
  assert.ok(L.compareCost(priced, unpriced, "asc") < 0);
  assert.ok(L.compareCost(priced, unpriced, "desc") < 0);
  assert.ok(L.compareCost(unpriced, priced, "asc") > 0);
  assert.ok(L.compareCost(unpriced, priced, "desc") > 0);
});

test("compareCost keeps a genuine zero as the cheapest priced row", () => {
  const free = { run_cost_usd: "0.000000" };
  const paid = { run_cost_usd: "0.010000" };
  assert.ok(L.compareCost(free, paid, "asc") < 0);
  assert.equal(L.compareCost(free, { run_cost_usd: "0.000000" }, "asc"), 0);
});

test("formatCost renders an absent cost as an em dash, never as money", () => {
  assert.equal(L.formatCost({ run_cost_usd: null }), "\u2014");
  assert.equal(L.formatCost({}), "\u2014");
});

test("formatCost rounds for display so six decimals cannot overflow the column", () => {
  // OME-770 D2: full precision is stored, the UI rounds.
  assert.equal(L.formatCost({ run_cost_usd: "12.400000" }), "$12.40");
  assert.equal(L.formatCost({ run_cost_usd: "1000.000000" }), "$1,000.00");
  assert.equal(L.formatCost({ run_cost_usd: "0.000000" }), "$0.00");
});

test("formatCost keeps a sub-cent cost visible instead of rounding it to zero", () => {
  // A cache-heavy run can cost fractions of a cent. Showing $0.00 would misreport it as free,
  // which is the one distinction this column exists to preserve.
  assert.equal(L.formatCost({ run_cost_usd: "0.000900" }), "$0.0009");
  assert.equal(L.formatCost({ run_cost_usd: "0.000001" }), "<$0.0001");
});

test("formatCost does not render one cent in two different formats", () => {
  // Found in review: the sub-cent branch was chosen on the UNROUNDED value but rendered with
  // toFixed(4), so 0.009999 printed "$0.0100" while 0.010000 printed "$0.01". The same money in
  // two formats, and in the ascending Cost column the four-decimal string sits above the
  // two-decimal one and reads as the larger number.
  assert.equal(L.formatCost({ run_cost_usd: "0.009999" }), "$0.01");
  assert.equal(L.formatCost({ run_cost_usd: "0.010000" }), "$0.01");
  // Genuinely sub-cent values still keep their four places.
  assert.equal(L.formatCost({ run_cost_usd: "0.009000" }), "$0.0090");
});
