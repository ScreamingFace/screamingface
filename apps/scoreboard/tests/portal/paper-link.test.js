/* Tests for the paper link's pure safety decision (E14a, OME-1307, MD-20).
 *
 * WHY a file of its own and not more cases in leaderboard-logic.test.js: the append-only gate
 * cannot parse JS, so any edit of an existing JS test file fails it. A new file is wired into the
 * gate by name (tests/unit/test_portal_ci_wiring.py checks both call sites).
 *
 * INVARIANT (MD-D6): `paper_url` is untrusted, API-provided text. It may become an anchor href
 * only when it is an absolute http(s) URL without credentials, and it never becomes text.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../../portal/leaderboard-logic.js");

const REL = "noopener noreferrer nofollow";

test("paperLink: an https URL is a link with the safe rel", () => {
  assert.deepEqual(L.paperLink("https://arxiv.org/abs/2609.01234"), {
    href: "https://arxiv.org/abs/2609.01234",
    rel: REL,
  });
});

test("paperLink: an http URL is a link", () => {
  assert.deepEqual(L.paperLink("http://x.org/p"), { href: "http://x.org/p", rel: REL });
});

test("paperLink: the href is the parsed, normalized URL", () => {
  assert.equal(L.paperLink("HTTPS://X.ORG").href, "https://x.org/");
});

test("paperLink: a URL of exactly 2048 characters is accepted", () => {
  const url = "https://x.org/" + "a".repeat(2048 - "https://x.org/".length);
  assert.equal(url.length, 2048);
  assert.equal(L.paperLink(url).href, url);
});

for (const [label, value] of [
  ["javascript:", "javascript:alert(1)"],
  ["data:", "data:text/html,<script>alert(1)</script>"],
  ["ftp:", "ftp://x.org/paper.pdf"],
  ["credentials", "https://u:p@x.org"],
  ["user only", "https://u@x.org"],
  ["relative", "/relative"],
  ["no scheme", "x.org/paper"],
  ["empty", ""],
  ["null", null],
  ["undefined", undefined],
  ["a number", 42],
  ["an object", { href: "https://x.org" }],
  ["2049 characters", "https://x.org/" + "a".repeat(2049 - "https://x.org/".length)],
]) {
  test(`paperLink: ${label} is not a link`, () => {
    assert.equal(L.paperLink(value), null);
  });
}
