/* Regression tests for review fixes to the score/cost Pareto chart (OME-923 part C). */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../../portal/leaderboard-logic.js");
const C = require("../../portal/pareto-chart.js");

test("buildCostTicks adds precision when cent rounding would repeat every label", () => {
  const ticks = C.buildCostTicks([1.001, 1.004], "linear", L.formatCost);
  const labels = ticks.map((tick) => tick.label);

  assert.equal(ticks.length, 5);
  assert.equal(new Set(labels).size, 5);
  assert.equal(labels[0], "$1.0010");
  assert.equal(labels[4], "$1.0040");
});

test("buildCostTicks keeps exact endpoints when interpolated ticks exceed wire precision", () => {
  const ticks = C.buildCostTicks([1, 1.000001], "linear", L.formatCost);

  assert.deepEqual(
    ticks.map((tick) => [tick.position, tick.label]),
    [
      [0, "$1.000000"],
      [1, "$1.000001"],
    ],
  );
});
