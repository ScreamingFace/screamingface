/* Tests for the Reproduce button in the board's Run column.
 *
 * Runs on Node's built-in runner, named explicitly in the scoreboard gate line and in
 * scoreboard-tests.yml like the sibling portal suites. The pure decisions (which id, what text) are
 * required from leaderboard-logic.js; the rendering loads the REAL main.js, leaderboard-logic.js
 * and benchmark.js into a `vm` context behind a small fake DOM, so what is asserted is what ships.
 *
 * The button copies the Python that replays a published run from its pinned cache. It appears
 * only when the row names a pinned cache AND the page's switch is on; the switch ships off until
 * the SDK release that understands `evaluate(pinned_cache=...)`.
 *
 * Every check compares whole values: exact strings, node lists, attribute values.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const L = require("../../portal/leaderboard-logic.js");

const PORTAL = path.join(__dirname, "..", "..", "portal");
const COPY = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b";
const SNIPPET = 'import screamingface as sf\nresult = sf.evaluate(pinned_cache="' + COPY + '")';
const HOVER = "Replays this run's recorded answers at $0 and checks the published score";

// --- the pure decisions --------------------------------------------------------------------------

test("the snippet is exactly the two lines the SDK runs", () => {
  assert.equal(L.reproduceSnippet(COPY), SNIPPET);
});

test("a row offers its pinned cache only when the switch is on", () => {
  assert.equal(L.reproduceCache({ pinned_cache: COPY }, true), COPY);
  assert.equal(L.reproduceCache({ pinned_cache: COPY }, false), null);
});

test("a row without a usable pinned cache offers nothing, switch on or off", () => {
  for (const value of [undefined, null, "", 7, {}, [COPY], true]) {
    const entry = value === undefined ? {} : { pinned_cache: value };
    assert.equal(L.reproduceCache(entry, true), null, String(value));
  }
});

// --- the rendering -------------------------------------------------------------------------------

function makeNode(tag) {
  const listeners = {};
  const node = {
    tag,
    children: [],
    attrs: {},
    className: "",
    hidden: false,
    textContent: "",
    title: "",
    type: "",
    style: {},
    parentNode: null,
    previousElementSibling: null,
    classList: { remove() {}, add() {} },
    get firstChild() {
      return this.children[0] || null;
    },
    appendChild(child) {
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
    addEventListener(name, handler) {
      listeners[name] = handler;
    },
    fire(name) {
      listeners[name]();
    },
    querySelector() {
      return null;
    },
  };
  return node;
}

function entry(spec, extra) {
  return {
    rank: 1,
    spec_id: spec,
    benchmark_revision: "rev-1",
    score: 0.5,
    total_questions: 4,
    ran_with_providers: ["openai"],
    submitted_at: "2026-10-15T00:00:00Z",
    submitted_by: "alice",
    authors: ["alice"],
    verified_by_screamingface: true,
    url4_expression: "url4://benchmark/" + spec,
    run_cost_usd: null,
    on_pareto_frontier: false,
    openness: "unidentified",
    ...extra,
  };
}

// Loads the three scripts against a fake page serving `entries`, waits for the page to settle, and
// returns the table body plus the page's window.
async function renderBoard(entries, clipboard) {
  const ids = {};
  const node = (id) => {
    if (!ids[id]) ids[id] = makeNode("div");
    return ids[id];
  };
  // The breadcrumb reads its parent and the parent's previous sibling.
  const crumb = node("crumb-benchmark");
  const nav = makeNode("nav");
  nav.previousElementSibling = makeNode("span");
  nav.appendChild(crumb);
  const bodies = {
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
    setTimeout,
    navigator: { clipboard },
    console,
    document: {
      readyState: "complete",
      title: "",
      createElement: makeNode,
      createTextNode: (text) => ({ textContent: String(text) }),
      getElementById: node,
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
  vm.createContext(context);
  for (const file of ["leaderboard-logic.js", "main.js", "benchmark.js"]) {
    vm.runInContext(fs.readFileSync(path.join(PORTAL, file), "utf8"), context, { filename: file });
  }
  await new Promise((resolve) => setTimeout(resolve, 25));
  return { body: ids["leaderboard-body"], page: context.SFBenchmarkPage };
}

function runCell(row) {
  return row.children[row.children.length - 1];
}

function buttons(cell) {
  const found = [];
  const walk = (n) => {
    if (n.tag === "button") found.push(n);
    (n.children || []).forEach(walk);
  };
  walk(cell);
  return found;
}

// OME-1655: the switch ships on, now that the SDK runs the snippet (`OME-1613`).
test("the switch ships on", async () => {
  const { page } = await renderBoard([]);

  assert.equal(page.SHOW_REPRODUCE_BUTTON, true);
});

test("the shipped board shows Reproduce under Copy on a captured row", async () => {
  const { body } = await renderBoard([entry("captured", { pinned_cache: COPY })]);

  const cell = runCell(body.children[0]);
  assert.deepEqual(buttons(cell).map((b) => b.textContent), ["Copy", "Reproduce"]);
});

test("with the switch off a captured row shows only the Copy button", async () => {
  const { page } = await renderBoard([]);

  // OME-1655: the switch is passed off explicitly, now that the shipped value is on.
  const cell = page.renderRunCell(entry("captured", { pinned_cache: COPY }), false);
  assert.deepEqual(buttons(cell).map((b) => b.textContent), ["Copy"]);
});

test("with the switch on, Reproduce stacks under Copy and carries the hover line", async () => {
  const { page } = await renderBoard([]);

  const cell = page.renderRunCell(entry("captured", { pinned_cache: COPY }), true);

  const [copy, reproduce] = buttons(cell);
  assert.deepEqual(buttons(cell).map((b) => b.textContent), ["Copy", "Reproduce"]);
  // Stacked: both buttons sit in one column container, Copy first.
  assert.equal(cell.children.length, 1);
  assert.equal(cell.children[0].className, "run-actions");
  assert.deepEqual(cell.children[0].children, [copy, reproduce]);
  assert.equal(reproduce.title, HOVER);
  assert.equal(reproduce.className, copy.className);
  assert.equal(reproduce.type, "button");
  // WCAG 2.5.3: the accessible name starts with the visible label, so voice control can say it.
  assert.equal(reproduce.getAttribute("aria-label"), "Reproduce captured: copy the replay code");
});

test("with the switch on, a row without a pinned cache keeps the single Copy button", async () => {
  const { page } = await renderBoard([]);

  const cell = page.renderRunCell(entry("uncaptured", {}), true);

  assert.deepEqual(buttons(cell).map((b) => b.textContent), ["Copy"]);
  assert.equal(cell.children[0].tag, "button");
});

test("Reproduce copies exactly the snippet and says so", async () => {
  const written = [];
  const clipboard = { writeText: async (text) => written.push(text) };
  const { page } = await renderBoard([], clipboard);
  const cell = page.renderRunCell(entry("captured", { pinned_cache: COPY }), true);
  const reproduce = buttons(cell)[1];

  reproduce.fire("click");
  await new Promise((resolve) => setTimeout(resolve, 5));

  assert.deepEqual(written, [SNIPPET]);
  assert.equal(reproduce.textContent, "✓ copied");
});

test("a refused clipboard says copy failed, like the Copy button", async () => {
  const clipboard = { writeText: async () => { throw new Error("denied"); } };
  const { page } = await renderBoard([], clipboard);
  const reproduce = buttons(page.renderRunCell(entry("captured", { pinned_cache: COPY }), true))[1];

  reproduce.fire("click");
  await new Promise((resolve) => setTimeout(resolve, 5));

  assert.equal(reproduce.textContent, "copy failed");
});
