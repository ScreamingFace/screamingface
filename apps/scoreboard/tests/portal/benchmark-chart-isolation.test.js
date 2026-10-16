/* OME-1595 review round 2: a chart failure must never block the leaderboard table.
 *
 * Loads the REAL leaderboard-logic.js, main.js and benchmark.js into a `vm` context behind a
 * small fake DOM (the paper-link.test.js approach), with a Pareto chart module whose render
 * throws. The table, its rows and the summary must still appear; only the chart is hidden.
 *
 * WHY this is load-bearing: benchmark.js used to render the chart before the table head and
 * body and before unhiding the table, so one bad tick computation left a valid board stuck on
 * "Loading…" with its leaderboard hidden.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PORTAL = path.join(__dirname, "..", "..", "portal");
const PAGE = "https://board.test/benchmark.html?id=hle";

function makeNode(tag) {
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
      contains() {
        return false;
      },
    },
    get firstChild() {
      return this.children[0] || null;
    },
    appendChild(child) {
      // A fragment hands over its children, as in the DOM.
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
    setAttribute(name, value) {
      this.attrs[name] = String(value);
    },
    getAttribute(name) {
      return name in this.attrs ? this.attrs[name] : null;
    },
    removeAttribute(name) {
      delete this.attrs[name];
    },
    addEventListener() {},
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
  };
  return node;
}

function entry(spec_id, score, cost, frontier) {
  return {
    rank: 1,
    spec_id,
    score,
    run_cost_usd: cost,
    on_pareto_frontier: frontier,
    submitted_at: "2026-10-06T12:00:00Z",
    authors: ["alice"],
    ran_with_providers: ["openai"],
    latest_submission_id: "11111111-1111-1111-1111-111111111111",
  };
}

// Renders benchmark.html's script against `entries` with the given chart module, and returns the
// fake page nodes once the page has settled.
async function renderBoard(entries, chartModule) {
  const ids = {};
  const byId = (id) => {
    if (!ids[id]) {
      ids[id] = makeNode("div");
      ids[id].id = id;
    }
    return ids[id];
  };
  // The breadcrumb's nav and its separator are read through the DOM tree.
  const crumbNav = makeNode("nav");
  crumbNav.previousElementSibling = makeNode("span");
  crumbNav.appendChild(byId("crumb-benchmark"));
  byId("leaderboard-wrap").hidden = true;
  byId("pareto-chart-section").hidden = true;

  const bodies = {
    "/v1/benchmarks": { benchmarks: [{ id: "hle", display_name: "HLE" }] },
    "/v1/leaderboard/hle?top=50": {
      benchmark: { id: "hle", display_name: "HLE", description: "" },
      entries,
    },
  };
  const context = {
    URL,
    URLSearchParams,
    Promise,
    JSON,
    Math,
    Number,
    setTimeout,
    navigator: {},
    console: { log() {}, warn() {}, error() {} },
    SFParetoChart: chartModule,
    document: {
      readyState: "complete",
      title: "",
      createElement: makeNode,
      createElementNS: (_ns, tag) => makeNode(tag),
      createDocumentFragment: () => makeNode("#fragment"),
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
    location: { href: PAGE, search: "?id=hle", protocol: "https:", origin: "https://board.test" },
  };
  context.window = context;
  context.self = context;
  vm.createContext(context);
  for (const file of ["leaderboard-logic.js", "main.js", "benchmark.js"]) {
    vm.runInContext(fs.readFileSync(path.join(PORTAL, file), "utf8"), context, { filename: file });
  }
  await new Promise((resolve) => setTimeout(resolve, 25));
  return ids;
}

const throwingChart = {
  render() {
    throw new RangeError("toFixed() digits argument must be between 0 and 100");
  },
};

const ENTRIES = [entry("cheap", 1e-101, "1.000000", true), entry("dear", 0, "2.000000", false)];

test("a throwing chart still leaves the leaderboard table rendered and visible", async () => {
  const page = await renderBoard(ENTRIES, throwingChart);

  assert.equal(page["leaderboard-wrap"].hidden, false, "the table is unhidden");
  assert.equal(page["leaderboard-body"].children.length, 2, "one row per entry");
  assert.ok(page["leaderboard-head"].children.length > 0, "the head is rendered");
  assert.equal(page["leaderboard-summary"].hidden, false, "the summary is visible");
  assert.equal(page["leaderboard-legend"].hidden, false, "the legend is visible");
});

test("a throwing chart hides only the chart section", async () => {
  const page = await renderBoard(ENTRIES, throwingChart);

  assert.equal(page["pareto-chart-section"].hidden, true);
  assert.equal(page["pareto-chart"].children.length, 0, "no half-drawn chart is left behind");
});

test("a throwing chart does not leave the status on Loading", async () => {
  const page = await renderBoard(ENTRIES, throwingChart);
  const loading = await renderBoard(ENTRIES, { render() {} });

  // The status region ends in the same state as on a board whose chart renders fine.
  assert.equal(page["leaderboard-status"].hidden, loading["leaderboard-status"].hidden);
  assert.equal(page["leaderboard-status"].textContent, loading["leaderboard-status"].textContent);
  assert.deepEqual(
    page["leaderboard-status"].children.map((child) => child.textContent),
    loading["leaderboard-status"].children.map((child) => child.textContent)
  );
});
