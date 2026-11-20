/* OME-1708 (PR #1943 review): switching revisions never leaves an earlier revision on screen.
 *
 * Loads the REAL leaderboard-logic.js, main.js, revision-selector.js and benchmark.js into a `vm`
 * context behind a small fake DOM (the benchmark-chart-isolation.test.js approach). Every API
 * answer is held until the test releases it, so the tests can answer an earlier choice last.
 *
 * WHY this is load-bearing: without the load counter, a slow answer for Latest that arrives after
 * the reader chose Previous paints Latest's table and frontier under a selector naming Previous;
 * without the reset, Latest's numbers stay visible while Previous loads.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PORTAL = path.join(__dirname, "..", "..", "portal");
const ORIGIN = "https://board.test";
const LATEST = "a41c09e2aaaaaaaa";
const PREVIOUS = "32a91cf1e087f719";

function makeNode(tag) {
  const node = {
    tag,
    children: [],
    attrs: {},
    style: {},
    className: "",
    hidden: false,
    textContent: "",
    value: "",
    parentNode: null,
    previousElementSibling: null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    get firstChild() {
      return this.children[0] || null;
    },
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
    focus() {},
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  return node;
}

function entry(spec_id, score) {
  return {
    rank: 1,
    spec_id,
    score,
    run_cost_usd: "1.000000",
    on_pareto_frontier: false,
    submitted_at: "2026-10-06T12:00:00Z",
    authors: ["alice"],
    ran_with_providers: ["openai"],
    latest_submission_id: "11111111-1111-1111-1111-111111111111",
  };
}

function board(entries) {
  return { benchmark: { id: "hle", display_name: "HLE", description: "", revision: LATEST }, entries };
}

const REVISIONS = {
  benchmark_id: "hle",
  revisions: [
    {
      revision: LATEST,
      first_seen_at: "2026-11-17T12:00:00Z",
      first_seen_inferred: false,
      until: null,
      case_count: 100,
      case_count_inferred: false,
      result_count: 3,
      current: true,
    },
    {
      revision: PREVIOUS,
      first_seen_at: "2026-10-09T09:00:00Z",
      first_seen_inferred: false,
      until: "2026-11-17T12:00:00Z",
      case_count: 100,
      case_count_inferred: false,
      result_count: 1,
      current: false,
    },
  ],
};

const OPEN_FRONTIER = { frontier_available: true, open_share: 0.5, open_count: 1, closed_count: 1 };
const NO_FRONTIER = { frontier_available: false };

const LATEST_BOARD = "/v1/leaderboard/hle?top=50";
const PREVIOUS_BOARD = "/v1/leaderboard/hle?top=50&revision=" + PREVIOUS;
const LATEST_FRONTIER = "/v1/leaderboard/hle/frontier";
const PREVIOUS_FRONTIER = "/v1/leaderboard/hle/frontier?revision=" + PREVIOUS;
const LIST = "/v1/leaderboard/hle/revisions";

const tick = () => new Promise((resolve) => setTimeout(resolve, 5));

// Opens benchmark.html?id=hle with every board, frontier and revision-list answer held until
// `answer(path, body)` releases it.
function openPage(search) {
  const query = search || "?id=hle";
  const ids = {};
  const byId = (id) => {
    if (!ids[id]) {
      ids[id] = makeNode("div");
      ids[id].id = id;
    }
    return ids[id];
  };
  const crumbNav = makeNode("nav");
  crumbNav.previousElementSibling = makeNode("span");
  crumbNav.appendChild(byId("crumb-benchmark"));
  byId("leaderboard-wrap").hidden = true;
  byId("revision-selector").hidden = true;
  byId("revision-select").hidden = true;

  const waiting = {};
  const location = {
    href: ORIGIN + "/benchmark.html" + query,
    pathname: "/benchmark.html",
    search: query,
    hash: "",
    protocol: "https:",
    origin: ORIGIN,
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
    SFParetoChart: { render() {} },
    history: {
      replaceState(_state, _title, url) {
        const next = new URL(url, location.href);
        location.search = next.search;
        location.href = next.href;
      },
    },
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
    fetch: (url) => {
      const key = url.replace(ORIGIN, "");
      if (key === "/v1/benchmarks") {
        return Promise.resolve({ ok: true, status: 200, text: async () => '{"benchmarks":[]}' });
      }
      return new Promise((resolve) => {
        (waiting[key] = waiting[key] || []).push(resolve);
      });
    },
    location,
  };
  context.window = context;
  context.self = context;
  vm.createContext(context);
  for (const file of ["leaderboard-logic.js", "main.js", "revision-selector.js", "benchmark.js"]) {
    vm.runInContext(fs.readFileSync(path.join(PORTAL, file), "utf8"), context, { filename: file });
  }

  async function answer(key, body) {
    for (let i = 0; i < 40 && !(waiting[key] && waiting[key].length); i++) await tick();
    assert.ok(waiting[key] && waiting[key].length, "the page asked for " + key);
    waiting[key].shift()({ ok: true, status: 200, text: async () => JSON.stringify(body) });
    await tick();
  }

  async function fail(key, status) {
    for (let i = 0; i < 40 && !(waiting[key] && waiting[key].length); i++) await tick();
    assert.ok(waiting[key] && waiting[key].length, "the page asked for " + key);
    waiting[key].shift()({ ok: false, status, text: async () => "" });
    await tick();
  }

  // The reader picks a revision in the dropdown.
  function choose(revision) {
    const select = byId("revision-select");
    select.value = revision;
    select.onchange();
  }

  return { ids, answer, fail, choose, location };
}

test("a late answer for Latest never paints over Previous once Previous is chosen", async () => {
  const page = openPage();
  await page.answer(LIST, REVISIONS);
  page.choose(PREVIOUS);

  await page.answer(PREVIOUS_BOARD, board([entry("old", 0.4)]));
  await page.answer(LATEST_BOARD, board([entry("a", 0.9), entry("b", 0.8), entry("c", 0.7)]));

  assert.equal(page.ids["leaderboard-body"].children.length, 1, "Previous's one row, not Latest's three");
  assert.equal(page.ids["revision-select"].value, PREVIOUS);
});

test("a late frontier answer for Latest never shows its card on Previous", async () => {
  const page = openPage();
  await page.answer(LIST, REVISIONS);
  page.choose(PREVIOUS);

  await page.answer(PREVIOUS_BOARD, board([entry("old", 0.4)]));
  await page.answer(PREVIOUS_FRONTIER, NO_FRONTIER);
  await page.answer(LATEST_FRONTIER, OPEN_FRONTIER);

  assert.equal(page.ids["summary-frontier-card"].hidden, true);
});

test("switching hides the previous revision's numbers until the new board arrives", async () => {
  const page = openPage();
  await page.answer(LIST, REVISIONS);
  await page.answer(LATEST_BOARD, board([entry("a", 0.9), entry("b", 0.8), entry("c", 0.7)]));
  await page.answer(LATEST_FRONTIER, OPEN_FRONTIER);
  assert.equal(page.ids["leaderboard-summary"].hidden, false, "Latest's summary was shown");
  assert.equal(page.ids["summary-frontier-card"].hidden, false, "Latest's frontier card was shown");

  page.choose(PREVIOUS);

  for (const id of [
    "leaderboard-summary",
    "summary-frontier-card",
    "leaderboard-climb-section",
    "leaderboard-wrap",
  ]) {
    assert.equal(page.ids[id].hidden, true, id + " is hidden while Previous loads");
  }
});

// A shared link to an earlier revision, opened while the revision list cannot be read: there is no
// selector, so a line names the revision shown.
test("without the revision list, a shared earlier-revision link still says which revision it shows", async () => {
  const page = openPage("?id=hle&revision=" + PREVIOUS);
  await page.fail(LIST, 503);
  await page.answer(PREVIOUS_BOARD, board([entry("old", 0.4)]));

  assert.equal(page.ids["revision-notice"].hidden, false);
  assert.equal(
    page.ids["revision-notice"].textContent,
    "Showing earlier revision 32a91cf1. The list of revisions could not be loaded."
  );
  assert.equal(page.ids["leaderboard-body"].children.length, 1);
});
