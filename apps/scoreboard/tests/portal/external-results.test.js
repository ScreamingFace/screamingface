/* E20: exercise the real page with external and community results. */
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
    listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
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

// Render the real page scripts and wait for the API promises to settle.
async function renderBoard(entries, baselines, fail = false) {
  const ids = {};
  const charts = [];
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
      baselines,
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
    SFParetoChart: { render(options) { charts.push(options.entries); } },
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
      if (fail && key.includes("/leaderboard/")) return { ok: false, status: 503, text: async () => "" };
      if (!(key in bodies)) return { ok: false, status: 404, text: async () => "" };
      return { ok: true, status: 200, text: async () => JSON.stringify(bodies[key]) };
    },
    location: { href: PAGE, search: "?id=hle", protocol: "https:", origin: "https://board.test" },
  };
  context.window = context;
  context.self = context;
  vm.createContext(context);
  for (const file of ["leaderboard-logic.js", "main.js", "external-results.js", "benchmark.js"]) {
    vm.runInContext(fs.readFileSync(path.join(PORTAL, file), "utf8"), context, { filename: file });
  }
  await new Promise((resolve) => setTimeout(resolve, 25));
  return { ids, charts, context };
}



const BASELINE = {
  model_name: "GPT-4o", score: 0.932, source: "agieval-authors-zero-shot-dev-e20",
  source_url: "https://example.org/results", imported_at: "2026-11-02T12:08:48Z",
  metadata: { comparison_note: "Same questions; different prompts and answer extraction." },
};
const nodes = (root) => [root, ...(root.children || []).flatMap(nodes)];
const rows = (page) => page.ids["leaderboard-body"].children;
const cell = (row, index) => row.children[index];
const modelName = (row) => cell(row, 2).children[0].textContent;

function sortBy(page, label) {
  const button = nodes(page.ids["leaderboard-head"]).find((n) =>
    n.tag === "button" && n.children[0].textContent === label + " ");
  button.listeners.click();
}

test("external-only board uses normal ranked table cells and source instead of copy", async () => {
  const page = await renderBoard([], [BASELINE, { ...BASELINE, model_name: "GPT-3.5", score: 0.704 }]);
  assert.equal(rows(page).length, 2);
  const first = rows(page)[0];
  assert.equal(first.children.length, 9);
  assert.equal(first.className, "external-result");
  assert.equal(cell(first, 0).textContent, "1");
  assert.equal(cell(rows(page)[1], 0).textContent, "2");
  assert.equal(modelName(first), "GPT-4o");
  assert.equal(cell(first, 5).children[0].children[0].textContent, "0.932");
  assert.equal(cell(first, 2).children[1].className, "sr-only");
  assert.equal(cell(first, 2).children[1].textContent, "External result; not reproducible.");
  assert.equal(cell(first, 2).title, "External result; not reproducible. " + BASELINE.metadata.comparison_note);
  assert.equal(cell(first, 7).textContent, page.context.ScorePortal.formatDate(BASELINE.imported_at));
  assert.equal(cell(first, 7).title, "Imported on " + BASELINE.imported_at);
  for (const index of [3, 4, 6]) assert.equal(cell(first, index).textContent, "—");
  const link = cell(first, 8).children[0];
  assert.equal(link.tag, "a");
  assert.equal(link.attrs.href, BASELINE.source_url);
  assert.equal(link.attrs.rel, "noopener noreferrer");
  assert.equal(link.attrs.target, "_blank");
  assert.equal(link.textContent, "Original result ↗");
  assert.equal(link.attrs["aria-label"], "Original result for GPT-4o (opens in a new tab)");
  assert.equal(nodes(first).filter((n) => n.tag === "button").length, 0);
  assert.equal(page.ids["leaderboard-status"].hidden, true);
  assert.equal(page.ids["summary-best"].textContent, "0.932");
  assert.equal(page.ids["summary-specs"].textContent, "2");
  assert.equal(page.charts.at(-1).length, 0);
});

test("mixed rows share score-based ranks while cost charts contain only community runs", async () => {
  const measured = entry("measured", 0.8, "1.000000", true);
  const page = await renderBoard([measured], [BASELINE, { ...BASELINE, model_name: "GPT-3.5", score: 0.704 }]);
  assert.deepEqual(rows(page).map(modelName), ["GPT-4o", "measured", "GPT-3.5"]);
  assert.deepEqual(rows(page).map((r) => cell(r, 0).textContent), ["1", "2", "3"]);
  assert.equal(rows(page)[0].className, "external-result");
  assert.equal(rows(page)[1].className, "");
  assert.equal(page.ids["summary-best"].textContent, "0.932");
  assert.equal(page.ids["summary-specs"].textContent, "3");
  assert.equal(page.charts.at(-1).length, 1);
  assert.equal(page.charts.at(-1)[0].spec_id, "measured");
  assert.equal(measured.rank, 1, "API data must not be mutated");
  sortBy(page, "Score");
  assert.deepEqual(rows(page).map(modelName), ["GPT-3.5", "measured", "GPT-4o"]);
  assert.deepEqual(rows(page).map((r) => cell(r, 0).textContent), ["3", "2", "1"]);
  sortBy(page, "Submission");
  assert.deepEqual(rows(page).map(modelName), ["GPT-3.5", "GPT-4o", "measured"]);
  sortBy(page, "Rank");
  assert.deepEqual(rows(page).map(modelName), ["GPT-4o", "measured", "GPT-3.5"]);
  sortBy(page, "Cost");
  assert.equal(modelName(rows(page)[0]), "measured", "unknown external costs do not sort as zero");
});

