/* Tests for the reproduced count on the spec history page (E14 B4, PRD reproduce R4; TDD #14).
 *
 * Runs on Node's built-in runner, like the other portal tests, and loads the REAL `main.js` and
 * `spec.js` into a `vm` context behind a very small fake DOM (the same harness as
 * `paper-link.test.js`): the decision under test lives in the page that reads the score detail.
 *
 * INVARIANT: `reproduction_count` is API data the page does not own. It is shown only when it is a
 * positive whole number, and only through `textContent`, so a stray value never becomes markup.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PORTAL = path.join(__dirname, "..", "..", "portal");
const PAGE = "https://board.test/spec.html?benchmark=hle&spec=spec-1";
const SCORE_ID = "11111111-1111-1111-1111-111111111111";
const LAST = "2026-10-06T12:30:00Z";

function makeNode(tag) {
  const node = {
    tag,
    children: [],
    attrs: {},
    className: "",
    hidden: false,
    textContent: "",
    parentNode: null,
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
    addEventListener() {},
    querySelector() {
      return heading;
    },
  };
  return node;
}

const heading = makeNode("h2");

// Loads main.js then spec.js, serves `score` as the latest submission's detail, and returns the
// `#spec-content` node once the page has settled.
async function renderSpecPage(score) {
  const ids = {};
  for (const id of [
    "spec-status",
    "spec-content",
    "spec-id",
    "spec-benchmark",
    "back-link",
    "history-body",
    "best-score",
    "submission-count",
    "run-region",
  ]) {
    ids[id] = makeNode("div");
  }
  const bodies = {
    "/v1/benchmarks": { benchmarks: [{ id: "hle", display_name: "HLE" }] },
    "/v1/leaderboard/hle/spec-1/history?limit=20": {
      submissions: [
        {
          id: SCORE_ID,
          submitted_at: "2026-10-06T12:00:00Z",
          submitted_by: "alice",
          authors: ["alice"],
          score: 0.5,
          total_questions: 10,
        },
      ],
    },
    ["/v1/scores/" + SCORE_ID]: score,
  };
  const context = {
    URL,
    URLSearchParams,
    Promise,
    JSON,
    Math,
    setTimeout,
    navigator: {},
    console,
    document: {
      readyState: "complete",
      title: "",
      createElement: makeNode,
      createTextNode: (text) => ({ textContent: String(text) }),
      getElementById: (id) => ids[id] || null,
      addEventListener() {},
    },
    fetch: async (url) => {
      const key = url.replace("https://board.test", "");
      if (!(key in bodies)) return { ok: false, status: 404, text: async () => "" };
      return { ok: true, status: 200, text: async () => JSON.stringify(bodies[key]) };
    },
    location: { href: PAGE, search: "?benchmark=hle&spec=spec-1", protocol: "https:", origin: "https://board.test" },
  };
  context.window = context;
  vm.createContext(context);
  for (const file of ["main.js", "spec.js"]) {
    vm.runInContext(fs.readFileSync(path.join(PORTAL, file), "utf8"), context, { filename: file });
  }
  await new Promise((resolve) => setTimeout(resolve, 25));
  return { content: ids["spec-content"], portal: context.ScorePortal };
}

function scoreDetail(extra) {
  return { id: SCORE_ID, url4_expression: "url4://x", ...extra };
}

// The direct children of the page content that read as a "Reproduced ..." line.
function reproducedLines(content) {
  return content.children.filter((child) => String(child.textContent).startsWith("Reproduced"));
}

test("a reproduced score shows the count and the last date", async () => {
  const { content, portal } = await renderSpecPage(
    scoreDetail({ reproduction_count: 3, last_reproduced_at: LAST }),
  );

  const lines = reproducedLines(content);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].textContent, "Reproduced 3 times · last " + portal.formatDate(LAST));
});

test("one reproduction reads as one time", async () => {
  const { content, portal } = await renderSpecPage(
    scoreDetail({ reproduction_count: 1, last_reproduced_at: LAST }),
  );

  assert.equal(reproducedLines(content)[0].textContent, "Reproduced 1 time · last " + portal.formatDate(LAST));
});

test("a count without a last date still shows the count", async () => {
  const { content } = await renderSpecPage(scoreDetail({ reproduction_count: 2 }));

  assert.equal(reproducedLines(content)[0].textContent, "Reproduced 2 times");
});

test("no reproduced line when the count is zero, absent, null or not a positive whole number", async () => {
  for (const count of [0, undefined, null, -1, 1.5, NaN, "3", "<img src=x onerror=alert(1)>", {}, [3]]) {
    const extra = count === undefined ? {} : { reproduction_count: count };
    const { content } = await renderSpecPage(scoreDetail({ ...extra, last_reproduced_at: LAST }));
    assert.deepEqual(reproducedLines(content), [], String(count));
  }
});

test("the line renders beside the paper link", async () => {
  const { content } = await renderSpecPage(
    scoreDetail({
      paper_url: "https://arxiv.org/abs/2610.01234",
      reproduction_count: 4,
      last_reproduced_at: LAST,
    }),
  );

  const texts = content.children.map((child) => String(child.textContent));
  assert.ok(texts.some((text) => text.startsWith("Paper:")), "paper line still renders");
  assert.ok(texts.some((text) => text.startsWith("Reproduced 4 times")));
});
