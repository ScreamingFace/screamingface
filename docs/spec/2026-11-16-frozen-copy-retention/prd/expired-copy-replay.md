# PRD: a replay of an expired copy, and the public promise

**Source:** ans:Q2, ans:Q8, ans:Q10, ans:Q22, ans:Q24, ans:Q32 · **Priority:** P1 (released
with the expiry rule, 30 days before the first copy can expire)
**Lifecycle:** existing (characterize + delta) in `apps/aigateway`, `apps/screamingface-engine`,
`public-docs`, `CONTEXT.md`
**Owner:** unassigned

Paths are relative to the repo root.

## 1. Summary and user story

As a user who replays a pinned cache, I want a clear answer when the cache expired, so that I
know the cause and what to do.

As a reader of the docs, I want to know how long a pinned cache is kept, before I rely on it.

The user learns the rule from the public docs and from the error message. The SDK does not
change. `[stated ans:Q8]`

## 2. Background and constraints

- "Docs only: update the public docs and the error message. No SDK change." `[stated ans:Q8]`
- The states `abandoned` and `expired` are defined in `erd.md` §2.2. The sweep that sets them is
  in `prd/copy-sweep.md`.

### 2.1 Current behavior

- The public docs say that a pinned cache "is kept forever".
  `[existing public-docs/src/pages/learn/CachingPage.vue:87-90]`
- The glossary calls a Pinned Cache "The permanent record of every model answer and web-tool
  result of one captured run". `[existing CONTEXT.md:187]`
- The E14 design records the owner decision E14 Q15 "keep copies forever" and the invariant F2
  "Copies and rows are kept forever (Q15)".
  `[existing docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md:37]`
  `[existing docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md:90]`
  The gateway model repeats F2 in its docstring.
  `[existing apps/aigateway/src/aigateway/core/frozen_copy/models.py:7]`
- The gateway answers a replay of an unknown, open or malformed copy id with one 404,
  `frozen_copy_unavailable`.
  `[existing apps/aigateway/src/aigateway/routes/frozen_copies.py:94-110]`
- The engine reads only a 404 as a replay refusal.
  `[existing apps/screamingface-engine/src/screamingface_engine/capture_outcomes.py:90-105]`
  It maps `frozen_copy_unavailable` to its own fixed text "the frozen copy is not available for
  replay", as a permanent failure.
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1553-1571]`
  Each other failure status with no replay header becomes the same code and text.
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1536-1550]`
- The web-tool lookup of a replay has the same two codes, with its own fixed texts.
  `[existing apps/screamingface-engine/src/screamingface_engine/world/web_tools.py:152-175]`
