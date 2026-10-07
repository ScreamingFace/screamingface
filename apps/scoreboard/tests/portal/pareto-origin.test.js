/* Tests for the Pareto chart axis origin — both axes meet at 0, not at the data's lowest value.
 *
 * Runs on Node's built-in runner; NAMED EXPLICITLY in the scoreboard card gate list and in
 * scoreboard-tests.yml (OME-798), like the sibling portal suites. A dedicated file (not appended
 * to pareto-chart.test.js) because the append-only gate cannot parse a .js edit to prove it is
 * additive and fails closed on any modification to an existing .js test artifact.
 *
 * The complaint this fixes: the chart framed its axes on the data range, so a board whose scores
 * sit in [0.4, 0.8] read as if 0.4 were the floor. Anchoring at the origin shows each score and
 * cost against a true zero.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const C = require("../../portal/pareto-chart.js");

function chartEntry(spec_id, score, cost, frontier = true) {
  return { spec_id, score, run_cost_usd: cost, on_pareto_frontier: frontier };
}

test("the score axis is anchored at 0 for an all-positive board, not at the lowest score", () => {
  const model = C.buildChartModel([
    chartEntry("low", 0.4, "1.000000"),
    chartEntry("high", 0.8, "2.000000"),
  ]);
  assert.ok(model);
  assert.deepEqual(model.scoreDomain, [0, 0.8], "floor is 0, not the lowest score 0.4");
  // The lowest score lands halfway up a [0, 0.8] axis, not pinned to the bottom edge.
  const low = model.priced.find((p) => p.specId === "low");
  assert.equal(low.y, 0.5);
});

test("the linear cost axis is anchored at 0, not at the cheapest run", () => {
  const model = C.buildChartModel([
    chartEntry("cheap", 0.4, "1.000000"),
    chartEntry("dear", 0.8, "2.000000"),
  ]);
  assert.ok(model);
  assert.equal(model.costScale, "linear");
  assert.deepEqual(model.costDomain, [0, 2], "floor is 0, not the cheapest cost 1");
  const cheap = model.priced.find((p) => p.specId === "cheap");
  assert.equal(cheap.x, 0.5);
});

test("a negative-score board is never cropped at 0 — the floor is min(0, lowest)", () => {
  // INVARIANT: anchoring at the origin must not hide data. A board whose every score is negative
  // (e.g. HealthBench worst-30) keeps its own negative floor so every point stays on the canvas.
  const model = C.buildChartModel([
    chartEntry("worst", -1.2, "1.000000"),
    chartEntry("best", -0.4, "2.000000"),
  ]);
  assert.ok(model);
  assert.deepEqual(model.scoreDomain, [-1.2, -0.4]);
});

test("a log cost axis keeps its positive minimum — zero has no logarithm", () => {
  // The origin anchor only applies to the linear scale. A wide-cost board still uses a log axis
  // (unchanged contract), and a log axis cannot include 0.
  const model = C.buildChartModel([
    chartEntry("cheap", 0.5, "1.000000"),
    chartEntry("dear", 0.9, "8.000001"),
  ]);
  assert.ok(model);
  assert.equal(model.costScale, "log");
  assert.equal(model.costDomain[0], 1, "the cheapest positive cost, not 0");
});
