/* Tests for the Pareto chart's circle/square composition-type encoding (OME-1852).
 *
 * A brand-new file rather than additions to leaderboard-logic.test.js / pareto-chart.test.js:
 * this unit's own fixtures and assertions live entirely here, so the two existing portal test
 * files are untouched by this change.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../../portal/leaderboard-logic.js");
const C = require("../../portal/pareto-chart.js");

// --- candidateKindLabel / isFusionCandidate (leaderboard-logic.js) -----------------------------

test("candidateKindLabel: a declared model reads Single model", () => {
  assert.equal(L.candidateKindLabel({ candidate_kind: "model" }), "Single model");
});

test("candidateKindLabel: a declared fusion reads Fusion", () => {
  assert.equal(L.candidateKindLabel({ candidate_kind: "fusion" }), "Fusion");
});

test("candidateKindLabel: anything else reads Unknown, never guessed into either shape", () => {
  // The server itself collapses pipeline/corrective_loop/self_corrective and anything
  // unrecognised to "unknown" (OME-1852), but the portal must fail the same way on its own if
  // it is ever handed something else — an older cached response, a future server value.
  assert.equal(L.candidateKindLabel({ candidate_kind: "unknown" }), "Unknown");
  assert.equal(L.candidateKindLabel({ candidate_kind: "pipeline" }), "Unknown");
  assert.equal(L.candidateKindLabel({}), "Unknown");
  assert.equal(L.candidateKindLabel(null), "Unknown");
  assert.equal(L.candidateKindLabel(undefined), "Unknown");
});

test("isFusionCandidate: true only for a declared fusion", () => {
  assert.equal(L.isFusionCandidate({ candidate_kind: "fusion" }), true);
  assert.equal(L.isFusionCandidate({ candidate_kind: "model" }), false);
  assert.equal(L.isFusionCandidate({ candidate_kind: "unknown" }), false);
  assert.equal(L.isFusionCandidate({}), false);
  assert.equal(L.isFusionCandidate(null), false);
});

// --- describePoint states the type in the accessible title text (pareto-chart.js) --------------

function chartEntry(spec_id, score, cost, frontier, candidate_kind) {
  var entry = {
    spec_id: spec_id,
    score: score,
    run_cost_usd: cost,
    on_pareto_frontier: frontier,
  };
  if (candidate_kind !== undefined) entry.candidate_kind = candidate_kind;
  return entry;
}

function describe(point) {
  return C.describePoint(point, L.formatCost, function (score) { return String(score); });
}

test("describePoint states the declared type for a priced single model and a fusion", () => {
  const model = C.buildChartModel([
    chartEntry("solo", 0.5, "2.000000", true, "model"),
    chartEntry("fused", 0.9, "4.000000", true, "fusion"),
  ]);

  assert.ok(model);
  const bySpec = {};
  model.priced.forEach((point) => { bySpec[point.specId] = point; });

  assert.equal(
    describe(bySpec.solo),
    "solo: score 0.5, cost $2.000000 (shown as $2.00); type Single model; " +
      "on the Pareto frontier",
  );
  assert.equal(
    describe(bySpec.fused),
    "fused: score 0.9, cost $4.000000 (shown as $4.00); type Fusion; " +
      "on the Pareto frontier; highest score",
  );
});

test("describePoint states Unknown for a missing or unrecognised type, never Fusion", () => {
  const model = C.buildChartModel([
    chartEntry("no-declaration", 0.5, "2.000000", true),
    chartEntry("a-pipeline", 0.6, "3.000000", true, "pipeline"),
  ]);

  assert.ok(model);
  const bySpec = {};
  model.priced.forEach((point) => { bySpec[point.specId] = point; });

  assert.equal(
    describe(bySpec["no-declaration"]),
    "no-declaration: score 0.5, cost $2.000000 (shown as $2.00); type Unknown; " +
      "on the Pareto frontier",
  );
  assert.equal(
    describe(bySpec["a-pipeline"]),
    "a-pipeline: score 0.6, cost $3.000000 (shown as $3.00); type Unknown; " +
      "on the Pareto frontier; highest score",
  );
});

test("describePoint states the type for an unpriced row too", () => {
  const model = C.buildChartModel([
    chartEntry("priced", 0.5, "2.000000", true),
    chartEntry("unpriced-fusion", 0.9, null, false, "fusion"),
  ]);

  assert.ok(model);
  assert.equal(model.unpriced.length, 1);
  const text = describe(model.unpriced[0]);
  assert.equal(
    text,
    "unpriced-fusion: score 0.9, cost not reported; type Fusion; highest score; " +
      "excluded from Pareto comparison",
  );
});
