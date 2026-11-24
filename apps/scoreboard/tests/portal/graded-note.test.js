/* Tests for the graded-Case note under a leaderboard score.
 *
 * Runs on Node's built-in runner, named explicitly in the scoreboard gate line and in
 * scoreboard-tests.yml like the sibling portal suites. The wording decision is required from
 * leaderboard-logic.js; the rendering loads the REAL leaderboard-logic.js, main.js and
 * benchmark.js into a `vm` context behind a small fake DOM, so what is asserted is what ships.
 *
 * A run selects `total_questions` Cases and can fail to grade some of them (the Candidate call
 * errors or times out, or the judge gives no readable verdict). `graded_questions` is how many got
 * a grade. The leaderboard says so under the score, so a run that failed on its hard Cases cannot
 * pass for a complete one. A row with no count, or a fully graded one, renders exactly as before.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const L = require("../../portal/leaderboard-logic.js");

const PORTAL = path.join(__dirname, "..", "..", "portal");

// --- the wording decision ------------------------------------------------------------------------

test("a run that failed on some Cases says how many were graded", () => {
  assert.deepEqual(L.gradedNote({ total_questions: 525, graded_questions: 505 }), {
    text: "505 / 525 graded",
    title: "20 of 525 Cases failed and were not graded",
  });
});

test("one failed Case is named in the singular", () => {
  assert.equal(
    L.gradedNote({ total_questions: 525, graded_questions: 524 }).title,
    "1 of 525 Cases failed and was not graded"
  );
});

test("a run where no Case was graded still gets its note", () => {
  // INVARIANT: 0 is a real count, not "missing". A falsy check here would hide the one row a
  // reader most needs flagged.
  assert.equal(L.gradedNote({ total_questions: 525, graded_questions: 0 }).text, "0 / 525 graded");
});

test("large counts are grouped like the other numbers on the page", () => {
  assert.equal(
    L.gradedNote({ total_questions: 12500, graded_questions: 12000 }).text,
    "12,000 / 12,500 graded"
  );
});

test("a fully graded run shows nothing", () => {
  assert.equal(L.gradedNote({ total_questions: 525, graded_questions: 525 }), null);
});

test("a row with no count shows nothing, never '0 failed'", () => {
  // INVARIANT: absent means "not reported" (an older client, or a row from before the field).
  // The page must not turn that into a claim in either direction.
  assert.equal(L.gradedNote({ total_questions: 525 }), null);
  assert.equal(L.gradedNote({ total_questions: 525, graded_questions: null }), null);
});

test("a count the leaderboard could not have stored shows nothing", () => {
  // The API validates the count; the page still refuses to print a claim it cannot stand behind.
  for (const graded of [-1, 526, 505.5, "505", NaN]) {
    assert.equal(L.gradedNote({ total_questions: 525, graded_questions: graded }), null);
  }
  assert.equal(L.gradedNote({ graded_questions: 505 }), null);
  assert.equal(L.gradedNote(null), null);
});

// --- the rendering -------------------------------------------------------------------------------

function makeNode(tag) {
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
    addEventListener() {},
    querySelector() {
      return null;
    },
  };
  return node;
}

// A ranked entry of a 525-Case Benchmark as GET /v1/leaderboard/{id} serves it.
function entry(spec, extra) {
  return {
    rank: 1,
    spec_id: spec,
    benchmark_revision: "rev-1",
    score: 0.5,
    total_questions: 525,
    ran_with_providers: ["openai"],
    submitted_at: "2026-11-21T00:00:00Z",
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
// returns the table body.
async function renderBoard(entries) {
  const ids = {};
  const node = (id) => {
    if (!ids[id]) ids[id] = makeNode("div");
    return ids[id];
  };
  // The breadcrumb reads its parent and the parent's previous sibling.
  const nav = makeNode("nav");
  nav.previousElementSibling = makeNode("span");
  nav.appendChild(node("crumb-benchmark"));
  const bodies = {
    "/v1/leaderboard/arc_agi_2?top=50": {
      benchmark: { id: "arc_agi_2", display_name: "ARC-AGI-2", description: "" },
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
    navigator: {},
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
      const key = url.replace("https://scoreboard.test", "");
      if (!(key in bodies)) return { ok: false, status: 404, text: async () => "" };
      return { ok: true, status: 200, text: async () => JSON.stringify(bodies[key]) };
    },
    location: {
      href: "https://scoreboard.test/benchmark.html?id=arc_agi_2",
      search: "?id=arc_agi_2",
      protocol: "https:",
      origin: "https://scoreboard.test",
    },
  };
  context.window = context;
  vm.createContext(context);
  for (const file of ["leaderboard-logic.js", "main.js", "benchmark.js"]) {
    vm.runInContext(fs.readFileSync(path.join(PORTAL, file), "utf8"), context, { filename: file });
  }
  await new Promise((resolve) => setTimeout(resolve, 25));
  return ids["leaderboard-body"];
}

// The Score column is the sixth: Rank, mark, Submission, Backends, Authors, Score.
function scoreCell(row) {
  return row.children[5];
}

function gradedLines(cell) {
  return cell.children.filter((child) => child.className.split(/\s+/).includes("graded-line"));
}

test("the Score cell of a partly graded entry gains one quiet line under the score", async () => {
  const body = await renderBoard([entry("partial", { graded_questions: 505 })]);

  const cell = scoreCell(body.children[0]);
  const lines = gradedLines(cell);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].textContent, "505 / 525 graded");
  assert.equal(lines[0].title, "20 of 525 Cases failed and were not graded");
  // The existing small-label treatment, no new colour; and UNDER the score, not in place of it.
  assert.equal(lines[0].className, "graded-line meta");
  assert.equal(cell.children[0].className, "score-cell");
  assert.equal(cell.children.indexOf(lines[0]), 1);
});

test("an entry with no count, and a fully graded one, keep the Score cell they always had", async () => {
  const body = await renderBoard([
    entry("old-client"),
    entry("complete", { rank: 2, graded_questions: 525 }),
  ]);

  for (const row of body.children) {
    const cell = scoreCell(row);
    assert.equal(cell.children.length, 1);
    assert.equal(cell.children[0].className, "score-cell");
  }
});

test("the note adds no column: a partly graded row has as many cells as any other", async () => {
  const body = await renderBoard([
    entry("partial", { graded_questions: 505 }),
    entry("old-client", { rank: 2 }),
  ]);

  assert.equal(body.children[0].children.length, body.children[1].children.length);
});
