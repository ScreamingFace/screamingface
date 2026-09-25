# OME-1326 — Sending what the cache saved

Client half of `OME-1251` D5. Board half: `OME-1325`, PR #1055.

## §1 What is sent

One new key on the submission: `cache_saved_cost_usd`, the **provider-reported** saving summed
across the run's spans. It already exists client side on `_RunOutcome`; this unit carries it the
rest of the way.

`run_cost_usd` is unchanged: it stays the real spend. The board adds the two at the point of use
(D5), so the client never pre-sums them.

## §2 Only the reported figure

`cache_saved_cost_archive_usd` stays internal. **D3.** It is measured from a different call of the
same model and kind, so it is not provably this run's. `OME-1252`'s structural test forbidding a
third accumulator must keep passing, and nothing here may add the two.

## §3 Omitted when null, not sent as null

A run with no saving sends **no key**, rather than `"cache_saved_cost_usd": null`.

- **The payload for an uncached run is byte-for-byte what it is today.** The exact key-set guard in
  `tests/test_leaderboards.py` stays green without an edit, so no append-only exception is needed.
- **It limits the blast radius of a mis-ordered release.** If this client ever reached users before
  the board accepted the field, only runs that actually carry a saving could 422. Uncached runs
  would keep working.

## §4 The board contract it must satisfy (PR #1055 at `0357d7bd`)

| client sends | board |
| -- | -- |
| `complete` + amount + saving | accepted, the main case: a priced cached run |
| `partial` + saving, no amount | accepted |
| `partial`, no saving | accepted (the rollout case) |
| `unavailable` + any saving | **refused** |

The SDK's derivation already guarantees the last row cannot happen: it returns `partial` whenever
the reported sum is present, including 0. A test pins that the pair is never produced, so a future
change to the derivation cannot silently start 422ing.

## §5 `CandidateResult` carries it, and the export keeps it

`CandidateResult` is public and snapshotted, so the snapshot moves and the CHANGELOG records it.

`to_dict()` emits the field. Review of PR #1017 (Keelan, F2) found that omitting a cost field there
silently loses evidence on export: a reader rebuilding state from the report cannot recover it.

## §6 Out of scope

- what the board does with the number: `OME-1325`
- `archive_matched` money: D3
- the portal's Cost column: open on `OME-1325` phase 2
