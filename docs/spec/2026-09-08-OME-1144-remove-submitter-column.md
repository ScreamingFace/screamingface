# OME-1144 — Remove the Submitter column from the leaderboard table

Status: owner-approved · Stack: scoreboard

## Problem

The benchmark leaderboard table renders two identity columns side by side: `Submitter` (OME-769)
and `Authors` (OME-1052). `_resolved_authors` falls back to `[submitted_by]` whenever a submission
carries no explicit author list, so for the common case the two cells render byte-identical text.
Observed on `leaderboard.dev.screamingface.ai/benchmark.html?id=draco-3pass`.

## Decisions

### D1 — The leaderboard table drops the Submitter column

The column config and its cell render come out of `portal/benchmark.js`. The table then shows one
identity column, `Authors`.

### D2 — Nothing behind the portal changes

`submitted_by` stays on `Score`, on `LeaderboardEntry`, on `ScoreSchema`, and on every API
response. This is a display change on one page. The private JSONL export and the staff surfaces
keep the field untouched.

### D3 — `formatSubmitter` stays

OME-1144 says to drop it "if no other caller". There is another caller: `portal/spec.js:17`
renders the submitter on each spec's history table, and `portal/spec.html` keeps its
`<th>Submitter</th>`. So `portal/main.js` is not modified and the helper keeps its export.

### D4 — The spec detail page is out of scope

The ticket scopes the change to the benchmark leaderboard table. The spec page shows one row per
submission rather than one row per spec, and its submitter column is not redundant with anything
there today. It is left alone.

### D5 — Accepted consequence: the surviving column is the unverified one

`submitted_by` is resolved by `_resolve_submitter` from verified Cloudflare Access identity.
`authors` is a client-supplied list on `ScoreSubmission` that nothing verifies. Removing Submitter
therefore leaves the public table showing only a claim made by the submitter. The owner reviewed
this trade and chose the removal as filed (2026-09-08); it is recorded here so the next reader does
not rediscover it as a defect. The verified value remains available on the spec page and the API.

## Verification contract

- the rendered leaderboard table has no `Submitter` header and no submitter cell;
- the `Authors` column still renders, including its em-dash empty state;
- every remaining column keeps its position and its sort behaviour;
- `portal/spec.js` and `portal/spec.html` still render the submitter;
- `portal/main.js` still exports `formatSubmitter`;
- full Scoreboard gates green.

## Confidence-Gate exception

`tests/unit/test_multiple_authors.py::test_portal_renders_author_lists_in_leaderboard_and_history`
asserts the removed column config and cell render as source text (lines 196–197). Those two
assertions describe the behaviour this unit deliberately removes, so they cannot survive it. The
owner approved the removal as filed, which entails the edit. The test's other five assertions —
`P.formatAuthors(entry.authors)`, both `spec.js` renders, and both `spec.html` headers — are kept
unchanged, and a new test pins the absence, so coverage of this area does not shrink.

## Non-goals

- changing `submitted_by` anywhere behind the portal;
- changing the spec detail page;
- changing how authors are collapsed or disambiguated (OME-1109);
- adding a conditional "hide when identical" behaviour.
