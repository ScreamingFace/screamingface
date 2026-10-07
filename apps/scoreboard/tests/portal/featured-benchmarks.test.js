/* Tests for the curated benchmark shortlist surfaced first across the portal.
 *
 * Runs on Node's built-in runner — `node --test tests/portal/featured-benchmarks.test.js` — so it
 * needs no package.json, no dependency, no toolchain. NAMED EXPLICITLY in the scoreboard card's
 * gate list and in scoreboard-tests.yml (same reasoning as the sibling portal suites, OME-798):
 * `node --test <dir>` fails on Node 24 and both glob forms exit 0 "pass 0" when nothing matches,
 * so a renamed/unlisted file would leave a permanently green gate covering nothing.
 *
 * WHY a dedicated file rather than appended to leaderboard-logic.test.js: the append-only gate
 * (sdlc rule 5) cannot parse a .js test to prove an edit is additive, so it fails closed on ANY
 * modification to an existing .js test artifact; a brand-new file is an unambiguous addition. The
 * subject under test is the same module (leaderboard-logic.js) — these cover only the featured
 * shortlist (FEATURED_BENCHMARK_IDS + partitionFeatured).
 *
 * FEATURE: a short list of boards leads the benchmark tab strip and the index catalogue, so the
 * boards readers should land on are not buried in a flat wall of ~65 equal-weight links.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../../portal/leaderboard-logic.js");

// A realistic catalog slice: two featured boards out of order, interleaved with non-featured
// ones, to pin that partitionFeatured re-orders by the constant and never by input position.
function catalog() {
  return [
    { id: "agieval-aqua-rat", display_name: "AGIEval AQuA-RAT" },
    { id: "ifeval", display_name: "IFEval" },
    { id: "mmlu", display_name: "MMLU" },
    { id: "draco-3pass", display_name: "DRACO 3-Pass" },
    { id: "winogrande", display_name: "WinoGrande" },
  ];
}

test("FEATURED_BENCHMARK_IDS pins the agreed shortlist ids, in order", () => {
  // The requester said "healthbench"; the catalog has two HealthBench boards, so this guards
  // that the shortlist means Professional (NOT a bare "healthbench", which no board uses, and
  // NOT worst-30, which OME-1147 slates to hide). draco-3pass, not draco.
  assert.deepEqual(L.FEATURED_BENCHMARK_IDS, [
    "draco-3pass",
    "contracteval",
    "frontierscience",
    "healthbench-professional",
    "ifeval",
  ]);
});

test("partitionFeatured returns featured in constant order, not input order", () => {
  // INVARIANT: the tabs and the catalogue render in FEATURED_BENCHMARK_IDS order, not the order
  // the API happens to return. Input here has ifeval before draco-3pass; the constant has
  // draco-3pass first, so featured must come back [draco-3pass, ifeval].
  const { featured } = L.partitionFeatured(catalog());
  assert.deepEqual(
    featured.map((b) => b.id),
    ["draco-3pass", "ifeval"],
  );
});

test("partitionFeatured puts every non-featured board in rest, in input order", () => {
  const { rest } = L.partitionFeatured(catalog());
  assert.deepEqual(
    rest.map((b) => b.id),
    ["agieval-aqua-rat", "mmlu", "winogrande"],
  );
});

test("partitionFeatured never places a board in both lists", () => {
  const { featured, rest } = L.partitionFeatured(catalog());
  const restIds = new Set(rest.map((b) => b.id));
  for (const b of featured) {
    assert.equal(restIds.has(b.id), false, `${b.id} must not appear in both featured and rest`);
  }
});

test("partitionFeatured skips a featured id the catalog does not return, never fabricates it", () => {
  // INVARIANT: fail-open like listedBenchmarks — a renamed/retired featured board drops out of
  // the shortlist rather than rendering a dead tab. Only draco-3pass of the five is present here;
  // the other four are absent and must simply not appear (featured is never padded).
  const { featured } = L.partitionFeatured([
    { id: "mmlu", display_name: "MMLU" },
    { id: "draco-3pass", display_name: "DRACO 3-Pass" },
  ]);
  assert.deepEqual(
    featured.map((b) => b.id),
    ["draco-3pass"],
  );
});

test("partitionFeatured tolerates a non-array and leaves its input alone", () => {
  assert.deepEqual(L.partitionFeatured(undefined), { featured: [], rest: [] });
  assert.deepEqual(L.partitionFeatured(null), { featured: [], rest: [] });

  const input = catalog();
  L.partitionFeatured(input);
  assert.equal(input.length, 5, "the caller's array must not be partitioned in place");
  assert.equal(input[0].id, "agieval-aqua-rat", "input order must be preserved for the caller");
});

// --- filterBenchmarks: the "More benchmarks" search box ---------------------------------------
// The tab strip's overflow dropdown lists every non-featured board, scrollable, with a search
// field; this pure helper is the filter behind that field.

test("filterBenchmarks matches on display_name, case-insensitively", () => {
  const out = L.filterBenchmarks(catalog(), "mm");
  assert.deepEqual(out.map((b) => b.id), ["mmlu"]);
  assert.deepEqual(L.filterBenchmarks(catalog(), "MMLU").map((b) => b.id), ["mmlu"]);
});

test("filterBenchmarks also matches on the id slug", () => {
  const out = L.filterBenchmarks(catalog(), "winogrande");
  assert.deepEqual(out.map((b) => b.id), ["winogrande"]);
});

test("filterBenchmarks returns a non-matching query's empty result", () => {
  assert.deepEqual(L.filterBenchmarks(catalog(), "zzz-nothing"), []);
});

test("filterBenchmarks returns the whole list (a copy) for an empty or whitespace query", () => {
  const input = catalog();
  const all = L.filterBenchmarks(input, "   ");
  assert.deepEqual(all.map((b) => b.id), input.map((b) => b.id));
  assert.notEqual(all, input, "must be a copy, not the caller's array");
  assert.deepEqual(L.filterBenchmarks(input, "").map((b) => b.id), input.map((b) => b.id));
});

test("filterBenchmarks tolerates a non-array and a non-string query", () => {
  assert.deepEqual(L.filterBenchmarks(undefined, "x"), []);
  assert.deepEqual(L.filterBenchmarks(catalog(), null).length, catalog().length);
});
