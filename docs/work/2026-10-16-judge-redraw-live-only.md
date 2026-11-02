---
ticket: OME-1646
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-16
finished: 2026-10-16
---

# judge-redraw-live-only — a recorded judge reply is final

## Intent

Make a replay of recorded judge replies reproduce the recorded score. Since PR #1395
(2026-10-14) DRACO's scorer redraws every reply with no verdict outside the gateway cache, also
the seed rows that record "no verdict" on purpose, so a replay of the DRACO reference run makes
paid live calls and its scores drift. Owner rule (2026-10-16): a redraw happens only after a
live reply; a reply from the gateway cache or a frozen-copy replay is final. Spec:
`docs/spec/2026-10-16-judge-redraw-live-only.md`. Plan:
`docs/plan/2026-10-16-judge-redraw-live-only.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/world/reply_origin.py` (new)
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py`
- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_provider.py`
- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_redraw.py`
- `apps/screamingface-engine/src/screamingface_engine/world/fresh_judge_retry.py` (docs)
- tests: `tests/unit/test_reply_origin.py` (new), `tests/unit/inspect/test_judge_redraw.py`
  (append), `tests/unit/inspect/test_draco_reference_replay.py` (new),
  `tests/fixtures/draco_reference_cases.json` (new)

## Test plan

- V1 connector records live / cache / replay; nothing on failure; no-op with no watch.
- V2/V3 a cached or replayed reply with no verdict (also blank) → 1 call, no redraw; live →
  today's redraws; a 502 is still retried; the failure reports its redraw count.
- V4 4 real DRACO reference Cases reproduce `normalized_score` exactly, one call per
  criterion per pass, no call leaves the cache; the error row fails as `judge_reply_invalid`.

## Acceptance

- V1-V4 green; all gates green; no published revision moves.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. The four local Task files (draco, gdpval, frames,
  healthbench) were edited and then restored: their source is hashed into the published
  revision, and the edits moved draco, draco-3pass, gdpval-text and frames_oracle
  (`test_published_revisions.py`). The behaviour lives in the shared helper, which is not
  hashed.
- **Commits:** see `git log` on branch `OME-1646-judge-redraw-live-only` (renamed from
  `judge-redraw-live-only` at PR-open).
- **Gates:** `run_gates.py screamingface-engine` ALL GATES GREEN (append-only, ruff, format,
  pyright, layering, pytest + coverage). CI inspect job equivalent:
  `uv run --extra inspect pytest -n auto tests/unit/inspect` → 1963 passed.
- **V4 against the pre-fix code** (src reverted, new test kept): 6 of 8 failed — case
  `09456551` scored 0.5048 instead of 0.4228; the error row was scored instead of failing;
  judge calls 131 / 160 / 228 instead of 126 / 132 / 114. With the fix: 8 of 8 pass.
- **Fixture source:** built from `~/Downloads/20260806-170633-251a/eval_results/
  draco-latest.eval.jsonl` by a one-off script (picks opus-4.8 `6c59b2a0`, gemini-3.1-pro
  `4f36f602` and `09456551`, gpt-5.6-sol `a78eed67`; keeps question, rubric, answer, the
  per-pass `verdicts`, `normalized_score`, `verdict_coverage`).
- **Deviations:**
  - DRACO's `judge_redraws` metadata still books `MAX_JUDGE_REDRAWS` for every item that
    gives up, also when a recorded reply ended it with no redraw (reporting only; the score
    is right). Fixing it edits `draco.py` and moves the published draco/draco-3pass
    revisions: owner decision, follow-up.
  - The scorer docstrings in the four Task files still say "redrawn at most twice"; the rule
    is documented in `judge_redraw.py`. Same revision reason.
  - V5 ran 2026-10-16 (owner-requested; the numbers here predate the seed fix below): e2e harness `inspect_replay_stack` +
    `CacheSeededGateway` (Postgres testcontainer, NO provider credentials) seeded with
    `draco-cache-live-v5.sql.gz`; engine from this branch; roster = the owner's
    `draco-cache-replay.py` (9 solos + 8 ensembles, prompts sha256-checked). 395,896 calls
    completed, all cache hits; 0 cache opt-outs (no redraw); 88 judge misses refused
    (`profile_not_found`), $0. 13 of 17 lineups reproduce the reference exactly over the Cases
    they scored (gpt-5.6-sol 0.6481 and gemini-3.1-pro 0.2416 with the error rows left out).
    Every remaining gap is seed data, not scoring: (a) judge rows keyed to the hand-built
    rendering, which collapsed `$$` in an answer (43 answers, 88 judge calls; on a keyless
    gateway each such Case fails as `scorer_error`); (b) a fusion answer byte-identical to a solo's (pareto_lean c48/c57/c100,
    best_open_source c85) shares one cached verdict set, while the reference judged each
    independently; (c) synth rows the seed lacks, served another lineup's answer
    (best_open_source c8/c27/c56, beat_runner_up c2/c27).
- **Follow-ups (not filed):** the DRACO metadata count above; a gateway "refresh" cache
  control so a live redraw's good reply replaces the garbled one in the cache (spec §6);
  OME-1642's FrontierScience gap checked against its own raw data.
- **Dev seed fixed (ops data, outside the repo), applied 2026-10-18 00:09Z** through the admin
  snapshot API (merge, with manifest): (1) 6,372 priced judge rows for answers containing "$$",
  copied from the dev rows of the same judge calls under the keys the local Task's requests hash
  to; (2) 56 answer rows that the 2026-09-18 archive-pricing merge had reverted to v2 bodies
  (where the reference recorded an empty answer) restored to v3, with their pricing. Read-back:
  6,428/6,428 rows byte-identical. A keyless replay of the full dev table with both loads scored
  every lineup 100/100 Cases (bar the reference's own 7 error rows); all 9 solos and 5 ensembles
  equal the published score. Remaining gaps are items (b) and (c) above. The working files were
  deleted afterwards.
- **PR review round (2026-10-18):** tests added for the open gaps: the provider puts the origin on
  `ModelOutput.metadata` and on `JudgeReplyBlank`, one watch per call (`test_judge_provider.py`);
  a 429 retry under R3 and an unknown origin (R4) (`test_judge_redraw.py`); a 5xx retry and the
  redraws share one budget. The budget give-up message now names the redraws spent, not
  `MAX_JUDGE_REDRAWS`. The AIDEV-NOTE claim in `fresh_judge_retry.py` is now pinned:
  `test_no_production_route_raises_a_retryable_judge_reply_invalid` fails on a new retryable
  `judge_reply_invalid` raise site. The DRACO `judge_redraws` count and the four Task docstrings
  stay as they are (owner, 2026-10-18: no published revision moves).
