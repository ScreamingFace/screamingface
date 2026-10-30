"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const logic = require("../../portal/leaderboard-logic.js");

// INVARIANT: exercise the renderer's catalog wiring and input handler, not only
// filterBenchmarks against a full catalog supplied directly by the test.
function element(tag) {
  return {
    tag, attrs: {}, children: [], listeners: {}, textContent: "",
    get firstChild() { return this.children[0] || null; },
    setAttribute(name, value) { this.attrs[name] = value; },
    appendChild(child) {
      if (child.tag === "fragment") {
        this.children.push(...child.children);
        child.children = [];
      } else {
        this.children.push(child);
      }
      return child;
    },
    removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
    addEventListener(name, callback) { this.listeners[name] = callback; },
    focus() {},
  };
}

const catalog = [
  { id: "draco", display_name: "DRACO", visibility: "public" },
  { id: "ifeval", display_name: "IFEval", visibility: "public" },
  { id: "healthbench-professional", display_name: "HealthBench Professional", visibility: "public" },
  { id: "draco-3pass", display_name: "DRACO 3-Pass", visibility: "public" },
  { id: "contracteval", display_name: "Private Featured", visibility: "private" },
  { id: "private-draco", display_name: "DRACO Private", visibility: "private" },
  { id: "legacy/id", display_name: "Legacy Board" },
];

function picker(activeId = "ifeval") {
  const context = {
    window: { SFLeaderboardLogic: logic },
    document: {
      readyState: "complete", createElement: element,
      createDocumentFragment() { return element("fragment"); },
      getElementById() { return null; },
      addEventListener() {},
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../portal/main.js"), "utf8"), context);
  const strip = element("nav");
  context.window.ScorePortal.renderTabStrip(strip, catalog, activeId);
  const button = strip.children.find(node => node.tag === "button");
  const panel = strip.children.find(node => node.id === "tabstrip-more-panel");
  const [search, list] = panel.children;
  button.listeners.click();
  return {
    strip, button, panel, list,
    query(value) {
      search.value = value;
      search.listeners.input();
      return list.children.filter(node => node.tag === "a");
    },
  };
}

function ids(links) {
  return links.map(node => decodeURIComponent(node.attrs.href.split("?id=")[1]));
}

for (const [query, expected] of [
  ["ifeval", ["ifeval"]],
  ["  IFEVAL \t", ["ifeval"]],
  ["healthbench", ["healthbench-professional"]],
  ["draco", ["draco", "draco-3pass"]],
  ["3-Pass", ["draco-3pass"]],
  ["healthbench-professional", ["healthbench-professional"]],
]) {
  test(`picker searches all listed boards for ${JSON.stringify(query)}`, () => {
    const results = ids(picker().query(query));
    assert.deepEqual(results, expected);
    assert.equal(new Set(results).size, results.length, "each board appears once in results");
  });
}

test("blank, whitespace and reopening restore overflow without changing featured tabs", () => {
  const page = picker();
  const tabs = () => page.strip.children.filter(node => node.tag === "a");
  assert.deepEqual(ids(tabs()), ["draco-3pass", "healthbench-professional", "ifeval"]);
  assert.equal(tabs().find(node => node.textContent === "IFEval").attrs["aria-current"], "page");
  assert.equal(page.button.textContent, "More benchmarks ▾");
  assert.deepEqual(ids(page.list.children), ["draco", "legacy/id"]);
  for (const blank of ["", " \t\n "]) {
    page.query("ifeval");
    assert.deepEqual(ids(page.query(blank)), ["draco", "legacy/id"]);
  }
  page.query("ifeval");
  page.button.listeners.click();
  page.button.listeners.click();
  assert.equal(page.panel.hidden, false);
  assert.equal(page.button.attrs["aria-expanded"], "true");
  assert.deepEqual(ids(page.list.children), ["draco", "legacy/id"]);
  assert.deepEqual(ids(tabs()), ["draco-3pass", "healthbench-professional", "ifeval"]);
});

test("private featured and overflow boards stay absent; unmatched queries show empty state", () => {
  const page = picker();
  for (const query of ["private", "contracteval", "not-a-benchmark"]) {
    assert.deepEqual(page.query(query), []);
    assert.equal(page.list.children.length, 1);
    assert.equal(page.list.children[0].textContent, "No benchmark matches.");
  }
});

test("results retain navigation links and active indication for either board type", () => {
  for (const [activeId, query, label] of [
    ["ifeval", "ifeval", "IFEval"],
    ["legacy/id", "legacy", "Legacy Board"],
  ]) {
    const page = picker(activeId);
    const [link] = page.query(query);
    assert.ok(link, "active board is searchable");
    assert.equal(link.attrs.href, "benchmark.html?id=" + encodeURIComponent(activeId));
    assert.equal(link.textContent, label);
    assert.equal(link.attrs["aria-current"], "page");
    if (activeId === "legacy/id") assert.equal(page.button.textContent, "Legacy Board ▾");
    for (const other of page.query("draco")) {
      assert.equal(other.attrs["aria-current"], undefined);
    }
  }
});
