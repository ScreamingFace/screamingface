# OME-1252 — Telling the board what a submitted cost is worth

Client half of `OME-1251`. Scoreboard half: `OME-822`.

## §1 What arrives and is thrown away

`SpanData` on the streaming protocol carries two counterfactual amounts
(`url4/streaming/protocol/signals.py:111,124`), and the engine populates both on **every**
emitted span (`runner/executor.py:542-543`). Summing them across a run reproduces the run's own
figures — asserted engine-side by `test_cache_saved_cost_spans.py:132-136`.

The SDK parses `cache_status` and `cache_reason` and stops. Everything else about the cache is
discarded at `_engine/contract.py:353-354`.

## §2 What the board can accept

Exactly one new field: `run_cost_status`. `ScoreSubmission` is `extra="forbid"`, so sending the
sums would 422 every submission.

**§2.1 The sums are read but not sent.** They decide `partial`; nothing on the board would read
them. A figure no surface consumes is not worth a schema change, a migration and a second deploy
ordering. `run_cost_status` already marks which rows a future lower-bound surface would apply to.

## §3 The derivation

| member | condition |
| -- | -- |
| `complete` | `pricing_version != "unpriced"` — the amount is exact and is sent |
| `partial` | unpriced, and the summed **reported** amount is non-null |
| `unavailable` | unpriced, and no reported evidence |

**§3.1 `partial` is decided by the `reported` sum ALONE.** `archive_matched` money is a real
amount measured from a different call of the same model and kind, not from this row
(`OME-1251` D3: not published). A run whose only evidence is archive-matched has nothing
publishable about its own cost, so it is `unavailable`, not `partial`.

**§3.2 The two are never summed.** `signals.py:124` keeps them as two differently-named fields
*"precisely so the two can never be summed (PRD S5): a single amount plus a label invites a
consumer to add the labels away."* The engine has a structural test forbidding a third
accumulator; mirror it here.

**§3.3 The amount and the status travel as a validated pair.** The board refuses `complete`
without an amount and an amount beside any other status, so the Client must not produce either.
An unpriced run sends the status and **no** amount.

## §4 Public surface

`CandidateResult` gains `run_cost_status` — one field, not three. The raw sums stay internal
because they are an implementation detail of the derivation, and every public field is a promise
that outlives the reason it was added.

## §5 Out of scope

- transmitting the sums (§2.1)
- the coverage counters `reported_hits` / `archive_hits` / `unpriced_hits` — engine log
  attributes only, and a `Log` is the one event kind the engine drops under backpressure
- distinguishing "no cache hits" from "hits nobody could price" — both present as a null sum,
  and separating them needs the engine to carry a reason
- providers reporting tokens rather than USD (`OME-1156`)
