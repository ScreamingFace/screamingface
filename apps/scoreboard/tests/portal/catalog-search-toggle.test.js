/* OME-1917: the homepage catalogue search starts collapsed behind a quiet
 * "Search benchmarks" button; clicking it reveals (and re-hides) the search
 * input. Runs on Node's built-in runner, same `vm.runInNewContext` + hand-rolled
 * DOM convention as catalog.test.js, so it needs no package.json or dependency.
 *
 * WHY a separate file instead of extending catalog.test.js: catalog.test.js is a
 * prior test (append-only) and does not exercise the toggle's DOM nodes at all —
 * this file is purely additive.
 */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const logic = require("../../portal/leaderboard-logic.js");

function element(tag) {
  return {
    tag, children: [], attrs: {}, listeners: {}, hidden: false, value: "", checked: false,
    textContent: "", focused: false,
    get firstChild() { return this.children[0] || null; },
    appendChild(child) { this.children.push(child); return child; },
    removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); },
    fire(k) { (this.listeners[k] || []).forEach((fn) => fn()); },
    focus() { this.focused = true; },
  };
}

// A one-benchmark catalog is enough: this suite is about the disclosure, not the
// filtering/paging that catalog.test.js already covers.
const catalog = [{ id: "mmlu", display_name: "MMLU", best_score: 0.9 }];

async function page() {
  const nodes = Object.fromEntries(
    ["status", "cards", "more", "search", "scored", "count", "controls", "search-toggle", "search-wrap"]
      .map((k) => [`benchmark-${k}`, element("div")]),
  );
  nodes["benchmark-scored"].checked = true;
  const context = {
    window: { SFLeaderboardLogic: logic, location: { protocol: "http:", origin: "http://test" } },
    SFLeaderboardLogic: logic,
    document: {
      readyState: "complete", createElement: element,
      getElementById(id) { return nodes[id] || null; },
      addEventListener() {},
    },
    fetch: async () => ({ ok: true, text: async () => JSON.stringify({ benchmarks: catalog }) }),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../portal/main.js"), "utf8"), context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../portal/catalog.js"), "utf8"), context);
  await new Promise(setImmediate);
  return nodes;
}

test("the search wrap starts collapsed and the toggle starts unexpanded", async () => {
  const nodes = await page();
  assert.equal(nodes["benchmark-search-wrap"].hidden, true);
  assert.equal(nodes["benchmark-search-toggle"].getAttribute("aria-expanded"), "false");
});

test("clicking the toggle reveals the search input and focuses it", async () => {
  const nodes = await page();
  nodes["benchmark-search-toggle"].fire("click");
  assert.equal(nodes["benchmark-search-wrap"].hidden, false);
  assert.equal(nodes["benchmark-search-toggle"].getAttribute("aria-expanded"), "true");
  assert.equal(nodes["benchmark-search"].focused, true);
});

test("clicking the toggle a second time collapses it again", async () => {
  const nodes = await page();
  nodes["benchmark-search-toggle"].fire("click");
  nodes["benchmark-search-toggle"].fire("click");
  assert.equal(nodes["benchmark-search-wrap"].hidden, true);
  assert.equal(nodes["benchmark-search-toggle"].getAttribute("aria-expanded"), "false");
});

test("expanding and searching still reaches the existing filter path", async () => {
  const nodes = await page();
  nodes["benchmark-search-toggle"].fire("click");
  nodes["benchmark-search"].value = "mmlu";
  nodes["benchmark-search"].fire("input");
  assert.equal(nodes["benchmark-count"].textContent, "Showing 1 of 1 matching benchmark with scores");
});

test("a DOM fixture without the toggle/wrap nodes does not throw (defensive lookup)", async () => {
  const nodes = {};
  for (const key of ["status", "cards", "more", "search", "scored", "count", "controls"]) {
    nodes["benchmark-" + key] = element("div");
  }
  nodes["benchmark-scored"].checked = true;
  const context = {
    window: { SFLeaderboardLogic: logic, location: { protocol: "http:", origin: "http://test" } },
    SFLeaderboardLogic: logic,
    document: {
      readyState: "complete", createElement: element,
      getElementById(id) { return nodes[id] || null; },
      addEventListener() {},
    },
    fetch: async () => ({ ok: true, text: async () => JSON.stringify({ benchmarks: catalog }) }),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../portal/main.js"), "utf8"), context);
  assert.doesNotThrow(() => {
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../portal/catalog.js"), "utf8"), context);
  });
  await new Promise(setImmediate);
  assert.equal(nodes["benchmark-cards"].hidden, false);
});
