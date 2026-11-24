/* Tests for the benchmark page's description fold (OME-1985).
 *
 * Runs on Node's built-in runner; NAMED EXPLICITLY in the scoreboard card gate list and in
 * scoreboard-tests.yml (OME-798). A dedicated file because the append-only gate cannot parse a
 * .js edit to prove it is additive.
 *
 * A benchmark description is one paragraph of up to ~2,500 characters. The page folds it to three
 * lines behind a "Show more" button. Two layers are pinned here: the rule (descriptionFoldState in
 * leaderboard-logic.js) and the page wiring that measures the text and applies the rule
 * (initDescriptionFold in benchmark.js, loaded for real into a `vm` context behind a fake DOM).
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PORTAL = path.join(__dirname, "..", "..", "portal");
const L = require("../../portal/leaderboard-logic.js");

// ---- the rule ----------------------------------------------------------------------------------

test("a description that fits in three lines shows no button, because a control that does nothing is noise", () => {
  const state = L.descriptionFoldState(false, false);
  assert.equal(state.buttonHidden, true);
  assert.equal(state.clamped, false);
});

test("a description taller than three lines is folded and offers Show more", () => {
  assert.deepEqual(L.descriptionFoldState(true, false), {
    clamped: true,
    buttonHidden: false,
    label: "Show more",
    expanded: false,
  });
});

test("an opened description keeps its button as Show less even though it no longer overflows", () => {
  // WHY: an open paragraph is unclamped, so it always measures as not overflowing. If that hid
  // the button, the reader could open a long description and never fold it again.
  assert.deepEqual(L.descriptionFoldState(false, true), {
    clamped: false,
    buttonHidden: false,
    label: "Show less",
    expanded: true,
  });
});

// ---- the page wiring ---------------------------------------------------------------------------

// A node with just enough DOM for the fold: a working class list, attributes and listeners.
function makeNode() {
  const classes = new Set();
  return {
    hidden: false,
    textContent: "",
    attrs: {},
    listeners: {},
    classes,
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
      contains: (name) => classes.has(name),
    },
    setAttribute(name, value) {
      this.attrs[name] = String(value);
    },
    addEventListener(name, handler) {
      this.listeners[name] = handler;
    },
  };
}

// Loads the real benchmark.js and returns the initDescriptionFold it exports for tests. The page
// start-up is not run: `ready` is a stand-in that never calls it, so no fetch or DOM is needed.
function loadInitDescriptionFold(windowListeners) {
  const window = {
    ScorePortal: { ready() {} },
    SFLeaderboardLogic: L,
    addEventListener(name, handler) {
      windowListeners[name] = handler;
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(PORTAL, "benchmark.js"), "utf8"), { window });
  return window.SFBenchmarkPage.initDescriptionFold;
}

// A fake description paragraph: `fullPx` tall unclamped, `clampPx` tall while its fold carries the
// clamp class. That is the one browser behaviour the wiring depends on.
function makeFold(fullPx, clampPx) {
  const fold = makeNode();
  const desc = makeNode();
  desc.scrollHeight = fullPx;
  Object.defineProperty(desc, "clientHeight", {
    get: () => (fold.classes.has("is-clamped") ? Math.min(desc.scrollHeight, clampPx) : desc.scrollHeight),
  });
  return { fold, desc, button: Object.assign(makeNode(), { hidden: true }) };
}

test("a long description loads folded, opens on click and folds again on the next click", () => {
  const windowListeners = {};
  const init = loadInitDescriptionFold(windowListeners);
  const { fold, desc, button } = makeFold(400, 77); // 400px of text in a 77px three-line box

  const sync = init(fold, desc, button);
  sync();
  assert.equal(fold.classes.has("is-clamped"), true);
  assert.equal(button.hidden, false);
  assert.equal(button.textContent, "Show more");
  assert.equal(button.attrs["aria-expanded"], "false");

  button.listeners.click();
  assert.equal(fold.classes.has("is-clamped"), false);
  assert.equal(button.hidden, false);
  assert.equal(button.textContent, "Show less");
  assert.equal(button.attrs["aria-expanded"], "true");

  button.listeners.click();
  assert.equal(fold.classes.has("is-clamped"), true);
  assert.equal(button.textContent, "Show more");
  assert.equal(button.attrs["aria-expanded"], "false");
});

test("a short description loads unclamped with the button still hidden", () => {
  const init = loadInitDescriptionFold({});
  const { fold, desc, button } = makeFold(26, 77); // one line of text

  init(fold, desc, button)();
  assert.equal(button.hidden, true);
  assert.equal(fold.classes.has("is-clamped"), false);
});

test("narrowing the window re-measures a folded description, so text that now wraps past three lines gains its button", () => {
  const windowListeners = {};
  const init = loadInitDescriptionFold(windowListeners);
  const { fold, desc, button } = makeFold(60, 77);

  init(fold, desc, button)();
  assert.equal(button.hidden, true);

  desc.scrollHeight = 180; // the same text, wrapped onto more lines by a narrower window
  windowListeners.resize();
  assert.equal(button.hidden, false);
  assert.equal(fold.classes.has("is-clamped"), true);
});

test("a page missing the fold markup gets a no-op, so the leaderboard still renders", () => {
  const init = loadInitDescriptionFold({});
  assert.doesNotThrow(() => init(null, makeNode(), null)());
});

// Runs the real page start-up (init in benchmark.js) on a board whose description the server
// already wrote, with the leaderboard answer held until the test releases it.
function openBoardWithHeldLeaderboard(fold, desc, button) {
  const nodes = { "benchmark-desc-fold": fold, "benchmark-desc": desc, "benchmark-desc-toggle": button };
  const byId = (id) => {
    if (!nodes[id]) nodes[id] = makeNode();
    return nodes[id];
  };
  // The crumb's <nav> and the separator before it, which the start-up shows beside the name.
  nodes["crumb-benchmark"] = Object.assign(makeNode(), {
    parentNode: Object.assign(makeNode(), { previousElementSibling: makeNode() }),
  });

  const held = {};
  const page = {};
  const window = {
    SFLeaderboardLogic: L,
    addEventListener() {},
    location: { search: "", pathname: "/benchmarks/hle/", hash: "" },
    ScorePortal: {
      ready: (init) => (page.start = init),
      boardId: () => "hle",
      atBoardAddress: () => true,
      fetchJson: (url) => new Promise((resolve) => (held[url] = resolve)),
      showLoading() {},
      setStatus() {},
      clear() {},
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(PORTAL, "benchmark.js"), "utf8"), {
    window,
    document: { getElementById: byId, title: "" },
  });
  page.start();
  return held;
}

test("a server-written description is folded while the leaderboard is still loading", () => {
  // WHY (PR #1983 review): folding only after the leaderboard answer showed the whole 2,500-
  // character paragraph during a slow load, then collapsed it and jumped the page up under the
  // reader. The fold must be in place before that answer, not because of it.
  const { fold, desc, button } = makeFold(512, 77); // the reviewer's measured heights
  desc.textContent = "A long description the server wrote into the page.";

  const held = openBoardWithHeldLeaderboard(fold, desc, button);
  assert.ok(held["/v1/leaderboard/hle?top=50"], "the leaderboard request is still pending");
  assert.equal(fold.classes.has("is-clamped"), true);
  assert.equal(button.hidden, false);
  assert.equal(button.textContent, "Show more");
});
