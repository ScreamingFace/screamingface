"use strict";
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const logic = require('../../portal/leaderboard-logic.js');

async function page() {
  const nodes = {};
  for (const key of ['status', 'cards', 'more', 'search', 'scored', 'count', 'controls']) {
    nodes['benchmark-' + key] = {
      value: '', children: [], listeners: {},
      appendChild(child) { this.children.push(child); },
      addEventListener(event, handler) { (this.listeners[event] ||= []).push(handler); },
      fire(event) { this.listeners[event].forEach(handler => handler()); },
    };
  }
  const benchmarks = Array.from({length: 22}, (_, i) => ({id: `b-${i}`, best_score: .5}));
  benchmarks.push({id: 'empty', best_score: null});
  const context = {
    document: {getElementById: id => nodes[id]},
    window: {SFLeaderboardLogic: logic, ScorePortal: {
      ready: fn => fn(), clear: node => { node.children = []; },
      showLoading() {}, showEmpty() {}, setStatus() {},
      benchmarkCard: b => b, fetchJson: async () => ({benchmarks}),
    }},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../portal/catalog.js'), 'utf8'), context);
  await new Promise(setImmediate);
  return {nodes, query(value) { nodes['benchmark-search'].value = value; nodes['benchmark-search'].fire('input'); }};
}

test('live count announces each revealed batch and resets with filters', async () => {
  const p = await page();
  const count = p.nodes['benchmark-count'];
  assert.equal(count.textContent, 'Showing 9 of 22 matching benchmarks with scores');
  p.nodes['benchmark-more'].fire('click');
  assert.equal(count.textContent, 'Showing 18 of 22 matching benchmarks with scores');
  p.nodes['benchmark-more'].fire('click');
  assert.equal(count.textContent, 'Showing 22 of 22 matching benchmarks with scores');
  p.query('b-21');
  assert.equal(count.textContent, 'Showing 1 of 1 matching benchmark with scores');
  p.query('missing');
  assert.equal(count.textContent, 'Showing 0 of 0 matching benchmarks with scores');
  p.query('empty');
  p.nodes['benchmark-scored'].checked = false;
  p.nodes['benchmark-scored'].fire('change');
  assert.equal(count.textContent, 'Showing 1 of 1 matching benchmark');
  p.query('');
  assert.equal(count.textContent, 'Showing 9 of 23 matching benchmarks');
});
