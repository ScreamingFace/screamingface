# OME-909 — Implementation plan

## Frame

Add a narrow submit-response fact at the API seam, carry it through the public Client value, and
render it on the existing published-score card. Do not touch persistence or leaderboard selection.

## Changes

1. Record the submit-time response, mismatch predicate, snapshot timing, and Client presentation
   decisions before implementation.
2. Add focused failing Scoreboard tests for mismatch creation/replay, match, revisionless board,
   OpenAPI, and unchanged leaderboard exclusion.
3. Add the typed notice and POST response schemas; snapshot the registered revision before the
   write and build the optional notice from the persisted score.
4. Add focused failing Client tests for decoding, validation, public exports, and warning-card
   rendering, including HTML escaping and the absent-notice path.
5. Add the immutable public notice value, response decoding, and SFDS warning block.
6. Run focused tests, then the complete Scoreboard and `screamingface` gates.
7. Complete the ledger, commit, push, open a PR, link it from Linear, and move OME-909 to In Review.

## Non-goals

- modifying the ranking query or making mismatched submissions fail;
- populating GET score responses with a ranking snapshot;
- folding OME-922 partial-run feedback into this revision-specific notice;
- portal or database changes.
