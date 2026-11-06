"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const logic = require("../../portal/leaderboard-logic.js");
const source = fs.readFileSync(path.join(__dirname, "../../portal/catalog.js"), "utf8");
const key = "sf_catalog_has_scores";
const benchmarks = [
  { id: "empty", display_name: "A blank board", best_score: null },
  { id: "zero", display_name: "B zero", best_score: 0 },
  { id: "negative", display_name: "C negative", best_score: -1 },
];

function session(value) {
  const values = new Map(value === undefined ? [] : [[key, value]]);
  return {
    getItem: name => values.get(name) ?? null,
    setItem: (name, saved) => values.set(name, saved),
  };
}

async function load(storage, deniedAccess = false) {
  const nodes = Object.fromEntries(
    ["status", "cards", "more", "search", "scored", "count", "clear", "controls"].map(name => [name, {
      children: [], listeners: {}, value: "", checked: true,
      appendChild(child) { this.children.push(child); },
      addEventListener(event, callback) { this.listeners[event] = callback; },
      focus() {},
    }]),
  );
  const requests = [];
  const window = {
    SFLeaderboardLogic: logic,
    get sessionStorage() {
      if (deniedAccess) throw new Error("storage denied");
      return storage;
    },
    ScorePortal: {
      ready: init => init(),
      showLoading() {}, showEmpty() {}, setStatus() {},
      showError() { assert.fail("Preference storage must not break the catalogue"); },
      describeError: error => error.message,
      clear: node => { node.children = []; },
      benchmarkCard: board => board.id,
      fetchJson: async url => { requests.push(url); return { benchmarks }; },
    },
  };
  vm.runInNewContext(source, { window, document: {
    getElementById: id => nodes[id.slice("benchmark-".length)],
  } });
  await new Promise(setImmediate);
  assert.deepEqual(requests, ["/v1/benchmarks/summary"]);
  return {
    nodes,
    ids: () => nodes.cards.children,
    toggle(checked) { nodes.scored.checked = checked; nodes.scored.listeners.change(); },
  };
}

test("both checkbox choices survive reload; fresh sessions still default to scored", async () => {
  const storage = session();
  let page = await load(storage);
  assert.equal(page.nodes.scored.checked, true);
  assert.deepEqual(page.ids(), ["zero", "negative"]);
  page.toggle(false);
  page = await load(storage);
  assert.equal(page.nodes.scored.checked, false);
  assert.deepEqual(page.ids(), ["empty", "zero", "negative"]);
  page.toggle(true);
  page = await load(storage);
  assert.equal(page.nodes.scored.checked, true);
  assert.deepEqual(page.ids(), ["zero", "negative"]);
  const fresh = await load(session());
  assert.equal(fresh.nodes.scored.checked, true);
});

test("unchecking Has scores retains the query and remembers the choice without persisting search", async () => {
  const storage = session();
  const page = await load(storage);
  page.nodes.search.value = "empty";
  page.nodes.search.listeners.input();
  page.toggle(false);
  assert.equal(page.nodes.search.value, "empty");
  assert.deepEqual(page.ids(), ["empty"]);
  const refreshed = await load(storage);
  assert.equal(refreshed.nodes.scored.checked, false);
  assert.equal(refreshed.nodes.search.value, "");
  assert.deepEqual(refreshed.ids(), ["empty", "zero", "negative"]);
});

test("only a valid saved false disables the scored default", async () => {
  for (const value of [undefined, "true", "", "0", "invalid", "null"]) {
    const page = await load(session(value));
    assert.equal(page.nodes.scored.checked, true);
    assert.deepEqual(page.ids(), ["zero", "negative"]);
  }
  const page = await load(session("false"));
  assert.equal(page.nodes.scored.checked, false);
  assert.deepEqual(page.ids(), ["empty", "zero", "negative"]);
});

test("unavailable storage never blocks rendering or checkbox changes", async () => {
  const fail = () => { throw new Error("storage unavailable"); };
  for (const [storage, denied] of [
    [session(), true],
    [{ getItem: fail, setItem: fail }, false],
    [{ getItem: () => "false", setItem: fail }, false],
  ]) {
    const page = await load(storage, denied);
    page.toggle(false);
    assert.deepEqual(page.ids(), ["empty", "zero", "negative"]);
    page.toggle(true);
    assert.deepEqual(page.ids(), ["zero", "negative"]);
    page.toggle(false);
    assert.deepEqual(page.ids(), ["empty", "zero", "negative"]);
  }
});
