/* Pure ranking / SOTA decisions for the leaderboard board (OME-769).
 *
 * FEATURE: the per-benchmark submissions board — ranked rows, score bars, and
 * the SOTA medal on the best reproducible result.
 *
 * WHY this file exists separately from benchmark.js: these three functions decide
 * what the public board *claims* — which row (if any) is presented as
 * state-of-the-art, and how long each score bar reads. Keeping them free of
 * the DOM makes them assertable in `tests/portal/leaderboard-logic.test.js`
 * without a browser, which the rest of the portal's rendering is not.
 *
 * Loaded as a plain <script> in the browser (exposing window.SFLeaderboardLogic)
 * and via require() in tests. No build step, matching the rest of the portal.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SFLeaderboardLogic = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // AIDEV-NOTE: `sotaScore` and `isSota` are intentionally NOT called by
  // benchmark.js yet. The SOTA medal was descoped from OME-769 in review because
  // `/v1/leaderboard` returns one row per spec chosen by score alone, so a
  // spec's verified run is invisible whenever that spec also has a higher
  // unverified run — the medal could name the wrong reproduced winner and no
  // client-side logic can recover the missing row. OME-771 filters the pool in
  // the query (`?pool=verified`), which makes the verified run a real row; these
  // functions are kept, tested, and correct so the medal can be wired there
  // without rediscovering the invariant below.
  //
  // INVARIANT: only a reproducible entry may ever be presented as SOTA. Returns
  // null when nothing has been reproduced — the medal is then shown nowhere,
  // rather than falling back to the best self-reported score. A board that
  // badged an unverified claim would be asserting OpenMined reproduced a run it
  // never did, which is exactly what the page's own disclaimer denies.
  //
  // AIDEV-NOTE: `verified_by_screamingface` is the only reproducibility signal the
  // Scoreboard API exposes today, and since OME-820 it is a placeholder that
  // asserts NOTHING: the default is true and no service re-runs submissions, so a
  // true value certifies nothing. Rows predating OME-820 keep false (D5 forbids a
  // backfill), so `?pool=verified` would not narrow the pool to *everything* — it
  // would split on submission date while presenting itself as a verification
  // filter, which is worse. That is why nothing calls these functions yet.
  //
  // OME-771 intends to source the signal from the SF engine instead ("have we run
  // this URL4 before" — i.e. a global-cache hit), and OME-821 gives the field a
  // real meaning. When either lands, TWO lines move: the predicate below, and the
  // one-line `entry()` helper at the top of leaderboard-logic.test.js, which names
  // `verified_by_screamingface` when building fixtures. The assertions themselves do
  // not change — they pin the invariant above, not the source of the signal.
  //
  // AIDEV-NOTE: this note used to say "change the predicate and nothing else",
  // which was wrong: the fixtures name the field too. Corrected in review of #588,
  // because "nothing else" is exactly the sort of promise a later reader trusts
  // instead of checking.
  function isReproducible(entry) {
    return entry.verified_by_screamingface === true;
  }

  // INVARIANT: strict `=== true`, mirroring isReproducible. This mark is a public claim
  // about money, and the field is absent from any server older than OME-923 part B — an
  // absent or junk value must render as "not marked" rather than guess. A truthy test
  // would mark on the string "false" across a version skew.
  function isParetoMarked(entry) {
    return !!entry && entry.on_pareto_frontier === true;
  }

  /* ---- cost (OME-770 pass 2, delivered with OME-923) ---------------------- */

  // INVARIANT: `run_cost_usd` crosses the wire as a STRING at fixed 6 decimal places
  // ("12.400000"), never a number — OME-770 section 2.4 chose that so the form is identical on
  // SQLite and Postgres. The consequence is that every comparison must convert first:
  // "1000.000000" < "3.500000" is TRUE in JavaScript.
  //
  // INVARIANT: absent is UNKNOWN, never 0. A null must not become the cheapest row on the
  // board — that is the same rule the frontier itself rests on (OME-770 D8).
  function costNumber(entry) {
    if (!entry) return null;
    var raw = entry.run_cost_usd;
    if (raw === null || raw === undefined || raw === "") return null;
    var value = parseFloat(raw);
    return isFinite(value) ? value : null;
  }

  // WHY cost gets its own comparator instead of benchmark.js's generic numeric branch: that
  // branch is `(av || 0) - (bv || 0)`, which coerces a null cost to 0 and sorts an unpriced row
  // as the cheapest on the board. Unknown is neither cheap nor dear, so it sorts LAST whichever
  // way the column is pointed — the direction flip is deliberately after the null checks.
  function compareCost(a, b, dir) {
    var av = costNumber(a);
    var bv = costNumber(b);
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    var res = av - bv;
    return dir === "desc" ? -res : res;
  }

  function _group(text) {
    var parts = text.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return parts.join(".");
  }

  // OME-770 D2: full precision is stored, the UI rounds — a six-decimal figure must not
  // overflow the column. Sub-cent values keep four places rather than collapsing to "$0.00",
  // because a cache-heavy run costing fractions of a cent is not free, and free vs nearly-free
  // is the distinction this column exists to show.
  function formatCost(entry) {
    var value = costNumber(entry);
    if (value === null) return "\u2014";
    if (value === 0) return "$0.00";
    if (value >= 0.01) return "$" + _group(value.toFixed(2));
    if (value >= 0.0001) return "$" + value.toFixed(4);
    return "<$0.0001";
  }

  function sotaScore(entries) {
    var best = null;
    (entries || []).forEach(function (entry) {
      if (!isReproducible(entry)) return;
      if (best === null || entry.score > best) best = entry.score;
    });
    return best;
  }

  // WHY exact equality is safe on a float here: `sota` is one of the very
  // `score` values being compared, carried through unchanged — no arithmetic
  // is performed on it, so there is no rounding to drift past.
  function isSota(entry, sota) {
    if (sota === null || sota === undefined) return false;
    return isReproducible(entry) && entry.score === sota;
  }

  // WHY a copy: callers hold the fetched array as page state and re-sort it on
  // header clicks; mutating it in place would make render order depend on how
  // many times the board had already been drawn.
  function orderRows(entries) {
    return (entries || []).slice().sort(function (a, b) {
      return b.score - a.score;
    });
  }

  // Bar length normalized over the scores *on screen*, so the widest bar is
  // always full — a field of near-identical short bars carries no comparison.
  //
  // INVARIANT (OME-866): scores are benchmark-native — HealthBench worst-30 is
  // negative for every serious baseline — so the origin cannot be assumed to be
  // 0. The floor is min(0, lowest score on screen): a classic 0..1 board keeps
  // its absolute zero origin (bars mean what they always meant), a negative
  // board shifts the origin down to its own minimum instead of rendering
  // negative CSS widths. Clamped to [0, 100] either way; a zero/degenerate span
  // returns 0 rather than dividing.
  function barWidth(score, minScore, maxScore) {
    if (typeof score !== "number" || isNaN(score)) return 0;
    if (typeof maxScore !== "number" || isNaN(maxScore)) return 0;
    var floor = Math.min(0, typeof minScore === "number" && !isNaN(minScore) ? minScore : 0);
    var span = maxScore - floor;
    if (span <= 0) return 0;
    var pct = ((score - floor) / span) * 100;
    if (pct < 0) return 0;
    return pct > 100 ? 100 : pct;
  }

  // The catalogue's "Best reproducible" figure for one benchmark.
  //
  // INVARIANT: entries only, never baselines — a baseline is an imported reference number with
  // no submitter, so ranking one here would present an outside board's figure as the best
  // result on this one. Entries arrive ordered by score descending; the scan guards against a
  // future reordering.
  //
  // Returns null rather than 0 when there is nothing to report: 0 is a real score on a
  // benchmark whose scores can go negative.
  function bestEntryScore(board) {
    var entries = (board && board.entries) || [];
    var best = null;
    entries.forEach(function (entry) {
      if (!entry || typeof entry.score !== "number" || isNaN(entry.score)) return;
      if (best === null || entry.score > best) best = entry.score;
    });
    return best;
  }

  return {
    isReproducible: isReproducible,
    isParetoMarked: isParetoMarked,
    costNumber: costNumber,
    compareCost: compareCost,
    formatCost: formatCost,
    bestEntryScore: bestEntryScore,
    sotaScore: sotaScore,
    isSota: isSota,
    orderRows: orderRows,
    barWidth: barWidth,
  };
});
