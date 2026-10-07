# Cut 01 — drop the revision registry, `cache-revision` and the revisions check

**Status:** planned, waiting for owner approval · **Date:** 2026-10-07
**Changes owner decision:** Q1 ("keep old key functions") becomes "accept breakage"
(the submission records its cache revision, so a changed revision is detected, not repaired).

## 1. Why

A replay under an unchanged cache key is a regular chat call: the same key reads the same row. The
three replay pieces covered three edge cases. This cut keeps the one that is cheap and important and
removes two:

| Piece | Keeps / drops | Reason |
|---|---|---|
| `only-if-cached` (504 on a miss or a bypass) | **keep** | A miss must fail visibly and never pay a provider. |
| Revision registry + `cache-revision` control | **drop** | Exists only to replay old revisions after a cache-key change (Q1). About half of B1, plus a rule that frozen key code must never change. |
| `GET /v1/cache/revisions` check (5.3) | **drop** | Only a guard against an old gateway that ignores `only-if-cached`. The deploy rule covers it: gateway before engine. |

## 2. New behaviour

1. The gateway still computes the cache revision label and sends `X-AIGW-Cache-Revision` on every
   response that ran the cache stage, including the 504s. (unchanged)
2. A submission still stores `cache_revision`. (unchanged)
3. A replay sends `cache: {"only-if-cached": true}` only. There is no `cache-revision` field.
4. On a 504 miss during a replay, the engine compares the response's revision header with the
   label it was given:
   - different label → case failure `cache_revision_changed` (the cache key changed since the
     submission, so the old rows cannot be reached);
   - same label → `replay_cache_miss` (as today).
5. A hit is never failed because of a label difference. The label covers every provider, so a
   change for one provider does not change the keys of the others; an openai-only run can still
   replay exactly after an openrouter bump.
6. `sf.reproduce` reports `failed / cache_revision_changed` in place of `failed /
   unknown_cache_revision`.

Known limit (accepted with the Q1 change): after any cache-key change, older submissions whose calls
are affected stop being replayable. They show `cache_revision_changed`.

## 3. Changes by PR

The stack and PR count do not change. Each change is one new commit on its own branch, then the
branches above are rebased (as before).

### B1 — gateway (most of the cut)

Remove:
- `RevisionEntry`, `REGISTRY`, `entry_for`, `cache_key_for`, `frozen_projections`, `frozen_rules`,
  the immutability wrapping, the bump procedure in the docstring.
- `tests/fixtures/cache_revisions/` golden vectors and `scripts/generate_cache_revision_vectors.py`.
- The startup "label not in registry" check in `main.py`.
- The `cache-revision` control: parse, `GlobalCacheControls.revision`, the planner branch for old
  labels, `_refuse_unusable_revision`, the 400 codes `unknown_cache_revision` and
  `cache_revision_requires_only_if_cached`.
- `routes/cache_revisions.py` (`GET /v1/cache/revisions`) and its router line.
- Tavily lane: `cache_revision` on lookup and fill, and `cache_revision_read_only`.
- The private `_key_result` refactor in `global_keys.py`: revert to the original single function
  (it existed only for `cache_key_for`).

Keep:
- `register_key_revision` (one line per provider plugin) and `current_label()` in a small core module
  (rename `revision_registry.py` → `cache_revision.py`).
- `X-AIGW-Cache-Revision` on chat responses (incl. 504s) and on Tavily lookups.
- `only-if-cached`: parse, 504 `cache_miss` / `cache_bypass` before credential resolution,
  `conflicting_cache_controls`, `malformed_cache_controls`, the refusal log line.
- The regenerated hit-contract fixture (the header is still on every hit).

Tests: delete the B1 test files and cases that cover only removed behaviour (registry, golden keys,
immutability, planner old-label, startup, revisions route, Tavily revision). These are this PR's own
new tests, so the append-only check is not affected. Keep and adjust the only-if-cached and header
tests.

### B2 — engine Tavily cache

No change (B2 never sent a revision).

### B3 — engine capture + replay

Remove:
- The K10 revisions check: the GET, the per-run memo and its lock, the deadline handling, and their
  tests.
- `cache-revision` in the replay chat body (send only `only-if-cached`).
- `cache_revision` in the replay Tavily lookup.

Change:
- Failure code `unknown_cache_revision` → `cache_revision_changed` (engine `error_text.py`,
  `benchmarks/contract.py`, SDK mirror `_report_primitives.py`, and the two exact-set tests already on
  the approved list).
- In replay mode, map a 504 to `cache_revision_changed` when its `X-AIGW-Cache-Revision` differs from
  the replay label; otherwise `replay_cache_miss`. Same rule for a Tavily lookup miss.
- README "Replay mode": drop the revisions check; keep the deploy rule (gateway, then workers, then
  the App).

Keep: the tally and rule C2, capture attributes, `X-Cache-Replay` (it still carries the label, now
used for the comparison in step 4 of §2), the start-route echo, the `cache.replay` summary
attribute, D1–D3.

### A1, B4, A2 — scoreboard and SDK metadata

No change.

### B5 — SDK

- `_classify`: reason `unknown_cache_revision` → `cache_revision_changed`; same check order.
- `_require_replay_statement`: the replay codes are `replay_cache_miss` and `cache_revision_changed`.
- Tests: rename the cases; no new behaviour.

### C1 — docs

- Remove "older revisions stay replayable" and every mention of naming an old revision.
- Explain `cache_revision_changed`: the cache key changed since the submission, so the score cannot
  be replayed exactly.
- Keep the single `only-if-cached` mention.

### Spec

- `00-overview.md`: record the Q1 change (with date) and update the design summary.
- `prd/gateway-cache-revision.md`: rewrite as "cache revision label + only-if-cached". Remove G4, G5,
  G8, G9, G12–G16, G21 and their TDD rows.
- `erd.md` §4: the registry becomes "a computed label, no stored entries".
- `contracts.md`: K1 loses `cache-revision`; K2 loses `cache_revision`; K10 is removed; K3 explains the
  new mismatch rule.
- `prd/reproduce.md`: R5 (old-label replay) becomes "a changed revision → `cache_revision_changed`";
  R11 updated.

## 4. Order of work

1. Spec docs (this branch).
2. B1 cut commit → gates.
3. B3 cut commit (rebased on the new B1 and B2) → gates.
4. B5 and C1 cut commits (after rebasing A1 → B4 → A2 onto the new B3) → gates and docs build.
5. Final gates at the top of the stack, design review of the B1 and B3 cuts, update the walkthrough
   artifact.

Each step uses the same model routing as before: a Sonnet implementer from this plan, then an Opus
design review.

## 5. Size

Mostly deletions. Rough estimate: about −1,400 lines in B1 (code and its own tests), about −300 in B3,
and small edits in B5, C1 and the spec. Less than one working day.

## 6. Risks

| Risk | Mitigation |
|---|---|
| A replay against an old gateway that ignores `only-if-cached` pays a provider. | Deploy rule: gateway before engine. The engine still records the response label, and the SDK still requires the `cache.replay` statement. |
| A key change makes every affected submission non-replayable. | Accepted by the Q1 change; detected and reported as `cache_revision_changed`. |
| A label difference is mistaken for a key change on a hit. | Rule §2.5: a hit is never failed on the label. |
