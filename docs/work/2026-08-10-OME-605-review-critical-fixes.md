---
ticket: OME-605
stack: screamingface
status: done
started: 2026-08-10
finished: 2026-08-10
---

# OME-605 — Critical fixes from the PR #539 branch review

## Intent

Close the four blocking findings from the pre-merge review of the ScreamingFace Client
branch. Each one either spends money incorrectly or discards work the user has already paid
for, so none of them can ship. The normative contract is
[`docs/spec/2026-08-10-OME-605-review-critical-fixes.md`](../spec/2026-08-10-OME-605-review-critical-fixes.md);
the findings are inline comments on
[PR #539](https://github.com/ScreamingFace/screamingface/pull/539#pullrequestreview-4901288332).

Owner decisions taken before implementation: small symmetric async stop (not the scope
redesign), include the replay-safety marking with the status gate, and additive edits to
existing test doubles are permitted.

## Planned changes

Implemented as four commits, in dependency order (pure/self-contained first, riskiest
last).

1. **Linker source-position references** — `_evaluation/linking.py`;
   `tests/test_shape_adaptive_linking.py`.
2. **Unsequenced advisory CloudEvents** — `_engine/contract.py`; `tests/protocol_server.py`
   (new `unsequenced_log` mode), `tests/test_engine_contract.py`,
   `tests/test_client_protocol.py`.
3. **Access challenge gate + replay safety** — `_engine/access_contract.py`,
   `_engine/auth.py`, `_engine/transport.py`; `tests/test_authentication.py`.
4. **Async `cancel_active`** — `_core/ports.py`, `_engine/transport.py`,
   `_evaluation/runner.py`; `tests/test_client_run.py`, plus additive `cancel_active`
   stubs on four existing async test doubles in `tests/test_draco_vertical_slice.py` and
   `tests/test_model_parameter_preflight.py`.

## Test plan

Failing-first tests, per the spec's Verification section:

- **Linker:** a source-position `($candidate)!'x'` links (today: `PlanningError` "does not
  invoke the Candidate"); a mixed source/intent Fusion reference never emits an unresolved
  `$candidate_member_N` (today: no exception, poisoned artifact); a partial member
  reference does not report a wrong arity. Boundaries: `VarRef` with a field path,
  `$candidate_result` plumbing stays a non-reference, `$$candidate` escape, iteration
  collection.
- **Unsequenced:** the real notice wire shape (sequence keys present and null) does not
  kill a Run, end to end and in both sync and async form; unsequenced frames are still
  validated (severity, attributes, run subject); a half-declared sequence still raises;
  unsequenced lifecycle frames still raise.
- **Access:** a 202 async start is never read as a challenge and is never re-sent; the
  challenge/non-challenge status matrix; the WebSocket predicate agrees with the HTTP one;
  an unmarked request raises `access_reauthenticated` instead of replaying.
- **Async stop:** async concurrent cancellation deletes every minted capability (mirrors
  the existing sync assertion); a stop failure is reported rather than swallowed.

## Acceptance

- Each of the four findings has a test that failed first for the stated reason.
- No existing assertion weakened, deleted, or skipped.
- `uv run .claude/scripts/run_gates.py screamingface` green on each commit.

## Outcome

- **Actual files:** as planned, plus three not foreseen. `_core/wire.py` now owns the
  replay-safety marker, because sourcing it from the Access module would have dragged native
  crypto into `client.py`'s deliberately cheap import path. `client.py` and
  `_engine/benchmark.py` mark their reads replay-safe — the plan only listed minting and
  stopping, which would have turned every catalogue read into an error on an expired session.

- **Commits:**
  - `fd720862` — docs: spec + ledger
  - `e754f25f` — fix: Candidate references in URL4 source position
  - `d821c22d` — fix: out-of-band notice no longer kills a paid Run
  - `298241d8` — fix: never replay a paid Run start after an Access login
  - `f7bb119e` — fix: stop paid Runs when an async Evaluation is cancelled

- **Gates:** `run_gates.py screamingface` green on every commit. 605 passed, 1 skipped
  (from 561); coverage 95.04% against the 95% floor.

## Deviations

1. **One reported defect was not real.** The review claimed `_start_sync` re-issues the Run
   start up to seven times on a non-202. It does not — the loop breaks on anything that is
   not the attachment-registration problem it retries. No change made. The PR comment
   carrying that claim should be corrected.

2. **The async fix needed a different shape than the plan assumed.** The plan said to mirror
   the synchronous sweep-before-cancel ordering. That is necessary but not sufficient:
   `asyncio.gather` cancels its children and re-raises only once they have all unwound, so
   the registry is already empty when the handler runs. Instrumentation confirmed two
   capabilities minted and zero visible to the sweep. A cancelled Run now keeps its
   capability registered and the sweep clears it. The synchronous path is unaffected — its
   sibling threads are still mid-Run when the sweep reads the registry.

3. **Two production functions were split to satisfy the complexity gate** —
   `_text_references` into leaf and child walks, and the async `run` into `run` plus
   `_connected_run`. Behaviour unchanged.

4. **Three existing tests were modified, plus four test doubles** (owner-authorised).
   `test_authentication.py`'s three login-and-retry tests drove a catalogue read and now
   declare it replay-safe, which is what `Client._http_get` does in production; their subject
   and assertions are unchanged. The four async fakes gained a no-op `cancel_active`.

5. **`--skip-append-only` was used from the second commit onward.** `tests/protocol_server.py`
   gains a mode (36 insertions, 0 deletions) and the three tests above changed, which the
   check reads as modified fixtures. This is the mechanised form of the rule the owner
   overrode for this unit; every edit is additive or intent-preserving.

6. **Rebased onto 36 newer commits before pushing.** The work was written against
   `65790f41`, which was two days stale; `origin/OME-605-screamingface-client` had advanced
   by 36 commits. Both branches shared that base, so this was an ordinary rebase, not a
   history rewrite.

   `eda5b722 fix(screamingface): surface event stream failures` had already landed the
   `stream_failed` re-attach that the review raised as an Important finding, and it changed
   `_advisory_error` to return `(code, message)` — the same function Fix 2 touched. Per the
   owner's standing instruction to prefer the remote fix on any overlap, `_advisory_error`
   is the remote's version verbatim, including dropping the log line this unit had added to
   it. Only genuinely new code survived the resolution: the advisory-log routing and
   `_advisory_log` itself, neither of which the remote has a counterpart for.

   `_AsyncReplayTransport`, a test double added by those commits, inherited a synchronous
   `cancel_active` and needed an asynchronous override to satisfy the widened Protocol. It
   was amended into the async commit so that no commit on the branch fails the type gate.

## Follow-up work to file

- The async stop registry lives on the transport, so two concurrent Evaluations sharing one
  Client still stop each other's Runs.
- The `len(candidates) == 1` short circuit bypasses the interruption handler in **both**
  runners, so a single-Candidate Evaluation orphans its capability in the synchronous path
  too. Measured, not inferred.
- A distinct server-side CloudEvent type for advisory notices, so the Client does not have to
  discriminate on the absence of a `sequence`.
