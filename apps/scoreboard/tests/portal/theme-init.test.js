"use strict";
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function initialize(stored, dark, denied = false) {
  let theme = 'light';
  const writes = [];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../portal/theme-init.js'), 'utf8'), {
    document: {documentElement: {setAttribute(name, value) {
      assert.equal(name, 'data-theme'); theme = value;
    }}},
    localStorage: {
      getItem(key) { assert.equal(key, 'sf_theme'); if (denied) throw new Error('denied'); return stored; },
      setItem(...args) { writes.push(args); },
    },
    window: {matchMedia(query) { assert.equal(query, '(prefers-color-scheme: dark)'); return {matches: dark}; }},
  });
  assert.deepEqual(writes, []);
  return theme;
}
for (const dark of [false, true]) {
  test(`OS ${dark ? 'dark' : 'light'} wins without a valid stored preference`, () => {
    for (const stored of [null, '', 'invalid']) assert.equal(initialize(stored, dark), dark ? 'dark' : 'light');
  });
  test(`valid explicit choice wins over OS ${dark ? 'dark' : 'light'}`, () => {
    for (const stored of ['dark', 'light']) assert.equal(initialize(stored, dark), stored);
  });
  test(`denied storage still follows OS ${dark ? 'dark' : 'light'}`, () => {
    assert.equal(initialize(null, dark, true), dark ? 'dark' : 'light');
  });
}
