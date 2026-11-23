/* OME-2001: the Benchmark page says why the selected revision changed.
 *
 * FEATURE: the revision note, one plain-text line the Engine publishes beside a Benchmark's
 * revision (what changed, and whether scores still compare). The page shows the SELECTED
 * revision's note under the revision selector, after the date the board first saw that revision.
 *
 * STORY: as a researcher holding runs under the old revision, I read what changed on the page,
 * without asking the team.
 *
 * Two layers: the pure line (revision-selector.js), then the REAL page (benchmark.js behind a
 * small fake DOM, the benchmark-revision-switch.test.js approach) to prove the line follows the
 * selection and is written as text.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const R = require("../../portal/revision-selector.js");

const PORTAL = path.join(__dirname, "..", "..", "portal");
const ORIGIN = "https://board.test";
const LATEST = "35c7d07e9058f52d";
const PREVIOUS = "d8fb037307f35415";
const NOTE =
  "Length-adjusted score, judge at low effort, failed Cases count as 0. Not comparable with earlier results.";

function row(overrides) {
  return Object.assign(
    {
      revision: LATEST,
      first_seen_at: "2026-11-23T09:30:00Z",
      first_seen_inferred: false,
      until: null,
      case_count: 525,
      case_count_inferred: false,
      result_count: 0,
      current: true,
      note: NOTE,
    },
    overrides
  );
}

// --- the line itself ---------------------------------------------------------------------------

test("the note line opens with the day the board first saw the revision", () => {
  assert.equal(R.noteLine(row()), "23 Nov 2026 · " + NOTE);
});

test("a revision without a note has no line, so the page shows what it showed before notes", () => {
  // Every revision recorded before notes existed answers null; an older board omits the key.
  assert.equal(R.noteLine(row({ note: null })), null);
  assert.equal(R.noteLine(row({ note: undefined })), null);
  assert.equal(R.noteLine(row({ note: "   " })), null);
  assert.equal(R.noteLine(null), null);
});

test("a backfilled first-seen date is marked about, as it is in the selector", () => {
  // The date was inferred from the earliest submission, so the line must not state it as exact.
  assert.equal(
    R.noteLine(row({ first_seen_inferred: true, note: "Judge changed." })),
    "about 23 Nov 2026 · Judge changed."
  );
});

test("a note that is not text is ignored rather than printed", () => {
  // The API is typed, but the page must never print [object Object] under a revision.
  assert.equal(R.noteLine(row({ note: { text: "x" } })), null);
});

// --- the real page -----------------------------------------------------------------------------

function makeNode(tag) {
  let text = "";
  const node = {
    tag,
    children: [],
    attrs: {},
    style: {},
    className: "",
    hidden: false,
    value: "",
    parentNode: null,
    previousElementSibling: null,
    markupWrites: 0,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    get textContent() {
      return text;
    },
    set textContent(value) {
      text = String(value);
    },
    // The fake records any attempt to write markup, so a test can refuse it.
    set innerHTML(_value) {
      this.markupWrites += 1;
    },
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

function board(revision) {
  return {
    benchmark: { id: "hbp", display_name: "HealthBench Professional", description: "", revision, visibility: "public" },
    entries: [],
    baselines: [],
  };
}

const LIST = "/v1/leaderboard/hbp/revisions";
const LATEST_BOARD = "/v1/leaderboard/hbp?top=50";
const PREVIOUS_BOARD = "/v1/leaderboard/hbp?top=50&revision=" + PREVIOUS;

function revisions(latestNote) {
  return {
    benchmark_id: "hbp",
    revisions: [
      row({ note: latestNote }),
      row({
        revision: PREVIOUS,
        first_seen_at: "2026-10-09T09:00:00Z",
        until: "2026-11-23T09:30:00Z",
        result_count: 40,
        current: false,
        note: null,
      }),
    ],
  };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 5));

// Opens benchmark.html with every board and revision-list answer held until `answer` releases it.
function openPage(search) {
  const query = search || "?id=hbp";
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
  // As the markup ships it: the note line starts hidden.
  byId("revision-note").hidden = true;

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
  for (const file of ["leaderboard-logic.js", "main.js", "revision-selector.js", "external-results.js", "benchmark.js"]) {
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

  return { ids, answer, fail, choose };
}

test("the page shows the selected revision's note under the selector", async () => {
  const page = openPage();
  await page.answer(LIST, revisions(NOTE));
  await page.answer(LATEST_BOARD, board(LATEST));

  const line = page.ids["revision-note"];
  assert.equal(line.hidden, false);
  assert.equal(line.textContent, "23 Nov 2026 · " + NOTE);
});

test("choosing a revision without a note takes the line away, and choosing back restores it", async () => {
  // WHY: a note left on screen would describe a revision the reader is no longer looking at.
  const page = openPage();
  await page.answer(LIST, revisions(NOTE));
  await page.answer(LATEST_BOARD, board(LATEST));

  page.choose(PREVIOUS);
  const line = page.ids["revision-note"];
  assert.equal(line.hidden, true);
  assert.equal(line.textContent, "");

  page.choose(LATEST);
  assert.equal(line.hidden, false);
  assert.equal(line.textContent, "23 Nov 2026 · " + NOTE);
});

test("a link that names the earlier revision opens on that revision's own note state", async () => {
  const page = openPage("?id=hbp&revision=" + PREVIOUS);
  await page.answer(LIST, revisions(NOTE));
  await page.answer(PREVIOUS_BOARD, board(PREVIOUS));

  assert.equal(page.ids["revision-note"].hidden, true);
});

test("a board with no notes anywhere never shows the line", async () => {
  const page = openPage();
  await page.answer(LIST, revisions(null));
  await page.answer(LATEST_BOARD, board(LATEST));

  assert.equal(page.ids["revision-note"].hidden, true);
  assert.equal(page.ids["revision-note"].textContent, "");
});

test("when the revision list cannot be read, the line stays hidden", async () => {
  const page = openPage();
  await page.fail(LIST, 500);
  await page.answer(LATEST_BOARD, board(LATEST));

  assert.equal(page.ids["revision-note"].hidden, true);
});

test("a note is written as text, so markup in it is shown and never run", async () => {
  // INVARIANT: the note is another service's free text. It reaches the page through textContent
  // only; the fake DOM counts any innerHTML write on the line and this refuses one.
  const hostile = '<img src=x onerror="alert(1)"> Not comparable.';
  const page = openPage();
  await page.answer(LIST, revisions(hostile));
  await page.answer(LATEST_BOARD, board(LATEST));

  const line = page.ids["revision-note"];
  assert.equal(line.textContent, "23 Nov 2026 · " + hostile);
  assert.equal(line.markupWrites, 0);
  assert.equal(line.children.length, 0);
});
