/* Tests for the board address helper (board-url.js) and every script that asks it which board a
 * page shows.
 *
 * Runs on Node's built-in runner, like the other portal tests.
 *
 * WHY these are pinned: a board has two addresses, /benchmarks/<id>/ and the older
 * benchmark.html?id=<id>. Analytics, the follow form and the board script each need the id from
 * whichever one the page was opened at. A reader that misses the path form shows no error: the
 * pageview just loses its board, or the follow form never appears.
 */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const U = require("../../portal/board-url.js");
const A = require("../../portal/analytics.js");
const S = require("../../portal/subscribe.js");

const PORTAL = path.join(__dirname, "..", "..", "portal");
const HTTPS = { protocol: "https:", origin: "https://board.test" };

function at(pathname, search) {
  return Object.assign({ pathname, search: search || "", href: "https://board.test" + pathname + (search || "") }, HTTPS);
}

/* ---- board-url.js ------------------------------------------------------ */

test("idFromPath reads the id from the board address, with or without the slash", () => {
  assert.equal(U.idFromPath("/benchmarks/draco-3pass/"), "draco-3pass");
  assert.equal(U.idFromPath("/benchmarks/draco-3pass"), "draco-3pass");
  assert.equal(U.idFromPath("/benchmarks/inspect-mmlu_pro/"), "inspect-mmlu_pro");
  assert.equal(U.idFromPath("/benchmarks/legacy%2Fid/"), "legacy/id");
  assert.equal(U.idFromPath("/benchmarks/a%20b/"), "a b");
});

test("idFromPath is null for every other path", () => {
  for (const other of ["/", "/index.html", "/benchmark.html", "/benchmarks/", "/benchmarks", "/v1/benchmarks/x",
    "/benchmarks/a/b/", "/x/benchmarks/a/", "", null, undefined]) {
    assert.equal(U.idFromPath(other), null, String(other));
  }
});

test("idFromPath is null for an id that cannot be decoded", () => {
  assert.equal(U.idFromPath("/benchmarks/%E0%A4%A/"), null);
});

test("idFromLocation prefers the path and falls back to ?id=", () => {
  assert.equal(U.idFromLocation(at("/benchmarks/draco/")), "draco");
  assert.equal(U.idFromLocation(at("/benchmark.html", "?id=contracteval")), "contracteval");
  assert.equal(U.idFromLocation(at("/benchmarks/draco/", "?id=other&utm_source=x")), "draco");
  assert.equal(U.idFromLocation(at("/benchmark.html", "?id=")), null);
  assert.equal(U.idFromLocation(at("/index.html")), null);
});

test("idFromLocation tolerates a missing or partial location", () => {
  assert.equal(U.idFromLocation(undefined), null);
  assert.equal(U.idFromLocation(null), null);
  assert.equal(U.idFromLocation({}), null);
  assert.equal(U.idFromLocation({ search: "?id=hle" }), "hle");
});

test("boardHref is the clean address over http and https", () => {
  assert.equal(U.boardHref("draco-3pass", HTTPS), "/benchmarks/draco-3pass/");
  assert.equal(U.boardHref("mmlu", { protocol: "http:" }), "/benchmarks/mmlu/");
  assert.equal(U.boardHref("legacy/id", HTTPS), "/benchmarks/legacy%2Fid/");
  assert.equal(U.idFromPath(U.boardHref("a b/c?d#e", HTTPS)), "a b/c?d#e");
});

test("boardHref keeps the relative query form where there is no server", () => {
  // Opened from the filesystem a root-relative link points at the disk root.
  for (const location of [{ protocol: "file:" }, {}, undefined, null]) {
    assert.equal(U.boardHref("draco 3", location), "benchmark.html?id=draco%203");
  }
});

test("pageHref is root-relative over http(s) and unchanged otherwise", () => {
  assert.equal(U.pageHref("index.html", HTTPS), "/index.html");
  assert.equal(U.pageHref("spec.html?benchmark=a&spec=b", HTTPS), "/spec.html?benchmark=a&spec=b");
  assert.equal(U.pageHref("index.html", { protocol: "file:" }), "index.html");
  assert.equal(U.pageHref("index.html", undefined), "index.html");
});

