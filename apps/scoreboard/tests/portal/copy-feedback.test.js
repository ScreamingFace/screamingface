"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function node() {
  return {
    attrs: {}, children: [], listeners: {}, textContent: "",
    setAttribute(name, value) { this.attrs[name] = value; },
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(name, callback) { this.listeners[name] = callback; },
  };
}

function portal(clipboard) {
  const body = node();
  const timers = [];
  const context = {
    window: {}, navigator: { clipboard },
    document: {
      body, readyState: "complete", createElement: node,
      getElementById() { return null; },
    },
    setTimeout(callback, delay) { timers.push({ callback, delay }); },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../portal/main.js"), "utf8"), context);
  return {
    api: context.window.ScorePortal, body,
    flush(delay) {
      const pending = timers.filter(timer => timer.delay === delay);
      for (const timer of pending) {
        timers.splice(timers.indexOf(timer), 1);
        timer.callback();
      }
    },
  };
}

for (const label of ["Copy", "Reproduce"]) {
  for (const outcome of ["success", "rejection", "unavailable"]) {
    test(`${label}: accessible ${outcome} feedback and name reset`, async () => {
      const copied = [];
      const clipboard = outcome === "unavailable" ? undefined : {
        writeText(text) {
          copied.push(text);
          return outcome === "success" ? Promise.resolve() : Promise.reject(new Error("denied"));
        },
      };
      const page = portal(clipboard);
      const ariaLabel = label + " the exact code for spec-1";
      const button = page.api.createCopyButton("spec-1", "raw <code>", { label, ariaLabel });
      page.api.createCopyButton("spec-2", "another expression");
      assert.equal(page.body.children.length, 1, "one live region, present before copying");
      const status = page.body.children[0];
      assert.equal(status.attrs.role, "status");
      assert.equal(status.attrs["aria-live"], "polite");
      assert.equal(status.attrs["aria-atomic"], "true");
      assert.equal(status.className, "sr-only");
      assert.equal(status.textContent, "");
      assert.equal(button.attrs["aria-label"], ariaLabel);

      for (let attempt = 0; attempt < 2; attempt++) {
        button.listeners.click();
        await Promise.resolve();
        assert.equal(status.textContent, "", "clear before repeating the same announcement");
        page.flush(50);
        const feedback = outcome === "success" ? "copied" : "copy failed";
        assert.equal(status.textContent, label + " for spec-1: " + feedback);
        assert.equal(button.textContent, outcome === "success" ? "✓ copied" : "copy failed");
        assert.equal(button.attrs["aria-label"], feedback + ": " + ariaLabel);
        page.flush(1600);
        assert.equal(button.textContent, label);
        assert.equal(button.attrs["aria-label"], ariaLabel);
      }
      assert.deepEqual(copied, outcome === "unavailable" ? [] : ["raw <code>", "raw <code>"]);
    });
  }
}
