/* OME-1762: exercise the real disclosure renderer and bubbling keyboard events.
 * WHY: a filter-only test cannot detect a listener attached to the wrong DOM node.
 * Native Tab/Enter behavior is also checked in Chromium during the browser smoke.
 */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const logic = require("../../portal/leaderboard-logic.js");

function setup() {
  const document = { activeElement: null, readyState: "complete", getElementById: () => null };
  function node(tag) {
    const listeners = {};
    return {
      tag, children: [], attrs: {}, parentNode: null, hidden: false, value: "",
      get firstChild() { return this.children[0] || null; },
      appendChild(child) {
        if (child.tag === "#fragment") {
          child.children.slice().forEach((item) => this.appendChild(item));
          child.children = [];
        } else {
          this.children.push(child);
          child.parentNode = this;
        }
        return child;
      },
      removeChild(child) {
        this.children.splice(this.children.indexOf(child), 1);
        child.parentNode = null;
      },
      setAttribute(key, value) { this.attrs[key] = String(value); },
      getAttribute(key) { return this.attrs[key] ?? null; },
      contains(other) { return other === this || this.children.some((child) => child.contains(other)); },
      addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
      dispatchEvent(event) {
        event.target ||= this;
        event.preventDefault ||= () => { event.defaultPrevented = true; };
        (listeners[event.type] || []).forEach((fn) => fn(event));
        if (event.bubbles && this.parentNode) this.parentNode.dispatchEvent(event);
      },
      focus() {
        const previous = document.activeElement;
        document.activeElement = this;
        if (previous && previous !== this) {
          previous.dispatchEvent({ type: "focusout", bubbles: true, relatedTarget: this });
        }
      },
    };
  }
  Object.assign(document, node("#document"));
  document.createElement = node;
  document.createDocumentFragment = () => node("#fragment");
  const window = { SFLeaderboardLogic: logic };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../portal/main.js"), "utf8"), {
    window, document,
  });
  const strip = node("nav");
  document.appendChild(strip);
  window.ScorePortal.renderTabStrip(strip, [
    { id: "mmlu", display_name: "MMLU" },
    { id: "other", display_name: "Other" },
  ], "ifeval");
  const [button, panel] = strip.children;
  const [search, list] = panel.children;
  const outside = node("button");
  document.appendChild(outside);
  button.dispatchEvent({ type: "click", bubbles: true });
  return { document, button, panel, search, list, outside };
}

function key(target, value) {
  const event = { type: "keydown", key: value, bubbles: true, defaultPrevented: false };
  target.dispatchEvent(event);
  return event;
}

function assertClosed(ui) {
  assert.equal(ui.panel.hidden, true);
  assert.equal(ui.button.getAttribute("aria-expanded"), "false");
}

for (const target of ["input", "first result", "last result", "trigger"]) {
  test(`Escape from ${target} closes and restores trigger focus`, () => {
    const ui = setup();
    assert.equal(ui.panel.hidden, false);
    assert.equal(ui.button.getAttribute("aria-expanded"), "true");
    assert.equal(ui.document.activeElement, ui.search);
    const element = target === "input" ? ui.search : target === "trigger" ? ui.button :
      target === "first result" ? ui.list.children[0] : ui.list.children.at(-1);
    element.focus();
    key(element, "Escape");
    assertClosed(ui);
    assert.equal(ui.document.activeElement, ui.button);
  });
}

test("Escape works on newly filtered results after reopening", () => {
  const ui = setup();
  key(ui.search, "Escape");
  ui.button.dispatchEvent({ type: "click", bubbles: true });
  ui.search.value = "MMLU";
  ui.search.dispatchEvent({ type: "input", bubbles: true });
  assert.equal(ui.list.children.length, 1);
  const result = ui.list.children[0];
  assert.equal(result.textContent, "MMLU");
  result.focus();
  key(result, "Escape");
  assertClosed(ui);
  assert.equal(ui.document.activeElement, ui.button);
});

for (const value of ["Tab", "Enter", "ArrowDown"]) {
  test(`${value} on a result is not canceled and does not close the panel`, () => {
    const ui = setup();
    const result = ui.list.children[0];
    result.focus();
    assert.equal(key(result, value).defaultPrevented, false);
    assert.equal(ui.panel.hidden, false);
    assert.equal(ui.button.getAttribute("aria-expanded"), "true");
    assert.equal(result.getAttribute("href"), "benchmark.html?id=mmlu");
  });
}

test("focus within the panel keeps it open; leaving closes without stealing focus", () => {
  const ui = setup();
  ui.list.children[0].focus();
  assert.equal(ui.panel.hidden, false);
  ui.list.children[1].focus();
  assert.equal(ui.panel.hidden, false);
  ui.outside.focus();
  assertClosed(ui);
  assert.equal(ui.document.activeElement, ui.outside);
});

test("outside click dismisses the picker", () => {
  const ui = setup();
  ui.outside.dispatchEvent({ type: "click", bubbles: true });
  assertClosed(ui);
});
