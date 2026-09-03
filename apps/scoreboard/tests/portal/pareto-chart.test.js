/* Tests for the public score/cost Pareto chart model (OME-923 part C). */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../../portal/leaderboard-logic.js");
const C = require("../../portal/pareto-chart.js");

function chartEntry(spec_id, score, cost, frontier = false) {
  return {
    spec_id,
    score,
    run_cost_usd: cost,
    on_pareto_frontier: frontier,
  };
}

test("buildChartModel hides the chart until at least one cost is reported", () => {
  assert.equal(C.buildChartModel([]), null);
  assert.equal(C.buildChartModel(null), null);
  assert.equal(
    C.buildChartModel([
      chartEntry("legacy/a", 0.9, null),
      chartEntry("legacy/b", 0.5, null),
    ]),
    null,
  );
});

test("buildChartModel fails closed when no priced row carries a server frontier mark", () => {
  assert.equal(
    C.buildChartModel([
      chartEntry("priced-but-unpinned", 0.9, "1.000000", false),
    ]),
    null,
  );
});

test("buildChartModel uses server membership for the visible frontier line", () => {
  const model = C.buildChartModel([
    chartEntry("dear", 0.9, "1000.000000", true),
    chartEntry("looks-efficient-but-server-said-no", 0.7, "3.000000", false),
    chartEntry("cheap", 0.5, "1.000000", true),
    chartEntry("unknown", 0.99, null, true),
  ]);

  assert.ok(model);
  assert.deepEqual(
    model.frontier.map((point) => point.specId),
    ["cheap", "dear"],
    "only priced rows strictly marked by the server form the line, ordered by cost",
  );
  assert.deepEqual(model.unpriced.map((point) => point.specId), ["unknown"]);
  assert.equal(model.unpriced[0].isFrontier, false, "a null-cost row never inherits a mark");
  assert.equal(model.unpriced[0].isLeader, true, "the highest-score signal remains independent");
});

test("buildChartModel switches to log only above an eightfold positive spread", () => {
  const exact = C.buildChartModel([
    chartEntry("cheap", 0.5, "1.000000", true),
    chartEntry("dear", 0.9, "8.000000", true),
  ]);
  const beyond = C.buildChartModel([
    chartEntry("cheap", 0.5, "1.000000", true),
    chartEntry("dear", 0.9, "8.000001", true),
  ]);
  const free = C.buildChartModel([
    chartEntry("free", 0.5, "0.000000", true),
    chartEntry("dear", 0.9, "1000.000000", true),
  ]);

  assert.equal(exact.costScale, "linear");
  assert.equal(beyond.costScale, "log");
  assert.equal(free.costScale, "linear", "zero is real but has no logarithm");
});

test("buildChartModel keeps degenerate and negative score coordinates finite", () => {
  const model = C.buildChartModel([
    chartEntry("free-a", -1.143, "0.000000", true),
    chartEntry("free-b", -1.143, "0.000000", true),
  ]);

  assert.ok(model);
  assert.deepEqual(model.scoreDomain, [-1.143, -1.143]);
  assert.deepEqual(model.costDomain, [0, 0]);
  model.priced.forEach((point) => {
    assert.ok(Number.isFinite(point.x));
    assert.ok(Number.isFinite(point.y));
    assert.equal(point.x, 0.5);
    assert.equal(point.y, 0.5);
    assert.equal(point.isLeader, true, "all exact highest-score ties carry the ring");
  });
});

test("buildChartModel skips malformed rows instead of emitting invalid SVG positions", () => {
  const model = C.buildChartModel([
    chartEntry("good", 0.5, "2.000000", true),
    chartEntry("bad-score", NaN, "1.000000", true),
    chartEntry("missing-score", undefined, "1.000000", true),
    chartEntry("bad-cost", 0.9, "not-money", true),
    chartEntry("negative-cost", 0.8, "-1.000000", true),
  ]);

  assert.ok(model);
  assert.deepEqual(model.priced.map((point) => point.specId), ["good"]);
  assert.deepEqual(model.unpriced.map((point) => point.specId), ["bad-cost", "negative-cost"]);
});

test("describePoint calls an unpriced row excluded rather than dominated", () => {
  const model = C.buildChartModel([
    chartEntry("priced", 0.5, "2.000000", true),
    chartEntry("unknown", 0.9, null, false),
  ]);

  assert.ok(model);
  const text = C.describePoint(model.unpriced[0], L.formatCost, (score) => String(score));
  assert.match(text, /excluded from Pareto comparison/);
  assert.doesNotMatch(text, /dominated/);
});

test("buildChartModel does not mutate the fetched entries", () => {
  const entries = [
    chartEntry("dear", 0.9, "100.000000", true),
    chartEntry("cheap", 0.5, "1.000000", true),
  ];
  const before = JSON.parse(JSON.stringify(entries));

  C.buildChartModel(entries);

  assert.deepEqual(entries, before);
});
