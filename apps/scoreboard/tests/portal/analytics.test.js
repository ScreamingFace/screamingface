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

test("selfExclusion reads only 1 and 0", () => {
  assert.deepEqual(A.selfExclusion("?plausible_ignore=1", "leaderboard.screamingface.ai").ignore, "1");
  assert.deepEqual(A.selfExclusion("?plausible_ignore=0", "leaderboard.screamingface.ai").ignore, "0");
  assert.deepEqual(A.selfExclusion("?plausible_ignore=yes", "leaderboard.screamingface.ai"), { ignore: null, next: null });
  assert.deepEqual(A.selfExclusion("?id=draco", "leaderboard.screamingface.ai"), { ignore: null, next: null });
  assert.deepEqual(A.selfExclusion("", "leaderboard.screamingface.ai"), { ignore: null, next: null });
});

test("selfExclusion hops to docs only from production, and only when asked", () => {
  assert.equal(
    A.selfExclusion("?plausible_ignore=1&hop=1", "leaderboard.screamingface.ai").next,
    "https://docs.screamingface.ai/?plausible_ignore=1&hop=1"
  );
  assert.equal(A.selfExclusion("?plausible_ignore=1", "leaderboard.screamingface.ai").next, null);
  assert.equal(A.selfExclusion("?plausible_ignore=1&hop=1", "leaderboard.dev.screamingface.ai").next, null);
  assert.equal(A.selfExclusion("?plausible_ignore=1&hop=1", "localhost").next, null);
  assert.equal(A.selfExclusion("?plausible_ignore=1&hop=1", "leaderboard.dev.screamingface.ai").ignore, "1");
});

test("applySelfExclusion sets, clears, and forwards", () => {
  function fakeRoot(search, hostname) {
    const store = new Map();
    const root = {
      location: { search, hostname, replaced: null, replace(url) { this.replaced = url; } },
      localStorage: { setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k), getItem: (k) => store.get(k) ?? null },
    };
    return { root, store };
  }
  let f = fakeRoot("?plausible_ignore=1&hop=1", "leaderboard.screamingface.ai");
  A.applySelfExclusion(f.root);
  assert.equal(f.store.get("plausible_ignore"), "true");
  assert.equal(f.root.location.replaced, "https://docs.screamingface.ai/?plausible_ignore=1&hop=1");

  f = fakeRoot("?plausible_ignore=0&hop=1", "leaderboard.dev.screamingface.ai");
  f.store.set("plausible_ignore", "true");
  A.applySelfExclusion(f.root);
  assert.equal(f.store.get("plausible_ignore"), undefined);
  assert.equal(f.root.location.replaced, null);

  f = fakeRoot("?id=draco", "leaderboard.screamingface.ai");
  A.applySelfExclusion(f.root);
  assert.equal(f.store.has("plausible_ignore"), false);
  assert.equal(f.root.location.replaced, null);
});
