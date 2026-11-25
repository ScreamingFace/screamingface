/* Tests for the Pareto chart's circle/square/triangle composition-type encoding (OME-1852).
 *
 * A brand-new file rather than additions to leaderboard-logic.test.js / pareto-chart.test.js:
 * this unit's own fixtures and assertions live entirely here, so the two existing portal test
 * files are untouched by this change.
 *
 * Review round 2 (P2 x2) added:
 *   - a rendered-SVG regression that calls the real renderChart and inspects the actual
 *     <circle>/<rect>/<polygon> marker element, not only the predicate/title-string level the
 *     tests below already covered;
 *   - a full-page regression (the benchmark-chart-isolation.test.js vm-context approach) proving
 *     the per-row screen-reader text that names a row's composition kind actually reaches the
 *     table, since the chart itself stays `aria-hidden` and is not a screen-reader data source.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const L = require("../../portal/leaderboard-logic.js");
const C = require("../../portal/pareto-chart.js");

const PORTAL = path.join(__dirname, "..", "..", "portal");

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

test("isUnknownCandidate: true for anything other than a declared model or fusion", () => {
  assert.equal(L.isUnknownCandidate({ candidate_kind: "model" }), false);
  assert.equal(L.isUnknownCandidate({ candidate_kind: "fusion" }), false);
  assert.equal(L.isUnknownCandidate({ candidate_kind: "pipeline" }), true);
  assert.equal(L.isUnknownCandidate({ candidate_kind: "corrective_loop" }), true);
  assert.equal(L.isUnknownCandidate({}), true);
  assert.equal(L.isUnknownCandidate(null), true);
  assert.equal(L.isUnknownCandidate(undefined), true);
});

test("isFusionCandidate and isUnknownCandidate never both claim the same entry", () => {
  for (const kind of ["model", "fusion", "pipeline", undefined, "garbage"]) {
    const entry = kind === undefined ? {} : { candidate_kind: kind };
    assert.ok(
      !(L.isFusionCandidate(entry) && L.isUnknownCandidate(entry)),
      "never both true for candidate_kind: " + String(kind)
    );
  }
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

// --- renderChart draws the actual marker element (review round 2, P2) --------------------------
//
// Every test above checks the pure model (predicates, title strings) but never calls into the
// DOM-touching half of pareto-chart.js, so a regression that drew the wrong shape — or kept
// drawing Unknown as a circle, the one mislabeling this ticket forbids — could pass every test
// above while the actual <circle>/<rect>/<polygon> choice was wrong. This section renders the
// real SVG tree (a minimal node stub standing in for the DOM, scoped to this test only) and reads
// the marker element's own tag name back.

function svgStubNode(tag) {
  return {
    tag: tag,
    attrs: {},
    children: [],
    textContent: "",
    appendChild(child) { this.children.push(child); return child; },
    setAttribute(key, value) { this.attrs[key] = String(value); },
  };
}

// pareto-chart.js's svgElement() calls the bare identifier `document`, resolved from the
// process-global scope (there is no `window.` prefix inside the module) — so the stub has to be
// installed on Node's own `global.document` for the call to reach it, and removed straight after
// so no other test file sharing this process sees it.
function withStubSvgDocument(fn) {
  const had = Object.prototype.hasOwnProperty.call(global, "document");
  const previous = global.document;
  global.document = { createElementNS(_ns, tag) { return svgStubNode(tag); } };
  try {
    return fn();
  } finally {
    if (had) global.document = previous;
    else delete global.document;
  }
}

function pointGroupsOf(svg) {
  return svg.children.filter((node) => node.tag === "g" && node.attrs.class === "pareto-chart__point");
}

function titleTextOf(group) {
  const title = group.children.find((child) => child.tag === "title");
  return title ? title.textContent : "";
}

// The marker shape is the one child whose class names a *-point kind (frontier/dominated/
// unpriced); the optional leader-ring circle carries a different class suffix (-ring) and is
// excluded on purpose, since a leader row would otherwise make this helper return the ring's
// shape instead of the actual composition marker.
function markerTagFor(svg, specId) {
  const group = pointGroupsOf(svg).find((candidate) => titleTextOf(candidate).indexOf(specId + ":") === 0);
  assert.ok(group, "no rendered point found for " + specId);
  const shape = group.children.find((child) => {
    const cls = child.attrs.class || "";
    return cls.slice(-6) === "-point";
  });
  assert.ok(shape, "no marker shape found inside the point group for " + specId);
  return shape.tag;
}

test("renderChart draws a circle for a model, a square for a fusion, and a triangle for Unknown", () => {
  const model = C.buildChartModel([
    chartEntry("solo", 0.9, "1.000000", true, "model"),
    chartEntry("fused", 0.8, "2.000000", false, "fusion"),
    chartEntry("no-declaration", 0.5, "3.000000", false),
    chartEntry("a-pipeline", 0.4, "4.000000", false, "pipeline"),
  ]);
  assert.ok(model);

  const svg = withStubSvgDocument(() =>
    C.renderChart({ formatScore: String, formatCost: L.formatCost }, model)
  );

  assert.equal(markerTagFor(svg, "solo"), "circle");
  assert.equal(markerTagFor(svg, "fused"), "rect");
  assert.equal(markerTagFor(svg, "no-declaration"), "polygon");
  assert.equal(markerTagFor(svg, "a-pipeline"), "polygon");
});

test("renderChart's triangle for Unknown never reuses the single-model circle or fusion square tag", () => {
  const model = C.buildChartModel([
    chartEntry("anchor", 0.9, "1.000000", true, "model"),
    chartEntry("mystery", 0.5, "2.000000", false, "self_corrective"),
  ]);
  assert.ok(model);

  const svg = withStubSvgDocument(() =>
    C.renderChart({ formatScore: String, formatCost: L.formatCost }, model)
  );

  const unknownTag = markerTagFor(svg, "mystery");
  assert.equal(unknownTag, "polygon");
  assert.notEqual(unknownTag, "circle");
  assert.notEqual(unknownTag, "rect");
});

// --- the per-row screen-reader mapping actually reaches the table (review round 2, P2) ----------
//
// The chart stays `aria-hidden` (benchmark.html) and the table is the documented accessible data
// source, so the composition-kind text belongs on the row, not only in the chart's own SVG
// <title>. This loads the REAL leaderboard-logic.js, pareto-chart.js, main.js and benchmark.js
// into a `vm` context behind a small fake DOM (the benchmark-chart-isolation.test.js approach) and
// reads back what a screen reader would actually encounter in each row.

function pageStubNode(tag) {
  const node = {
    tag,
    children: [],
    attrs: {},
    style: {},
    className: "",
    hidden: false,
    textContent: "",
    parentNode: null,
    previousElementSibling: null,
    classList: {
      add() {},
      remove() {},
      toggle() {},
      contains() { return false; },
    },
    get firstChild() { return this.children[0] || null; },
    appendChild(child) {
      if (child.tag === "#fragment") {
        child.children.slice().forEach((grandchild) => this.appendChild(grandchild));
        child.children = [];
        return child;
      }
      this.children.push(child);
      child.parentNode = this;
      return child;
    },
    insertBefore(child, ref) {
      const at = this.children.indexOf(ref);
      this.children.splice(at < 0 ? this.children.length : at, 0, child);
      child.parentNode = this;
      return child;
    },
    removeChild(child) {
      this.children.splice(this.children.indexOf(child), 1);
      return child;
    },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; },
    removeAttribute(name) { delete this.attrs[name]; },
    addEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  return node;
}

function rowEntry(spec_id, score, cost, frontier, candidate_kind) {
  const e = {
    rank: 1,
    spec_id: spec_id,
    score: score,
    run_cost_usd: cost,
    on_pareto_frontier: frontier,
    submitted_at: "2026-10-06T12:00:00Z",
    authors: ["alice"],
    ran_with_providers: ["openai"],
    latest_submission_id: "11111111-1111-1111-1111-111111111111",
  };
  if (candidate_kind !== undefined) e.candidate_kind = candidate_kind;
  return e;
}

// Renders benchmark.html's real scripts against `entries` and returns the fake page nodes once
// the page has settled.
async function renderBoardPage(entries) {
  const ids = {};
  const byId = (id) => {
    if (!ids[id]) {
      ids[id] = pageStubNode("div");
      ids[id].id = id;
    }
    return ids[id];
  };
  const crumbNav = pageStubNode("nav");
  crumbNav.previousElementSibling = pageStubNode("span");
  crumbNav.appendChild(byId("crumb-benchmark"));
  byId("leaderboard-wrap").hidden = true;
  byId("pareto-chart-section").hidden = true;

  const bodies = {
    "/v1/benchmarks": { benchmarks: [{ id: "hle", display_name: "HLE" }] },
    "/v1/leaderboard/hle?top=50": {
      benchmark: { id: "hle", display_name: "HLE", description: "" },
      entries: entries,
    },
  };
  const context = {
    URL: URL,
    URLSearchParams: URLSearchParams,
    Promise: Promise,
    JSON: JSON,
    Math: Math,
    Number: Number,
    setTimeout: setTimeout,
    navigator: {},
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: "complete",
      title: "",
      createElement: pageStubNode,
      createElementNS: (_ns, tag) => pageStubNode(tag),
      createDocumentFragment: () => pageStubNode("#fragment"),
      createTextNode: (text) => ({ textContent: String(text) }),
      getElementById: byId,
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
    },
    fetch: async (url) => {
      const key = url.replace("https://board.test", "");
      if (!(key in bodies)) return { ok: false, status: 404, text: async () => "" };
      return { ok: true, status: 200, text: async () => JSON.stringify(bodies[key]) };
    },
    location: {
      href: "https://board.test/benchmark.html?id=hle",
      search: "?id=hle",
      protocol: "https:",
      origin: "https://board.test",
    },
  };
  context.window = context;
  context.self = context;
  vm.createContext(context);
  for (const file of ["leaderboard-logic.js", "pareto-chart.js", "main.js", "benchmark.js"]) {
    vm.runInContext(fs.readFileSync(path.join(PORTAL, file), "utf8"), context, { filename: file });
  }
  await new Promise((resolve) => setTimeout(resolve, 25));
  return ids;
}

// specTd is the row's third <td> (rank, mark slot, then the spec-id cell carrying both the
// highest-score and composition-kind sr-only text).
function srOnlyTextOf(row) {
  const specTd = row.children[2];
  return specTd.children
    .filter((child) => child.className === "sr-only")
    .map((span) => span.textContent)
    .join("");
}

test("every row's composition kind reaches the table as screen-reader-only text", async () => {
  const entries = [
    rowEntry("solo-model", 0.9, "1.000000", true, "model"),
    rowEntry("fused", 0.8, "2.000000", false, "fusion"),
    rowEntry("mystery", 0.5, "3.000000", false, undefined),
  ];
  const page = await renderBoardPage(entries);
  const rows = page["leaderboard-body"].children;
  assert.equal(rows.length, 3);

  // "solo-model" also carries the highest-score sr-only text (0.9 is the board's top score),
  // so its mapping check doubles as proof the two sr-only spans compose rather than collide.
  assert.equal(srOnlyTextOf(rows[0]), " (highest score) (single model)");
  assert.equal(srOnlyTextOf(rows[1]), " (fusion)");
  assert.equal(srOnlyTextOf(rows[2]), " (unknown)");
});

test("a row's composition kind is stated even for the common single-model case, not omitted", () => {
  // Omitting the text on the "model" case (treating it as the unmarked default, the way the
  // Pareto-frontier mark only appears when true) would read to a screen reader as "no
  // information recorded" rather than "confirmed single model" — those are different claims,
  // and only the explicit text makes the right one.
  assert.equal(L.candidateKindLabel({ candidate_kind: "model" }), "Single model");
  assert.notEqual(L.candidateKindLabel({ candidate_kind: "model" }), "");
});
