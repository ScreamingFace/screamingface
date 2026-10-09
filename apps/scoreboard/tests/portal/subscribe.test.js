/* Tests for the portal's email subscribe forms (subscribe.js).
 *
 * Runs on Node's built-in runner — `node --test tests/portal/` — like the other portal tests.
 *
 * WHY these are pinned: the submission body is the only record of which leaderboard a person
 * asked to follow, where on the page they did it, and which lists they agreed to. A silent change
 * here files subscribers under the wrong board, or opts them into email they never asked for.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const S = require("../../portal/subscribe.js");

const IDS = { all: "111", board: "222" };

function value(body, name) {
  const hit = body.fields.find((f) => f.name === name);
  return hit ? hit.value : undefined;
}

function consented(body) {
  return body.legalConsentOptions.consent.communications.map((c) => c.subscriptionTypeId);
}

test("isValidEmail accepts an address and rejects fragments", () => {
  assert.equal(S.isValidEmail("ada@lab.org"), true);
  assert.equal(S.isValidEmail("  ada@lab.org  "), true);
  for (const bad of ["", "ada", "ada@", "ada@lab", "@lab.org", "ada @lab.org", null, undefined]) {
    assert.equal(S.isValidEmail(bad), false, String(bad));
  }
});

test("a board submission records the board, the placement and the page", () => {
  const body = S.buildSubmission(
    { email: " ada@lab.org ", board: "draco-3pass", placement: "board-footer", pageUri: "https://x/benchmark.html?id=draco-3pass" },
    IDS
  );
  assert.equal(value(body, "email"), "ada@lab.org");
  assert.equal(value(body, "sf_subscribe_board"), "draco-3pass");
  assert.equal(value(body, "sf_subscribe_placement"), "board-footer");
  assert.equal(body.context.pageUri, "https://x/benchmark.html?id=draco-3pass");
  assert.equal(body.context.pageName, "leaderboard: draco-3pass");
  assert.ok(body.fields.every((f) => f.objectTypeId === "0-1"));
});

test("a board submission opts into the general list only when asked", () => {
  const plain = S.buildSubmission({ email: "a@b.co", board: "ifeval", placement: "board-footer" }, IDS);
  assert.deepEqual(consented(plain), ["222"]);
  assert.equal(value(plain, "sf_subscribe_all"), "false");

  const both = S.buildSubmission({ email: "a@b.co", board: "ifeval", placement: "board-footer", alsoAll: true }, IDS);
  assert.deepEqual(consented(both), ["222", "111"]);
  assert.equal(value(both, "sf_subscribe_all"), "true");
});

test("a general submission is scoped 'all' and opts into the general list alone", () => {
  const body = S.buildSubmission({ email: "a@b.co", placement: "site-band" }, IDS);
  assert.equal(value(body, "sf_subscribe_board"), "all");
  assert.equal(value(body, "sf_subscribe_all"), undefined);
  assert.equal(body.context.pageName, "leaderboard: all");
  assert.deepEqual(consented(body), ["111"]);
});

test("UTM tags on the URL travel with the submission; absent ones are left out", () => {
  const body = S.buildSubmission(
    { email: "a@b.co", placement: "site-band", search: "?id=x&utm_source=newsletter&utm_campaign=q4&utm_term=nope" },
    IDS
  );
  assert.equal(value(body, "utm_source"), "newsletter");
  assert.equal(value(body, "utm_campaign"), "q4");
  assert.equal(value(body, "utm_medium"), undefined);
  assert.equal(value(body, "utm_term"), undefined);
});

test("the HubSpot visitor cookie is sent only when there is one", () => {
  assert.equal(S.buildSubmission({ email: "a@b.co" }, IDS).context.hutk, undefined);
  assert.equal(S.buildSubmission({ email: "a@b.co", hutk: "abc" }, IDS).context.hutk, "abc");
});

test("with no subscription types configured, no list is claimed", () => {
  const body = S.buildSubmission({ email: "a@b.co", board: "ifeval", alsoAll: true }, {});
  assert.deepEqual(consented(body), []);
  assert.equal(body.legalConsentOptions.consent.consentToProcess, true);
});

test("copyFor names the board in the board scope and ScreamingFace in the general one", () => {
  const board = S.copyFor("draco-3pass", "DRACO 3-Pass");
  assert.equal(board.heading, "Follow DRACO 3-Pass");
  assert.match(board.done, /DRACO 3-Pass/);
  const all = S.copyFor("all");
  assert.equal(all.heading, "ScreamingFace updates");
  assert.equal(all.button, "Subscribe");
});
