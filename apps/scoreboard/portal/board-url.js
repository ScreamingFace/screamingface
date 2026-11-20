/* Board addresses for the leaderboard portal.
 *
 * A board has two addresses. The server answers /benchmarks/<id>/ with that board's own title
 * and description, so it is the one a search engine or a link preview should see. The older
 * benchmark.html?id=<id> redirects to it, and is still what the page is opened at from the
 * filesystem, where there is no server to answer a path.
 *
 * This file is the one place that knows both forms: which board a page shows, and what a link to
 * a board looks like. Analytics, the follow form and the page scripts all ask here, so a page
 * cannot count a visit for one board and follow another.
 *
 * Loaded as a plain <script> in the browser (exposing window.SFBoardUrl) and via require() in
 * tests, the same shape as leaderboard-logic.js. No build step.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SFBoardUrl = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var BOARD_PATH = /^\/benchmarks\/([^\/]+)\/?$/;
  // Anchored at the site root, with or without an origin, so the API's /v1/benchmarks/<id> is
  // never mistaken for a board page.
  var BOARD_LINK = /^(?:https?:\/\/[^\/]+)?\/benchmarks\/([^\/?#]+)\/?(?:[?#]|$)/;
  var OLD_BOARD_LINK = /(?:^|\/)benchmark\.html\?/;

  function decode(segment) {
    try {
      return decodeURIComponent(segment) || null;
    } catch (e) {
      // A malformed escape names no board.
      return null;
    }
  }

  function idFromSearch(search) {
    return new URLSearchParams(search || "").get("id") || null;
  }

  // The board a path names, or null. Only /benchmarks/<id>/ is a board; /v1/benchmarks/... is
  // the API and never reaches a page.
  function idFromPath(pathname) {
    var match = BOARD_PATH.exec(pathname || "");
    return match ? decode(match[1]) : null;
  }

  // The board this page shows: the path wins, so a stray ?id= on a board address cannot rename it.
  function idFromLocation(location) {
    if (!location) return null;
    return idFromPath(location.pathname) || idFromSearch(location.search);
  }

  // The board a link points at, in either form, or null for any other link.
  function idFromHref(href) {
    var value = String(href || "");
    if (OLD_BOARD_LINK.test(value)) return idFromSearch(value.slice(value.indexOf("?")));
    var match = BOARD_LINK.exec(value);
    return match ? decode(match[1]) : null;
  }

  function served(location) {
    return !!location && (location.protocol === "http:" || location.protocol === "https:");
  }

  // A link to a board. Root-relative when a server is answering, because a page at
  // /benchmarks/<id>/ would resolve a relative link beneath itself. Without a server the
  // relative query form is the only one that opens.
  function boardHref(id, location) {
    var segment = encodeURIComponent(id);
    return served(location) ? "/benchmarks/" + segment + "/" : "benchmark.html?id=" + segment;
  }

  // A link to another portal page, for the same reason.
  function pageHref(file, location) {
    return served(location) ? "/" + file : file;
  }

  return {
    idFromPath: idFromPath,
    idFromLocation: idFromLocation,
    idFromHref: idFromHref,
    boardHref: boardHref,
    pageHref: pageHref,
  };
});
