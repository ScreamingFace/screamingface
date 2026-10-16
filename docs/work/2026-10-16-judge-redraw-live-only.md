---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
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
- **Commits:** see `git log` on branch `judge-redraw-live-only`.
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
  - V5 (full draco-3pass replay on the local stack) not run yet.
- **Follow-ups (not filed):** the DRACO metadata count above; a gateway "refresh" cache
  control so a live redraw's good reply replaces the garbled one in the cache (spec §6);
  OME-1642's FrontierScience gap checked against its own raw data.
