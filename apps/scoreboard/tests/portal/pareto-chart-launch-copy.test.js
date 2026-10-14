/* OME-1595: short y-axis tick labels and plain wording for the board's Pareto chart.
 *
 * WHY short ticks: the y-axis used the 6-significant-digit score formatter ("0.515175"), and
 * a label that long ran into the rotated "Score" title. Ticks get 2 decimals; point tooltips
 * keep full precision.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../../portal/leaderboard-logic.js");
const C = require("../../portal/pareto-chart.js");

function chartEntry(spec_id, score, cost, frontier) {
  return { spec_id, score, run_cost_usd: cost, on_pareto_frontier: frontier };
}

test("formatScoreTick rounds to two decimals", () => {
  assert.equal(C.formatScoreTick(0.515175), "0.52");
  assert.equal(C.formatScoreTick(0.6875), "0.69");
  assert.equal(C.formatScoreTick(1), "1.00");
  assert.equal(C.formatScoreTick(0), "0.00");
  assert.equal(C.formatScoreTick(0.25), "0.25");
});

test("formatScoreTick keeps the sign of a negative score", () => {
  // HealthBench worst-30 boards score below zero, so the axis floor goes negative.
  assert.equal(C.formatScoreTick(-1.143), "-1.14");
});

test("describePoint says a priced non-frontier point is not on the Pareto frontier", () => {
  const model = C.buildChartModel([
    chartEntry("cheap", 0.9, "1.000000", true),
    chartEntry("dear", 0.515175, "3.000000", false),
  ]);
  assert.ok(model);
  const dear = model.priced.find((point) => point.specId === "dear");
  const formatScore = (score) => String(score);

  assert.equal(
    C.describePoint(dear, L.formatCost, formatScore),
    "dear: score 0.515175, cost $3.000000 (shown as " + L.formatCost(dear.entry) + ")" +
      "; not on the Pareto frontier"
  );
});

test("describePoint keeps full score precision for a frontier point", () => {
  const model = C.buildChartModel([chartEntry("cheap", 0.515175, "1.000000", true)]);
  assert.ok(model);
  const formatScore = (score) => String(score);

  assert.equal(
    C.describePoint(model.priced[0], L.formatCost, formatScore),
    "cheap: score 0.515175, cost $1.000000 (shown as " + L.formatCost(model.priced[0].entry) + ")" +
      "; on the Pareto frontier; highest score"
  );
});