- The engine has no check of the copy before the run. The first replay call finds the problem.
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1520-1532]`
- The SDK shows the engine's message text as it is. Its reproduction logic reads only the code
  strings `frozen_copy_miss` and `frozen_copy_unavailable`.
  `[existing packages/screamingface/src/screamingface/_reproduction.py:62-68]`
- New decisions go into the E14 design as new rows that start with "Reverses Qn" or "Narrows
  Qn". Old rows are not edited.
  `[existing docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md:53-54]`

**Delta.** The gateway answers 410 for an `expired` copy. The engine gives that case its own
message and keeps the code. The docs, the glossary and the design record state the new rule.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **R1. A replay of an expired copy says so.** `[stated ans:Q8]` Must
  - Given a copy with status `expired`
  - When a replay sends a chat call or a web-tool lookup for it
  - Then the gateway answers 410 with `detail.code = frozen_copy_expired`,
    `detail.state = expired`, and no `X-AIGW-Replay` header
  - And the engine fails the call as permanent with the code `frozen_copy_unavailable` and the
    message: "the frozen copy expired: no leaderboard score used it in its retention period, and
    the gateway deleted its answers"
  - And the user sees that message in the failure of the replay.
- **R2. The public docs state the rule.** `[stated ans:Q8]` `[stated ans:Q32]` Must
  - Given the page "Caching", section "Reproducing a submission"
  - Then it no longer says "kept forever". It says, in the words of the docs: a pinned cache
    that a leaderboard score uses is kept for as long as the score exists on the board; a pinned
    cache with no submitted score is deleted 30 days after it is sealed (a run seals its pinned
    cache when it ends); for a pinned cache that was sealed before the rule started, the 30 days
    count from the start of the rule; submit the score before that time; a replay of a deleted
    pinned cache fails with a message that says it expired.
  - And it gives no date for the start of the rule, and it names no release day and no person.
    The docs state the rule only. `[stated ans:Q32]`
  - And it says that the rule also applies to a local engine: a pinned cache in a local
    gateway is deleted 30 days after it is sealed, because no score can use it there.
    `[stated ans:Q22]`
  - And it says which submit is refused `[stated ans:Q10]`: a score can be submitted with a
    pinned cache only when the service holds that pinned cache complete. A run whose pinned
    cache was not closed, and a run on a local engine with capture, cannot be submitted with
    their pinned cache.
- **R3. The design record states the decision.** `[stated ans:Q2]` Must
  - Given `02-frozen-copy-design.md`
  - Then its decision table has four new rows, Q33 to Q36 (text in §4.3), and F1 and F2 have
    the new text of `erd.md` §2.5 (I6, I7)
  - And the docstring of the gateway model has the same new F1 and F2
    `[existing apps/aigateway/src/aigateway/core/frozen_copy/models.py:6-7]`.
- **R4. The glossary is true.** `[implied]` Must
  - Given `CONTEXT.md`, entry "Pinned Cache"
  - Then the first sentence does not say "permanent". Proposed text: "The record of every model
    answer and web-tool result of one captured run. It is kept while a Leaderboard Score names
    it; if no Score names it, the AI gateway deletes it 30 days after it is sealed."

### 3.2 Error paths

- **R5. A replay of an abandoned copy.** `[implied]` Must
  - Given a copy with status `abandoned`
  - When a replay reads it
  - Then the gateway answers the same 404 `frozen_copy_unavailable` as for an `open` copy.
  - Reason: an abandoned copy was never sealed, so no user ever had a replayable copy. The
    answer does not change for them.

### 3.3 Derived scenarios (risk order)

- **R6. An engine that does not know the new status.** `[implied]` H×M Must
  - Given the gateway has this change and the engine does not (production runs an older engine
    for some days after each merge)
  - When a replay reads an `expired` copy
  - Then the old engine fails the call as permanent with `frozen_copy_unavailable` and its old
    text. No retry occurs, and no crash.
  - This is true today: a failure status with no replay header becomes that code
    `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1536-1539]`.
    The 410 must thus never carry the `X-AIGW-Replay` header.
- **R7. The code string does not change.** `[stated ans:Q8]` H×M Must
  - Given the engine has this change
  - Then the failure code of R1 is exactly `frozen_copy_unavailable`. The engine adds no new
    code to the failures that a client sees.
  - Reason: the released SDK decides the reproduction result from this code string
    `[existing packages/screamingface/src/screamingface/_reproduction.py:62-68]`.
- **R8. The gateway's text is not passed on.** `[implied]` M×M Must
  - Given the 410 body carries a `message`
  - Then the engine uses its own fixed text and not the text of the gateway, as it does for the
    two codes of today
    `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1556-1558]`.
- **R9. The docs are public before a copy can expire.** `[implied]` H×L Must
  - Given pull request C1 is merged (the production release of C1 starts the 30-day clock of
    the copies that exist, `erd.md` §5)
  - Then pull request C3, with the docs change of R2, is merged after C1 is merged. The first
    copy cannot expire until 30 days after the production release of C1, so the docs are public
    before the first expiry.
  - The docs give no date, and C3 is not tied to the day of a release. `[stated ans:Q32]`
  - No code waits for the docs. `[stated ans:Q22]` If the docs are late, the notice is shorter
    by that delay.
- **R10. A partial replay.** `[implied]` M×L Must
  - Given a replay with `limit=n` of an `expired` copy
  - Then the result is the same as R1. This PRD adds no special case.
- **Not applicable.** Concurrent replays: a replay only reads. Empty state: a copy with no
  entry that expired answers as R1.

## 4. Non-functional requirements

### 4.1 Compatibility

- Gateway first, engine second, in any order of release (R6). The SDK needs no release.
  `[stated ans:Q8]`
- The studio frontend lists the two replay codes
  `[existing apps/screamingface-studio/frontend/src/lib/engine/run-result.ts:45-46]`. It needs no
  change, because the code does not change (R7). `[implied]`

### 4.2 Text rules

- Docs text uses "pinned cache". The glossary says to avoid "Frozen Copy" in text for users
  `[existing CONTEXT.md:190]`.
- The engine message uses "frozen copy", as the two messages next to it do
  `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:1546-1550]`.
  `[proposed]`
- The engine message names no number of days. The period is a gateway setting, and the engine
  must not repeat its value. `[proposed]`

### 4.3 The rows for the E14 decision table

| Id | Question | Answer |
|---|---|---|
| Q33 | Retention (2026-11-16) | Reverses E14 Q15. A copy that a Score claims is kept forever. A sealed copy with no claim is deleted 30 days after its clock starts. Spec: `docs/spec/2026-11-16-frozen-copy-retention`. |
| Q34 | Open copies (2026-11-16) | An open copy that gets no entry for 24 hours is abandoned, and its entries are deleted. A replay never read an open copy. |
| Q35 | Clock of copies sealed before the rule (2026-11-16) | Their 30 days start when the rule goes live, not at their seal. The release writes that time into the database; no setting holds it. The public docs name no date. |
| Q36 | Notice to users (2026-11-16) | Public docs and the error message only. No SDK change. |

### 4.4 Observability

- The gateway logs nothing new for a 410. The request log line already shows the status.
  `[proposed]`

## 5. Out of scope

- A new field in the SDK result that shows the expiry date. `[stated ans:Q8]`
- A check of the copy before a replay run starts. `[proposed]`
- A change of the docs for the request cache ("Cache entries do not expire"). That text is about
  a different table and stays true. `[stated ans:Q1]`
- A banner or a mark on the leaderboard for a Score whose copy expired. A claimed copy does not
  expire, so a Score on the board keeps its copy. `[implied]`

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

**Order:** gateway, then engine. Risk first. The text changes have no test (see below the table).

Test files: `apps/aigateway/tests/unit/test_frozen_copy_replay.py` (add),
`apps/screamingface-engine/tests/unit/` (the files that test `replay_refusal_code`,
`_replay_refusal` and `FrozenToolResults.lookup` today; find them with a search for
`frozen_copy_unavailable`).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| CH-1 | CHAR: a replay of an open or unknown copy answers 404 `frozen_copy_unavailable` | unit | `[existing routes/frozen_copies.py:94-110]` | — | passes today (`test_replay_of_an_open_or_unknown_copy_is_404_unavailable`) |
| CH-2 | CHAR: the engine maps a 404 `frozen_copy_unavailable` to its fixed text, permanent | unit | `[existing connector.py:1567-1568]` | — | passes today |
| CH-3 | CHAR: the engine maps a failure status with no replay header to `frozen_copy_unavailable` (R6) | unit | `[existing connector.py:1536-1539]` | — | passes today; it is the proof for old engines |
| R-1 | gateway: a chat replay of an `expired` copy answers 410 `frozen_copy_expired`, `state: expired`, with no `X-AIGW-Replay` header (R1) | unit | `[stated ans:Q8]` | H×M | new branch in `_sealed_copy` |
| R-2 | gateway: a tool lookup of an `expired` copy answers the same 410 (R1) | unit | `[stated ans:Q8]` | H×M | both routes use `_sealed_copy` |
| R-3 | gateway: a replay of an `abandoned` copy answers 404 `frozen_copy_unavailable` (R5) | unit | `[implied]` | M×M | falls into the branch of today |
| R-4 | engine: a 410 `frozen_copy_expired` gives code `frozen_copy_unavailable`, permanent, with the expired text (R1, R7) | unit | `[stated ans:Q8]` | H×M | extend `replay_refusal_code` and `_replay_refusal` |
| R-5 | engine: the expired text is the engine's own, also when the gateway sends a different `message` (R8) | unit | `[implied]` | M×M | fixed string |
| R-6 | engine: a tool lookup that gets 410 `frozen_copy_expired` raises `frozen_copy_unavailable` with the expired text (R1) | unit | `[stated ans:Q8]` | M×M | same mapping in `lookup` |
| R-7 | engine: a 410 with a different code, or with no JSON body, is still `frozen_copy_unavailable` with the old text | unit | `[implied]` | M×L | no change to the fallback |
| R-8 | gateway: a provenance read of an `expired` copy answers the same 410 with no `X-AIGW-Replay` header; an `abandoned` copy stays the 404 (R1) | unit | owner decision 2026-11-23 | M×L | the read uses `_sealed_copy` |

Items R2, R3 and R4 are text edits with no automated test: `CachingPage.vue` (the section
"Reproducing a submission"), `02-frozen-copy-design.md` (rows Q33–Q36, F1, F2),
`apps/aigateway/src/aigateway/core/frozen_copy/models.py:6-7` (F1, F2), `CONTEXT.md:187`. The
reviewer checks them against §3.1, §4.3 and `erd.md` §2.5 (I6, I7). The reviewer also searches the
public docs for "kept forever" in text about the pinned cache; no such text must remain. The
reviewer also confirms that the page gives no date for the start of the rule `[stated ans:Q32]`.

### 7.1 Implementation notes

- **Gateway.** In `_sealed_copy`, read the status after the lookup: `sealed` → return;
  `expired` → raise 410; all other cases → the 404 of today. Shape in `contracts.md` K3.
- **Engine.** `replay_refusal_code` reads only a 404 today. Add the one case: status 410 with
  `detail.code == "frozen_copy_expired"`. Keep the engine's own list of codes
  `[existing apps/screamingface-engine/src/screamingface_engine/error_text.py:82-83]` as it is:
  the code that leaves the engine is still `frozen_copy_unavailable`.
- **Do not** add `frozen_copy_expired` to the codes that the engine sends to a client.
- **Do not** edit the old rows Q15 or the text of old specs. Add rows, as E14 Q31 did for E14 Q22.
