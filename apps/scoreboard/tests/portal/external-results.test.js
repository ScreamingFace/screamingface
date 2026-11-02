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
  byId("external-results").hidden = true;
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
    if (!fs.existsSync(path.join(PORTAL, file))) continue;
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
const text = (root) => nodes(root).map((n) => n.textContent || "").join(" ");
const rows = (page) => page.ids["external-results-body"].children;

test("external-only board displays source-backed rows without ranked results", async () => {
  const page = await renderBoard([], [BASELINE, { ...BASELINE, model_name: "GPT-3.5", score: 0.704 }]);
  assert.equal(page.ids["external-results"].hidden, false);
  assert.equal(rows(page).length, 2);
  assert.match(text(rows(page)[0]), /GPT-4o/);
  assert.match(text(rows(page)[0]), /0\.932/);
  assert.match(text(rows(page)[0]), /External · Not reproducible/);
  assert.match(text(rows(page)[0]), /Nov 2, 2026/);
  assert.match(text(rows(page)[0]), /Same questions; different prompts/);
  const links = nodes(rows(page)[0]).filter((n) => n.tag === "a");
  assert.equal(links.length, 1);
  assert.equal(links[0].attrs.href, BASELINE.source_url);
  assert.match(links[0].attrs.rel, /noopener/);
  assert.equal(nodes(rows(page)[0]).filter((n) => n.tag === "button").length, 0);
  assert.equal(page.ids["leaderboard-body"].children.length, 0);
  assert.equal(page.ids["leaderboard-summary"].hidden, true);
  assert.equal(page.charts.at(-1).length, 0);
});

test("higher external score does not change ranked rows, best score or charts", async () => {
  const ranked = entry("measured", 0.5, "1.000000", true);
  const page = await renderBoard([ranked], [BASELINE]);
  assert.equal(rows(page).length, 1);
  assert.equal(page.ids["leaderboard-body"].children.length, 1);
  assert.equal(page.ids["summary-best"].textContent, "0.5");
  assert.equal(page.ids["summary-specs"].textContent, "1");
  assert.equal(page.charts.at(-1).length, 1);
  assert.equal(page.charts.at(-1)[0].spec_id, "measured");
  assert.equal(rows(page)[0].className, "external-result");
  assert.ok(!nodes(rows(page)[0]).some((n) => /sota|pareto-mark|copy/.test(n.className || "")));
});

for (const baselines of [undefined, null, [], {}]) {
  test("missing/empty/non-list baselines leave the external section hidden: " + JSON.stringify(baselines), async () => {
    const page = await renderBoard([], baselines);
    assert.equal(page.ids["external-results"].hidden, true);
  });
}

test("failed leaderboard request leaves external results hidden", async () => {
  const page = await renderBoard([], [BASELINE], true);
  assert.equal(page.ids["external-results"].hidden, true);
});

test("source text is inert and unsafe or missing URLs never become links", async () => {
  for (const url of ["javascript:alert(1)", "data:text/html,bad", "/relative", "https://", null]) {
    const page = await renderBoard([], [{ ...BASELINE, source_url: url, model_name: "<img onerror=alert(1)>", metadata: { comparison_note: "<script>bad()</script>" } }]);
    assert.match(text(rows(page)[0]), /<img onerror=alert\(1\)>/);
    assert.match(text(rows(page)[0]), /<script>bad\(\)<\/script>/);
    assert.ok(!nodes(rows(page)[0]).some((n) => ["a", "img", "script"].includes(n.tag)));
    assert.match(text(rows(page)[0]), /Source unavailable/);
  }
});

test("unknown details stay unknown and finite native scores are not percentages", async () => {
  const page = await renderBoard([], [0, -0.25, 12].map((score) => ({ ...BASELINE, score, imported_at: null, metadata: null })));
  assert.equal(rows(page).length, 3);
  assert.deepEqual(rows(page).map((r) => r.children[1].textContent), ["0", "-0.25", "12"]);
  assert.match(text(rows(page)[0]), /Evaluation details not provided/);
  assert.match(text(rows(page)[0]), /—/);
});

test("malformed rows are skipped without hiding valid external or community results", async () => {
  const page = await renderBoard([entry("valid", 1, null, false)], [null, {}, { ...BASELINE, score: "0.9" }, { ...BASELINE, model_name: null }, BASELINE]);
  assert.equal(rows(page).length, 1);
  assert.equal(page.ids["leaderboard-body"].children.length, 1);
});

test("a repeat render clears old external rows and hides an empty section", async () => {
  const page = await renderBoard([], [BASELINE]);
  page.context.SFExternalResults.render([BASELINE]);
  assert.equal(rows(page).length, 1);
  page.context.SFExternalResults.render([]);
  assert.equal(rows(page).length, 0);
  assert.equal(page.ids["external-results"].hidden, true);
});

test("page supplies a labelled scrollable table and loads renderer before benchmark", () => {
  const html = fs.readFileSync(path.join(PORTAL, "benchmark.html"), "utf8");
  assert.match(html, /id="external-results"[^>]*hidden/);
  assert.match(html, /aria-label="External results, scrollable"/);
  assert.match(html, /<table aria-label="External results">/);
  assert.ok(html.indexOf('src="external-results.js"') < html.indexOf('src="benchmark.js"'));
  assert.ok(html.includes('src="external-results.js"'));
});
