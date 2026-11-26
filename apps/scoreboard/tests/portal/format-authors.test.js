/* An author's name links to their website when `authors_metadata` carries one.
 *
 * Exercises the real `formatAuthors()` from `main.js` (not a reimplementation), behind a
 * minimal fake DOM — the same `node()` shape used by benchmark-picker-keyboard.test.js.
 * `formatAuthors` returns its own inline wrapper element (built with the file's own `el()`),
 * never a bare DocumentFragment, so this fixture needs nothing beyond `createElement` and
 * `createTextNode`, the same two primitives every other portal test fixture already provides.
 *
 * `authors_metadata` is keyed by the SAME published name `authors` carries (the store masks both
 * the same way — see `_publish_authors_metadata` in `schemas.py`), so these fixtures key by the
 * plain name throughout, exactly as a real API response does.
 */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function node(tag) {
  return {
    tag,
    children: [],
    attrs: {},
    textContent: "",
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    setAttribute(key, value) {
      this.attrs[key] = String(value);
    },
    getAttribute(key) {
      return key in this.attrs ? this.attrs[key] : null;
    },
  };
}

function load() {
  const document = {
    createElement: node,
    createTextNode: (text) => ({ tag: "#text", textContent: String(text) }),
  };
  const window = { location: { href: "https://board.test/benchmark.html?id=hle" } };
  const context = { window, document, URL };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "..", "..", "portal", "main.js"), "utf8"),
    context,
    { filename: "main.js" }
  );
  return context.window.ScorePortal;
}

// `formatAuthors` returns its own inline wrapper (a <span>, like `paperLink` returns its own
// <a>) — its children are what a caller's cell ends up holding once appended.
function render(portal, values, metadata) {
  return portal.formatAuthors(values, metadata).children;
}

test("no authors renders a lone em dash, metadata or not", () => {
  const portal = load();

  assert.deepEqual(
    render(portal, [], { ignored: { website: "https://x.test" } }).map((c) => c.textContent),
    ["—"]
  );
  assert.deepEqual(render(portal, null, undefined).map((c) => c.textContent), ["—"]);
});

test("an author with no metadata entry renders as plain text, unchanged from before", () => {
  const portal = load();

  const children = render(portal, ["alice", "bob"], undefined);

  assert.deepEqual(
    children.map((c) => ({ tag: c.tag, text: c.textContent })),
    [
      { tag: "#text", text: "alice" },
      { tag: "#text", text: ", " },
      { tag: "#text", text: "bob" },
    ]
  );
});

test("a safe http(s) website renders the author as a link", () => {
  const portal = load();

  const children = render(portal, ["alice"], { alice: { website: "https://alice.example/" } });

  assert.equal(children.length, 1);
  assert.equal(children[0].tag, "a");
  assert.equal(children[0].attrs.href, "https://alice.example/");
  assert.equal(children[0].textContent, "alice");
  assert.equal(children[0].attrs.rel, "noopener noreferrer nofollow");
});

test("full_name becomes the link label when the website is present", () => {
  const portal = load();

  const children = render(portal, ["alice"], {
    alice: { website: "https://alice.example/", full_name: "Alice Silva" },
  });

  assert.equal(children[0].tag, "a");
  assert.equal(children[0].textContent, "Alice Silva");
});

test("full_name with no website still renders as plain text, not a link", () => {
  const portal = load();

  const children = render(portal, ["alice"], { alice: { full_name: "Alice Silva" } });

  assert.deepEqual(children.map((c) => ({ tag: c.tag, text: c.textContent })), [
    { tag: "#text", text: "Alice Silva" },
  ]);
});

test("an unsafe website scheme never becomes an anchor", () => {
  const portal = load();

  for (const unsafe of ["javascript:alert(1)", "data:text/html,<b>x</b>", "ftp://x.test/p", ""]) {
    const children = render(portal, ["alice"], { alice: { website: unsafe } });
    assert.deepEqual(children.map((c) => c.tag), ["#text"], unsafe);
    assert.equal(children[0].textContent, "alice", unsafe);
  }
});

test("only the authors with a website link; the rest of the row stays plain text", () => {
  const portal = load();

  const children = render(portal, ["alice", "bob", "carol"], {
    alice: { website: "https://alice.example/" },
    carol: { website: "javascript:alert(1)" },
  });

  assert.deepEqual(
    children.map((c) => c.tag),
    ["a", "#text", "#text", "#text", "#text"]
  );
  assert.equal(children[0].attrs.href, "https://alice.example/");
  assert.equal(
    children.map((c) => c.textContent).join(""),
    "alice, bob, carol"
  );
});
