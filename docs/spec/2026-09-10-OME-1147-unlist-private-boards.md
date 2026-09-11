# OME-1147 — Unlist private boards from the portal index

Status: owner-approved · Stack: scoreboard

## Problem

`healthbench-worst30` is the Fusion Monsters entry challenge, assembled by us rather than proposed
by academics. It appears on the public portal index as a card with no entries, because
`initIndex()` renders every benchmark `/v1/benchmarks` returns and a private board yields no rows
to an anonymous visitor.

The owner's requirements (2026-09-09): the index shows only established benchmarks; `sf.leaderboards`
still lists everything so participants can submit against the challenge; nobody outside the
OpenMined product team sees its rankings.

Two of the three already hold. `get_leaderboard` routes private boards to `_private_leaderboard`,
and `ScoreStore.list_benchmarks()` returns every board unfiltered. Only the index is wrong.

## Decisions

### D1 — The index filters on `visibility`, client-side

`BenchmarkSchema` already exposes `visibility`, so `/v1/benchmarks` already carries what the portal
needs. No API change, no schema change, no migration, no seed change.

### D2 — Filtering happens before the boards are fetched

`initIndex()` currently issues one `fetchBoard()` per benchmark and then renders. Filtering first
also stops the page requesting a board it will never draw. That is incidental to the ask and is
the obviously correct ordering, so it is stated rather than left to chance.

### D3 — The rule is FAIL-OPEN

A benchmark whose `visibility` is absent, null, or an unrecognised string stays listed. This is a
cosmetic filter, not an access control: the server already refuses private rankings to anyone who
should not see them. A stricter client-side rule buys no privacy and risks silently erasing a
board from the public catalogue on a serialisation change.

INVARIANT: only the exact string `"private"` removes a card.

### D4 — The logic lives in `leaderboard-logic.js`

`index.html` already loads that module before `main.js`, it is already exercised by
`tests/portal/leaderboard-logic.test.js`, and that file is already named in the scoreboard gate
list. A helper in `main.js` would be untestable, and a new test file would mean editing the gate
list by name (`OME-798`) for one function. Its header is widened to say it holds the portal's pure
decisions rather than only the board's.

### D5 — Visibility stands in for provenance, and says so

The owner's rule is *established versus ours*. Filtering on `visibility` produces exactly that
result today, because `healthbench-worst30` is both the only board we assembled and the only
private one. They diverge the moment we run a challenge on an academic benchmark or publish one of
our own. `OME-1112` — "Benchmark catalogue records where each benchmark came from" — is where the
provenance rule belongs, and the code says so at the filter.

### D6 — Two docstrings are corrected

`routes/leaderboard.py` documents `list_benchmarks` as "List registered public benchmarks" while
the store returns private boards as well. That behaviour is what requirement 2 depends on, so the
docstring must state it. The index's empty-state copy carries the same slip.

## Verification contract

- a private benchmark is dropped from the index;
- a public one is kept;
- absent, null and unrecognised visibility values are kept (D3);
- `initIndex` actually calls the helper — the rule existing is not the rule being used;
- `/v1/benchmarks` still returns private boards, unchanged;
- full Scoreboard gates green.

## Non-goals

- any change to who can read rankings — `OME-894`'s behaviour is untouched;
- a `listed_in_portal` field, a migration, or a seed change;
- the direct `benchmark.html?id=healthbench-worst30` URL, which still resolves and still shows
  nothing to anyone unauthorised;
- the provenance rule itself (`OME-1112`).