test("idFromHref reads a board link in either form and ignores other links", () => {
  assert.equal(U.idFromHref("/benchmarks/contracteval/"), "contracteval");
  assert.equal(U.idFromHref("https://leaderboard.screamingface.ai/benchmarks/draco/?utm_source=x"), "draco");
  assert.equal(U.idFromHref("benchmark.html?id=contracteval"), "contracteval");
  assert.equal(U.idFromHref("/benchmark.html?id=draco"), "draco");
  for (const other of ["index.html", "/v1/benchmarks/x", "https://example.org/benchmarks", "#", "", null, undefined]) {
    assert.equal(U.idFromHref(other), null, String(other));
  }
});

/* ---- analytics.js ------------------------------------------------------ */

test("the benchmark property is read from the board address", () => {
  assert.equal(A.benchmarkFromLocation(at("/benchmarks/draco-3pass/")), "draco-3pass");
  assert.equal(A.benchmarkFromLocation(at("/benchmark.html", "?id=hle")), "hle");
  assert.equal(A.benchmarkFromLocation(at("/about.html")), null);
});

test("a pageview on the board address carries the benchmark property", () => {
  const root = {
    location: Object.assign(at("/benchmarks/draco-3pass/"), { hostname: "leaderboard.screamingface.ai" }),
    localStorage: { setItem() {}, removeItem() {} },
    document: { addEventListener() {} },
  };
  A.install(root);
  assert.deepEqual(root.plausible.o.customProperties(), { benchmark: "draco-3pass" });
});

test("a click on a board link in the clean form is labelled with the board id", () => {
  assert.equal(A.labelFor({ href: "/benchmarks/contracteval/", text: "ContractEval → Legal clause extraction" }), "contracteval");
  assert.equal(A.labelFor({ trackLabel: "hero-cta", href: "/benchmarks/x/", text: "Get started" }), "hero-cta");
});

/* ---- subscribe.js ------------------------------------------------------ */

test("the follow form finds its board on either address", () => {
  assert.equal(S.boardId({ location: at("/benchmarks/draco-3pass/") }), "draco-3pass");
  assert.equal(S.boardId({ location: at("/benchmarks/draco-3pass/", "?utm_source=news") }), "draco-3pass");
  assert.equal(S.boardId({ location: at("/benchmark.html", "?id=hle") }), "hle");
  assert.equal(S.boardId({ location: at("/index.html") }), null);
});

/* ---- main.js and benchmark.js, run as the page runs them --------------- */

function makeNode(tag) {
  return {
    tag, children: [], attrs: {}, style: {}, className: "", hidden: false, textContent: "",
    parentNode: null, previousElementSibling: null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
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
      const index = this.children.indexOf(ref);
      this.children.splice(index < 0 ? this.children.length : index, 0, child);
      child.parentNode = this;
      return child;
    },
    removeChild(child) { this.children.splice(this.children.indexOf(child), 1); return child; },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; },
    removeAttribute(name) { delete this.attrs[name]; },
    addEventListener() {},
    focus() {},
    querySelector: () => null,
    querySelectorAll: () => [],
  };
}

function descendants(node, found) {
  found = found || [];
  (node.children || []).forEach((child) => { found.push(child); descendants(child, found); });
  return found;
}

function hrefs(node) {
  return descendants(node).filter((child) => child.tag === "a").map((child) => child.attrs.href);
}

