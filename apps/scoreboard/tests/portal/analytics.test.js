/* Tests for the portal's Plausible labelling (analytics.js).
 *
 * Runs on Node's built-in runner — `node --test tests/portal/` — like the other portal tests.
 *
 * WHY these are pinned: the `benchmark`, `section` and `label` values are the keys marketing
 * groups the leaderboard's traffic by. A silent change to how a board or a click is named splits
 * one dashboard row into two, and the history before the change stops lining up with the history
 * after it.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const A = require("../../portal/analytics.js");

test("benchmarkFromSearch reads the board id from ?id=", () => {
  assert.equal(A.benchmarkFromSearch("?id=contracteval"), "contracteval");
  assert.equal(A.benchmarkFromSearch("?sort=score&id=gdpval-text"), "gdpval-text");
  assert.equal(A.benchmarkFromSearch("?id=a%20b"), "a b");
});

test("benchmarkFromSearch is null off a board", () => {
  assert.equal(A.benchmarkFromSearch(""), null);
  assert.equal(A.benchmarkFromSearch(undefined), null);
  assert.equal(A.benchmarkFromSearch("?id="), null);
  assert.equal(A.benchmarkFromSearch("?other=1"), null);
});

test("sectionFor uses the region name, and 'page' outside every region", () => {
  assert.equal(A.sectionFor("catalogue"), "catalogue");
  assert.equal(A.sectionFor(null), "page");
  assert.equal(A.sectionFor(""), "page");
});

test("labelFor prefers an explicit data-track-label", () => {
  assert.equal(
    A.labelFor({ trackLabel: "hero-cta", href: "benchmark.html?id=x", text: "Get started" }),
    "hero-cta"
  );
});

test("labelFor names a link to a board by the board's id, not its card text", () => {
  assert.equal(
    A.labelFor({ href: "benchmark.html?id=contracteval", text: "ContractEval → Legal clause extraction 4,182 questions" }),
    "contracteval"
  );
  assert.equal(A.labelFor({ href: "/benchmark.html?id=draco", text: "DRACO" }), "draco");
});

test("labelFor falls back to aria-label, then collapsed visible text", () => {
  assert.equal(A.labelFor({ ariaLabel: "Toggle light/dark theme", text: "◐" }), "Toggle light/dark theme");
  assert.equal(A.labelFor({ href: "about.html", text: "  about \n " }), "about");
  assert.equal(A.labelFor({ href: "index.html", text: "Show   more\nbenchmarks" }), "Show more benchmarks");
});

test("labelFor caps long text at 60 characters", () => {
  const label = A.labelFor({ text: "x".repeat(200) });
  assert.equal(label.length, 60);
  assert.ok(label.endsWith("…"));
});

test("labelFor never returns an empty label", () => {
  assert.equal(A.labelFor({ text: "   " }), "(unlabelled)");
  assert.equal(A.labelFor({}), "(unlabelled)");
});
