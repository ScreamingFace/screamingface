/* The revision selector's decisions for a benchmark leaderboard.
 *
 * Each leaderboard can show any revision its benchmark has had. The page defaults to Latest,
 * keeps the choice in `?revision=`, and after a bump shows an empty Latest that points to the
 * previous revision's results instead of silently falling back.
 *
 * WHY separate from benchmark.js: these labels and choices decide which grading a reader is
 * looking at, so they are pure and assertable without a browser, like leaderboard-logic.js.
 *
 * Input rows are `GET /v1/leaderboard/{id}/revisions` entries, newest first.
 * Loaded as a plain <script> (window.SFRevisionSelector) and via require() in tests.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SFRevisionSelector = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // WHY UTC: a revision's date is a fact about the board, not the reader's clock; local time
  // would label one revision with two different days for two readers.
  function parts(iso) {
    var date = new Date(iso);
    return { day: date.getUTCDate(), month: MONTHS[date.getUTCMonth()], year: date.getUTCFullYear() };
  }

  function day(iso) {
    var p = parts(iso);
    return p.day + " " + p.month + " " + p.year;
  }

  function range(fromIso, untilIso) {
    var from = parts(fromIso);
    var until = parts(untilIso);
    if (from.day === until.day && from.month === until.month && from.year === until.year) {
      return day(fromIso);
    }
    var start = from.day + " " + from.month + (from.year === until.year ? "" : " " + from.year);
    return start + " – " + until.day + " " + until.month + " " + until.year;
  }

  function shortId(revision) {
    return String(revision).slice(0, 8);
  }

  function results(count) {
    return count + (count === 1 ? " result" : " results");
  }

  // "about" marks a first-seen date backfilled from the earliest submission.
  function about(row) {
    return row.first_seen_inferred ? "about " : "";
  }

  // `index` is the row's place in the newest-first list; the first older revision is "Previous".
  function optionLabel(row, index) {
    if (row.current) {
      return [
        "Latest",
        "since " + about(row) + day(row.first_seen_at),
        shortId(row.revision),
        results(row.result_count),
      ].join(" · ");
    }
    // No end date happens when Latest was first seen earlier than this revision (a rollback,
    // or an empty Latest): the range is open, so it reads "from".
    var when = row.until
      ? about(row) + range(row.first_seen_at, row.until)
      : "from " + about(row) + day(row.first_seen_at);
    var position = typeof index === "number" ? index : 1;
    var parts = [when, shortId(row.revision), results(row.result_count)];
    if (position === 1) parts.unshift("Previous");
    return parts.join(" · ");
  }

  // A benchmark with one revision shows plain text, never a one-item dropdown.
  function staticLabel(row) {
    return shortId(row.revision) + " · since " + about(row) + day(row.first_seen_at);
  }

  function requestedRevision(search) {
    var value = new URLSearchParams(search).get("revision");
    return value ? value : null;
  }

  function latest(rows) {
    for (var i = 0; i < rows.length; i++) if (rows[i].current) return rows[i];
    return rows[0] || null;
  }

  // An id that is not on this board always falls back to Latest, and the page says so.
  function resolveSelection(rows, requested) {
    var fallback = latest(rows);
    if (!requested) return { selected: fallback, notFound: false };
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].revision === requested) return { selected: rows[i], notFound: false };
    }
    return { selected: fallback, notFound: true };
  }

  // Latest has no parameter, so the plain URL keeps meaning "whatever is current".
  function searchWith(search, row) {
    var params = new URLSearchParams(search);
    if (row.current) params.delete("revision");
    else params.set("revision", row.revision);
    var text = params.toString();
    return text ? "?" + text : "";
  }

  // After a bump, Latest is empty until results arrive; point to the newest earlier revision that
  // has any, rather than switching to it silently.
  function emptyLatestPointer(rows, selected) {
    if (!selected || !selected.current || selected.result_count > 0) return null;
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (row.current || row.result_count === 0) continue;
      var isPrevious = rows.indexOf(row) === rows.indexOf(selected) + 1;
      return {
        revision: row,
        text:
          "No results under this revision yet. " +
          results(row.result_count) +
          " under " +
          shortId(row.revision) +
          (isPrevious ? " (previous)." : "."),
      };
    }
    return null;
  }

  // The board route's own answer for a revision it does not have. An unknown benchmark is also a
  // 404, with a different detail, and must not be mistaken for an unknown revision.
  var REVISION_NOT_FOUND_DETAIL = "Revision not found for this benchmark";

  function isRevisionNotFound(err) {
    if (!err || err.status !== 404 || typeof err.body !== "string") return false;
    try {
      var body = JSON.parse(err.body);
      return !!body && body.detail === REVISION_NOT_FOUND_DETAIL;
    } catch (e) {
      return false;
    }
  }

  // A history row's revision as the board lists it: { current } when listed, else null. A run's
  // revision comes from its client, so an id the board never had gets no link.
  function listedRevision(rows, revision) {
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].revision === revision) return { current: !!rows[i].current };
    }
    return null;
  }

  function notFoundNotice(requested) {
    return "Revision " + shortId(requested) + " is not on this leaderboard. Showing the latest.";
  }

  return {
    optionLabel: optionLabel,
    staticLabel: staticLabel,
    requestedRevision: requestedRevision,
    resolveSelection: resolveSelection,
    searchWith: searchWith,
    emptyLatestPointer: emptyLatestPointer,
    notFoundNotice: notFoundNotice,
    isRevisionNotFound: isRevisionNotFound,
    listedRevision: listedRevision,
    shortId: shortId,
  };
});
