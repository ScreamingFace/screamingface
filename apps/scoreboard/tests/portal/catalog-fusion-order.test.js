/* Tests for catalog.js's fusion-leads partition (OME-1916): fusion-leading benchmarks sort
 * first, the rest after, and the existing alphabetical comparator is the tiebreaker within
 * each partition, unchanged from before this ticket.
 *
 * Runs on Node's built-in runner; NAMED EXPLICITLY in the scoreboard card gate list and in
 * scoreboard-tests.yml (OME-798). A dedicated file (not appended to catalog.test.js) because
 * the append-only gate cannot parse a .js edit to prove it is additive, and this is its own
 * concern from the existing paging/search/filter coverage in catalog.test.js.
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
    textContent: "", get firstChild() { return this.children[0] || null; },
    appendChild(child) { this.children.push(child); return child; },
    removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); },
    fire(k) { (this.listeners[k] || []).forEach((fn) => fn()); },
    focus() { this.focused = true; },
  };
}

async function page(data) {
  const nodes = Object.fromEntries(
    ["status", "cards", "more", "search", "scored", "count", "controls"].map(
      (k) => [`benchmark-${k}`, element("div")]
    )
  );
  nodes["benchmark-scored"].checked = false;
  const context = {
    window: { SFLeaderboardLogic: logic, location: { protocol: "http:", origin: "http://test" } },
    SFLeaderboardLogic: logic,
    document: {
      readyState: "complete", createElement: element,
      getElementById(id) { return nodes[id] || null; }, addEventListener() {},
    },
    fetch: async () => ({ ok: true, text: async () => JSON.stringify({ benchmarks: data }) }),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../portal/main.js"), "utf8"), context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../portal/catalog.js"), "utf8"), context);
  await new Promise(setImmediate);
  const ids = () => nodes["benchmark-cards"].children.map(
    (c) => new URL(c.attrs.href, "http://test").searchParams.get("id")
  );
  return { ids };
}

test("fusion-leading benchmarks sort before the rest, alpha order within each group", async () => {
  const data = [
    { id: "z-lead", display_name: "Zebra (leads)", best_score: 1, fusion_leads: true },
    { id: "a-plain", display_name: "Apple", best_score: 1, fusion_leads: false },
    { id: "m-lead", display_name: "Mango (leads)", best_score: 1, fusion_leads: true },
    { id: "b-plain", display_name: "Banana", best_score: 1, fusion_leads: false },
  ];
  const p = await page(data);
  assert.deepEqual(p.ids(), ["m-lead", "z-lead", "a-plain", "b-plain"]);
});

test("a benchmark with no fusion_leads field sorts with the non-leading group, not first", async () => {
  const data = [
    { id: "unknown-signal", display_name: "Aardvark", best_score: 1 },
    { id: "leads", display_name: "Zebra", best_score: 1, fusion_leads: true },
    { id: "explicitly-false", display_name: "Badger", best_score: 1, fusion_leads: false },
  ];
  const p = await page(data);
  assert.deepEqual(p.ids(), ["leads", "unknown-signal", "explicitly-false"]);
});

test("within the non-leading group, ties still break by id exactly as the alpha comparator always has", async () => {
  const data = [
    { id: "b-id", display_name: "Same Name", best_score: 1, fusion_leads: false },
    { id: "a-id", display_name: "Same Name", best_score: 1, fusion_leads: false },
  ];
  const p = await page(data);
  assert.deepEqual(p.ids(), ["a-id", "b-id"]);
});

test("all benchmarks leading, or none, preserves plain alpha order", async () => {
  const allLead = [
    { id: "b", display_name: "Beta", best_score: 1, fusion_leads: true },
    { id: "a", display_name: "Alpha", best_score: 1, fusion_leads: true },
  ];
  assert.deepEqual((await page(allLead)).ids(), ["a", "b"]);
  const noneLead = [
    { id: "b", display_name: "Beta", best_score: 1, fusion_leads: false },
    { id: "a", display_name: "Alpha", best_score: 1, fusion_leads: false },
  ];
  assert.deepEqual((await page(noneLead)).ids(), ["a", "b"]);
});
