import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
const source = readFileSync(new URL("../src/screamingface/_ui/credit_refresh.js", import.meta.url), "utf8");
const {default: {render}} = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));

test("visible-only five-minute refresh, overlap suppression, acknowledgement and cleanup", () => {
  const originals = Object.fromEntries(["document", "IntersectionObserver", "MutationObserver", "setTimeout", "clearTimeout"]
    .map(name => [name, globalThis[name]]));
  const listeners = new Map(), handlers = new Map(), timers = new Map(), sent = [];
  let mounted, observer, stopped = false, timerId = 0;
  const target = {isConnected: true};
  globalThis.document = {visibilityState: "visible",
    addEventListener: (key, fn) => listeners.set(key, fn),
    removeEventListener: key => listeners.delete(key)};
  globalThis.MutationObserver = class {
    constructor(fn) { mounted = fn; }
    observe() {}
    disconnect() {}
  };
  globalThis.IntersectionObserver = class {
    constructor(fn) { observer = fn; }
    observe(el) { assert.equal(el, target); }
    disconnect() { stopped = true; }
  };
  globalThis.setTimeout = (fn, delay) => {
    assert.equal(delay, 300000);
    timers.set(++timerId, fn);
    return timerId;
  };
  globalThis.clearTimeout = id => timers.delete(id);
  let enabled = true;
  const model = {get: () => enabled, send: msg => sent.push(msg),
    on: (key, fn) => handlers.set(key, fn), off: key => handlers.delete(key)};
  const el = {isConnected: false, style: {}, setAttribute() {}, closest: () => target};
  let cleanup;
  try {
    cleanup = render({model, el});
    assert.equal(sent.length, 0);
    el.isConnected = true;
    mounted();
    observer([{isIntersecting: true}]);
    assert.equal(sent.length, 1);
    observer([{isIntersecting: true}]);
    assert.equal(sent.length, 1, "in-flight requests cannot overlap");
    handlers.get("msg:custom")({type: "other"});
    assert.equal(timers.size, 0);
    handlers.get("msg:custom")({type: "refreshed"});
    assert.equal(timers.size, 1);
    [...timers.values()][0]();
    assert.equal(sent.length, 2);
    handlers.get("msg:custom")({type: "refreshed"});
    document.visibilityState = "hidden";
    listeners.get("visibilitychange")();
    assert.equal(timers.size, 0);
    document.visibilityState = "visible";
    listeners.get("visibilitychange")();
    assert.equal(sent.length, 3);
    handlers.get("msg:custom")({type: "refreshed"});
    observer([{isIntersecting: false}]);
    assert.equal(timers.size, 0);
    observer([{isIntersecting: true}]);
    handlers.get("msg:custom")({type: "refreshed"});
    enabled = false;
    handlers.get("change:active")();
    assert.equal(timers.size, 0);
    cleanup();
    assert.equal(listeners.size, 0);
    assert.equal(handlers.size, 0);
    assert.equal(stopped, true);
  } finally {
    cleanup?.();
    Object.assign(globalThis, originals);
  }
});