test("combined top 50 excludes low external scores whose global rank is not known", async () => {
  const measured = Array.from({ length: 50 }, (_, i) => entry("run-" + i, 100 - i, "1.000000", false));
  const page = await renderBoard(measured, [{ ...BASELINE, score: 101 }, { ...BASELINE, model_name: "low", score: -1 }]);
  assert.equal(rows(page).length, 50);
  assert.equal(modelName(rows(page)[0]), "GPT-4o");
  assert.equal(modelName(rows(page)[49]), "run-48");
  assert.equal(cell(rows(page)[49], 0).textContent, "50");
  assert.ok(!rows(page).some((r) => modelName(r) === "low"));
});

test("equal scores keep community order before external rows", async () => {
  const page = await renderBoard([entry("first", 1, null, false), entry("second", 1, null, false)], [{ ...BASELINE, score: 1 }]);
  assert.deepEqual(rows(page).map(modelName), ["first", "second", "GPT-4o"]);
  assert.deepEqual(rows(page).map((r) => cell(r, 0).textContent), ["1", "2", "3"]);
});

test("imports cannot displace fetched community frontier points from the cost chart", async () => {
  const measured = Array.from({ length: 50 }, (_, i) =>
    entry("run-" + i, 0.9 - i / 100, String(50 - i), true));
  const withoutImports = await renderBoard(measured, []);
  const mixed = await renderBoard(measured, [BASELINE]);
  assert.equal(rows(mixed).length, 50);
  assert.equal(modelName(rows(mixed)[49]), "run-48");
  assert.deepEqual(
    Array.from(mixed.charts.at(-1), (row) => row.spec_id),
    Array.from(withoutImports.charts.at(-1), (row) => row.spec_id),
  );
  assert.equal(mixed.charts.at(-1)[49].on_pareto_frontier, true);

  const importsOnlyInTable = await renderBoard(measured, Array.from({ length: 50 }, (_, i) =>
    ({ ...BASELINE, model_name: "external-" + i, score: 1 })));
  assert.ok(rows(importsOnlyInTable).every((row) => row.className === "external-result"));
  assert.equal(importsOnlyInTable.charts.at(-1).length, 50);
});

test("comparison notes are readable through a native disclosure, not just a tooltip", async () => {
  const page = await renderBoard([], [BASELINE]);
  const model = cell(rows(page)[0], 2);
  const details = model.children.find((node) => node.tag === "details");
  assert.ok(details, "provide a disclosure usable by touch and keyboard");
  assert.equal(details.children[0].tag, "summary");
  assert.equal(details.children[0].textContent, "Comparison");
  assert.equal(details.children[1].textContent, BASELINE.metadata.comparison_note);
  assert.equal(details.children[1].attrs["aria-hidden"], undefined);
  for (const note of [null, "", "  ", 123]) {
    const empty = await renderBoard([], [{ ...BASELINE, metadata: { comparison_note: note } }]);
    assert.ok(!nodes(rows(empty)[0]).some((node) => node.tag === "details"));
  }
});

for (const baselines of [undefined, null, [], {}]) {
  test("missing/empty/non-list baselines preserve the ordinary empty board: " + JSON.stringify(baselines), async () => {
    const page = await renderBoard([], baselines);
    assert.equal(rows(page).length, 0);
    assert.equal(page.ids["leaderboard-summary"].hidden, true);
  });
}

test("failed leaderboard request does not render external rows", async () => {
  const page = await renderBoard([], [BASELINE], true);
  assert.equal(page.ids["leaderboard-wrap"].hidden, true);
});

test("unsafe sources and markup stay inert in their exact cells", async () => {
  for (const url of ["javascript:alert(1)", "data:text/html,bad", "/relative", "https://", null]) {
    const model = "<img onerror=alert(1)>";
    const note = "<script>bad()</script>";
    const page = await renderBoard([], [{ ...BASELINE, source_url: url, model_name: model, metadata: { comparison_note: note } }]);
    const row = rows(page)[0];
    assert.equal(modelName(row), model);
    assert.equal(cell(row, 2).title, "External result; not reproducible. " + note);
    assert.ok(!nodes(row).some((n) => ["a", "img", "script"].includes(n.tag)));
    assert.equal(cell(row, 8).textContent, "—");
  }
});

test("unknown fields stay unknown and finite scores keep their native scale", async () => {
  const page = await renderBoard([], [0, -0.25, 12].map((score) => ({ ...BASELINE, score, imported_at: null, metadata: null })));
  assert.deepEqual(rows(page).map((r) => cell(r, 5).children[0].children[0].textContent), ["12", "0", "-0.25"]);
  assert.equal(cell(rows(page)[0], 7).textContent, "—");
  assert.equal(cell(rows(page)[0], 2).title, "External result; not reproducible.");
});

test("malformed rows do not hide valid rows", async () => {
  const page = await renderBoard([entry("valid", 1, null, false)], [null, {}, { ...BASELINE, score: "0.9" }, { ...BASELINE, model_name: null }, { ...BASELINE, model_name: "  " }, BASELINE]);
  assert.deepEqual(rows(page).map(modelName), ["valid", "GPT-4o"]);
});