// Runs the board page's scripts at `location` and returns its nodes and what it fetched.
async function boardPage(location, title) {
  const ids = {};
  const byId = (id) => {
    if (!ids[id]) { ids[id] = makeNode("div"); ids[id].id = id; }
    return ids[id];
  };
  const crumbNav = makeNode("nav");
  crumbNav.previousElementSibling = makeNode("span");
  crumbNav.appendChild(byId("crumb-benchmark"));
  const fetched = [];
  const bodies = {
    "/v1/benchmarks": { benchmarks: [{ id: "hle", display_name: "HLE" }, { id: "ifeval", display_name: "IFEval" }] },
    "/v1/leaderboard/hle?top=50": {
      benchmark: { id: "hle", display_name: "HLE", description: "Hard questions." },
      entries: [{
        rank: 1, spec_id: "trio", score: 0.5, run_cost_usd: "1.000000", on_pareto_frontier: true,
        submitted_at: "2026-10-06T12:00:00Z", authors: ["alice"], ran_with_providers: ["openai"],
        url4_expression: "url4://x", verified_by_screamingface: true,
      }],
    },
  };
  const context = {
    URL, URLSearchParams, Promise, JSON, Math, Number, setTimeout,
    navigator: {}, console: { log() {}, warn() {}, error() {} },
    SFParetoChart: { render() {} },
    document: {
      readyState: "complete", title,
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
      fetched.push(key);
      if (!(key in bodies)) return { ok: false, status: 404, text: async () => "" };
      return { ok: true, status: 200, text: async () => JSON.stringify(bodies[key]) };
    },
    location,
  };
  context.window = context;
  context.self = context;
  vm.createContext(context);
  for (const file of ["board-url.js", "leaderboard-logic.js", "main.js", "benchmark.js"]) {
    vm.runInContext(fs.readFileSync(path.join(PORTAL, file), "utf8"), context, { filename: file });
  }
  await new Promise((resolve) => setTimeout(resolve, 25));
  return { ids, fetched, document: context.document, portal: context.ScorePortal };
}

test("the board script loads the board named by the clean address", async () => {
  const page = await boardPage(at("/benchmarks/hle/"), "HLE leaderboard: models & fusions | ScreamingFace");

  assert.ok(page.fetched.includes("/v1/leaderboard/hle?top=50"), page.fetched.join(", "));
  assert.equal(page.ids["benchmark-name"].textContent, "HLE");
  assert.equal(page.ids["leaderboard-body"].children.length, 1);
});

test("the board script leaves the title the server wrote", async () => {
  // The server's title carries the words a search result shows; the script must not swap it
  // for a shorter one after load.
  const served = "HLE leaderboard: models & fusions | ScreamingFace";
  const page = await boardPage(at("/benchmarks/hle/"), served);

  assert.equal(page.document.title, served);
});

test("the board script still titles the page at the old address", async () => {
  const page = await boardPage(at("/benchmark.html", "?id=hle"), "screamingface · leaderboard");

  assert.equal(page.document.title, "HLE — screamingface");
});

test("links built on a board page do not resolve under /benchmarks/<id>/", async () => {
  const page = await boardPage(at("/benchmarks/hle/"), "t");
  const links = hrefs(page.ids["leaderboard-body"]).concat(hrefs(page.ids["benchmark-tabs"]));

  assert.ok(links.includes("/spec.html?benchmark=hle&spec=trio"), links.join(", "));
  // ifeval is on the featured shortlist, so the strip renders it as a tab.
  assert.ok(links.includes("/benchmarks/ifeval/"), links.join(", "));
  for (const href of links) {
    assert.ok(/^(\/|https?:|#)/.test(href), href);
  }
});

test("main.js builds board links for the clean address over http(s)", async () => {
  const page = await boardPage(at("/benchmarks/hle/"), "t");

  assert.equal(page.portal.boardHref("draco-3pass"), "/benchmarks/draco-3pass/");
  assert.equal(page.portal.pageHref("index.html"), "/index.html");
  assert.equal(page.portal.boardId(), "hle");
});

test("an address with no board says so and fetches no leaderboard", async () => {
  const page = await boardPage(at("/benchmark.html"), "t");

  assert.ok(!page.fetched.some((url) => url.startsWith("/v1/leaderboard/")), page.fetched.join(", "));
  const status = page.ids["leaderboard-status"];
  const text = [status.textContent].concat(descendants(status).map((node) => node.textContent)).join(" ");
  assert.match(text, /No benchmark specified/);
  assert.ok(hrefs(status).includes("/index.html"), hrefs(status).join(", "));
});
