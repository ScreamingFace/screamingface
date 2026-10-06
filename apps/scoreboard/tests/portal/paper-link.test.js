/* Tests for the paper link on the spec history page (E14 A1, PRD metadata-ownership M21).
 *
 * Runs on Node's built-in runner, like the other portal tests. Unlike them it loads the REAL
 * `main.js` and `spec.js` into a `vm` context behind a very small fake DOM, because the decision
 * under test — "a paper link is clickable only when it is http(s)" — lives in the shared helpers
 * and in the page that calls them, not in a pure module.
 *
 * INVARIANT: `paper_url` is untrusted API data. The API refuses non-http(s) links on write (M10),
 * but the portal must not depend on that: a row written by an older build, or by hand in the
 * database, must still never become a `javascript:` anchor.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PORTAL = path.join(__dirname, "..", "..", "portal");
const PAGE = "https://board.test/spec.html?benchmark=hle&spec=spec-1";

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
          id: "11111111-1111-1111-1111-111111111111",
          submitted_at: "2026-10-06T12:00:00Z",
          submitted_by: "alice",
          authors: ["alice"],
          score: 0.5,
          total_questions: 10,
        },
      ],
    },
    "/v1/scores/11111111-1111-1111-1111-111111111111": score,
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

function anchors(node) {
  const found = [];
  for (const child of node.children) {
    if (child.tag === "a") found.push(child);
    found.push(...anchors(child));
  }
  return found;
}

function scoreDetail(extra) {
  return { id: "11111111-1111-1111-1111-111111111111", url4_expression: "url4://x", ...extra };
}

test("paper link renders for an https paper_url", async () => {
  const { content } = await renderSpecPage(scoreDetail({ paper_url: "https://arxiv.org/abs/2610.01234" }));

  const links = anchors(content).filter((a) => a.attrs.href !== undefined);
  assert.equal(links.length, 1);
  assert.equal(links[0].attrs.href, "https://arxiv.org/abs/2610.01234");
  assert.equal(links[0].attrs.rel, "noopener noreferrer nofollow");
});

test("paper link renders only for http(s): a javascript: paper_url is never an anchor", async () => {
  for (const unsafe of ["javascript:alert(1)", "data:text/html,<b>x</b>", "vbscript:msgbox(1)", "ftp://x.test/p"]) {
    const { content } = await renderSpecPage(scoreDetail({ paper_url: unsafe }));
    assert.deepEqual(anchors(content), [], unsafe);
  }
});

test("a score with no paper_url shows no paper line", async () => {
  const { content } = await renderSpecPage(scoreDetail({}));
  assert.deepEqual(anchors(content), []);
  const { content: withNull } = await renderSpecPage(scoreDetail({ paper_url: null }));
  assert.deepEqual(anchors(withNull), []);
});

test("paperLink returns null for a falsy or non-http(s) value and an anchor otherwise", async () => {
  const { portal } = await renderSpecPage(scoreDetail({}));

  assert.equal(portal.paperLink(null), null);
  assert.equal(portal.paperLink(""), null);
  assert.equal(portal.paperLink("javascript:alert(1)"), null);
  assert.equal(portal.paperLink("https://doi.org/10.1/x").attrs.href, "https://doi.org/10.1/x");
});
