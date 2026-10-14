/* OME-1595: short y-axis tick labels and plain wording for the board's Pareto chart.
 *
 * WHY round ticks: the y-axis used the 6-significant-digit score formatter ("0.515175"), and
 * a label that long ran into the rotated "Score" title. Ticks now sit on round multiples of a
 * 1/2/2.5/5 step, labelled exactly; point tooltips keep full precision.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../../portal/leaderboard-logic.js");
const C = require("../../portal/pareto-chart.js");

function chartEntry(spec_id, score, cost, frontier) {
  return { spec_id, score, run_cost_usd: cost, on_pareto_frontier: frontier };
}

function values(axis) {
  return axis.ticks.map((tick) => tick.value);
}

function labels(axis) {
  return axis.ticks.map((tick) => tick.label);
}

// Every label names its tick exactly, no two repeat, and the top label is the axis top.
function assertExactAxis(axis) {
  assert.deepEqual(axis.ticks.map((tick) => Number(tick.label)), values(axis));
  assert.equal(new Set(labels(axis)).size, axis.ticks.length);
  const top = axis.ticks[axis.ticks.length - 1];
  assert.equal(Number(top.label), axis.domain[1]);
  assert.equal(top.position, 1);
}

test("buildScoreTicks rounds a 0.6869 board up to 0.8 in steps of 0.2", () => {
  const axis = C.buildScoreTicks(0, 0.6869);
  assert.deepEqual(axis.domain, [0, 0.8]);
  assert.deepEqual(values(axis), [0, 0.2, 0.4, 0.6, 0.8]);
  assert.deepEqual(labels(axis), ["0.0", "0.2", "0.4", "0.6", "0.8"]);
  // Positions are pixel fractions, so compare them within float tolerance.
  [0, 0.25, 0.5, 0.75, 1].forEach((expected, index) => {
    assert.ok(Math.abs(axis.ticks[index].position - expected) < 1e-12, String(index));
  });
  assertExactAxis(axis);
});

test("buildScoreTicks names a tiny board without repeating labels", () => {
  const axis = C.buildScoreTicks(0, 0.03);
  assert.deepEqual(axis.domain, [0, 0.03]);
  assert.deepEqual(labels(axis), ["0.00", "0.01", "0.02", "0.03"]);
  assertExactAxis(axis);
});

test("buildScoreTicks keeps a perfect-score board at 1.0", () => {
  const axis = C.buildScoreTicks(0, 1);
  assert.deepEqual(axis.domain, [0, 1]);
  assert.deepEqual(labels(axis), ["0.0", "0.2", "0.4", "0.6", "0.8", "1.0"]);
  assertExactAxis(axis);
});

test("buildScoreTicks handles an all-negative board on exact multiples", () => {
  const axis = C.buildScoreTicks(-1.2, -0.4);
  assert.deepEqual(axis.domain, [-1.2, -0.4]);
  assert.deepEqual(labels(axis), ["-1.2", "-1.0", "-0.8", "-0.6", "-0.4"]);
  assertExactAxis(axis);
});

test("buildScoreTicks keeps an off-step negative floor and labels only multiples", () => {
  const axis = C.buildScoreTicks(-1.143, 0.5);
  assert.deepEqual(axis.domain, [-1.143, 0.5], "the floor stays at the lowest score");
  assert.deepEqual(labels(axis), ["-1.0", "-0.5", "0.0", "0.5"]);
  assertExactAxis(axis);
});

test("buildScoreTicks uses whole numbers on a 0-100 board", () => {
  const axis = C.buildScoreTicks(0, 87.3);
  assert.deepEqual(axis.domain, [0, 100]);
  assert.deepEqual(labels(axis), ["0", "20", "40", "60", "80", "100"]);
  assertExactAxis(axis);
});

test("buildScoreTicks keeps between 2 and 6 ticks across magnitudes", () => {
  [0.0042, 0.03, 0.21, 0.41, 0.6869, 0.999, 1, 7.5, 87.3].forEach((top) => {
    const axis = C.buildScoreTicks(0, top);
    assert.ok(axis.ticks.length >= 2 && axis.ticks.length <= 6, top + ": " + labels(axis));
    assert.ok(axis.domain[1] >= top, top + " fits under the axis top");
    assertExactAxis(axis);
  });
});

test("buildScoreTicks leaves a single-value board as one centred tick", () => {
  const axis = C.buildScoreTicks(-1.143, -1.143);
  assert.deepEqual(axis.domain, [-1.143, -1.143]);
  assert.deepEqual(axis.ticks.map((tick) => [tick.position, tick.value]), [[0.5, -1.143]]);
  assert.equal(Number(axis.ticks[0].label), -1.143);
});

test("buildChartModel plots points against the extended score axis", () => {
  const model = C.buildChartModel([
    chartEntry("cheap", 0.3, "1.000000", true),
    chartEntry("dear", 0.6869, "2.000000", true),
  ]);
  assert.ok(model);
  assert.deepEqual(model.scoreDomain, [0, 0.8]);
  assert.deepEqual(model.scoreTicks.map((tick) => tick.label), ["0.0", "0.2", "0.4", "0.6", "0.8"]);
  const dear = model.priced.find((point) => point.specId === "dear");
  assert.equal(dear.y, 0.6869 / 0.8);
});

test("an unnamed row is called an unnamed submission", () => {
  const model = C.buildChartModel([chartEntry("", 0.5, "1.000000", true)]);
  assert.ok(model);
  assert.equal(model.priced[0].specId, "Unnamed submission");
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
