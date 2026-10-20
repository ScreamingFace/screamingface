/* Tests for the lines the per-submission page shows above its history: no reproduced count.
 *
 * Runs on Node's built-in runner, named explicitly in the scoreboard gate line and in
 * scoreboard-tests.yml like the sibling portal suites. Loads the REAL main.js and spec.js into a
 * `vm` context behind a small fake DOM and serves the score detail the page reads.
 *
 * The page no longer shows how many times a score was reproduced (the owner decided the count is
 * not displayed; the API still returns `reproduction_count`). The checks compare the WHOLE list of
 * lines the page added, so any extra line, the count included, fails them.
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
const PAPER = "https://arxiv.org/abs/2610.01234";
const EDITED = "2026-10-06T12:30:00Z";

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
      return null;
    },
  };
  return node;
}

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
    // The portal reads score detail anonymously (e003f254a).
    ["/v1/public/scores/" + SCORE_ID]: score,
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
    location: {
      href: PAGE,
      search: "?benchmark=hle&spec=spec-1",
      protocol: "https:",
      origin: "https://board.test",
    },
  };
  context.window = context;
  vm.createContext(context);
  for (const file of ["main.js", "spec.js"]) {
    vm.runInContext(fs.readFileSync(path.join(PORTAL, file), "utf8"), context, { filename: file });
  }
  await new Promise((resolve) => setTimeout(resolve, 25));
  return { content: ids["spec-content"], portal: context.ScorePortal };
}

const LAST = "2026-10-07T08:00:00Z";

test("a reproduced score adds no line to the page", async () => {
  const { content } = await renderSpecPage({
    id: SCORE_ID,
    url4_expression: "url4://x",
    reproduction_count: 3,
    last_reproduced_at: LAST,
  });

  assert.deepEqual(content.children, []);
});

test("beside a paper link and an edit time, only those two lines render", async () => {
  const { content, portal } = await renderSpecPage({
    id: SCORE_ID,
    url4_expression: "url4://x",
    paper_url: PAPER,
    metadata_updated_at: EDITED,
    reproduction_count: 4,
    last_reproduced_at: LAST,
  });

  const lines = content.children.map((line) => ({
    className: line.className,
    texts: [line.textContent, ...line.children.map((child) => child.textContent)],
  }));
  assert.deepEqual(lines, [
    { className: "meta mono", texts: ["Paper: ", PAPER] },
    { className: "meta mono", texts: ["Metadata edited " + portal.formatDate(EDITED)] },
  ]);
});
