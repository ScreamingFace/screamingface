---
ticket: OME-1275
stack: py-screamingface
status: done
started: 2026-09-23
finished: 2026-09-25
---

# OME-1275 — Add a manually-run paid smoke test that runs every imported benchmark with real models

## Intent

Every imported inspect_evals board can be green in mocked/replay tests and still be broken at first real run — the runtime-only wiring class has no test. This unit adds an opt-in "paid" pytest lane: per imported board, one real Fusion evaluation (2 flash-tier members + 1 synthesizer, all from the gateway seed list) at 2 cases, through the full product path (SDK → gateway → OpenRouter → engine). Assertions are shape-only (no infrastructure failure codes), never score. Manually invoked (`just` recipe + `workflow_dispatch` workflow); never a merge gate. Owner presses the paid button — the agent never spends.

## Planned changes

- `packages/screamingface/tests/paid/` — new lane: conftest (gating + stack boot with real key), the parametrized per-board smoke test.
- `packages/screamingface/tests/e2e/harness/` — reuse subprocess plumbing (`_local_proc.py`) via imports only; the replay harness's clean-env invariant stays byte-untouched.
- `packages/screamingface/pyproject.toml` — register the `paid` marker beside `e2e`.
- `justfile` (or the package's just recipes) — `test-paid-inspect` target.
- `.github/workflows/` — `workflow_dispatch`-only workflow running the lane with `OPENROUTER_API_KEY` from secrets.
- `docs/tasks/2026-09-23-paid-inspect-smoke.md` — mirror.

## Test plan

- Skip path (free, runs in CI): without `SCREAMINGFACE_TEST_PAID=1` or `OPENROUTER_API_KEY`, every paid test skips with the exact reason — invariant: spend is opt-in by construction.
- Enumeration (free): the board list comes from the engine registry rows with `origin="inspect_evals"` — invariant: a new import is covered with zero test edits (wholesale lane, no hand list).
- Model pins (free): the three pinned models are present in the gateway seed list — invariant: the lane can never 404 on an unseeded model.
- Paid path (owner-run only): per board, run completes; each of the 2 cases carries a grade or a model-side status; no infrastructure failure codes.

## Acceptance

1. `just test-paid-inspect` with key + flag runs every imported board once (Fusion, 2 cases); spend < $1.
2. Without flag/key the lane skips loudly; merge gates unaffected.
3. `workflow_dispatch` workflow runs the same lane on demand.
4. A broken runtime route fails with the board name + infrastructure failure code visible.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `packages/screamingface/tests/paid/{_panel,conftest,test_imported_board_smoke,test_panel_models}.py` (new lane), `packages/screamingface/pyproject.toml` (`paid` marker), `packages/screamingface/pyrightconfig.json` (tests/paid execution env resolving the e2e harness import), `packages/screamingface/justfile` (`test-paid-inspect`), `.github/workflows/screamingface-paid-inspect-smoke.yml` (workflow_dispatch only), plus this ledger + the `docs/tasks/` mirror.
- **Commits:** on branch `OME-1275-paid-inspect-smoke` (shas in the Linear close comment; docs flip to done as the last pre-merge commit).
- **Gates:** run_gates.py screamingface — ALL GATES GREEN (append-only ✓, ruff ✓, format ✓, pyright ✓, pytest cov≥95 ✓, notebooks ✓, build ✓, distribution ✓).
- **Deviations:** (1) 17 imported boards, not the ~13 estimated at design time — cost still well under $1. (2) The paid path itself cannot be self-verified by an agent (spend is the owner's); agent-side proof is the loud skip on both gate branches (flag missing, key missing — both exercised), the free seed-pin test, and pyright typechecking the smoke against the real SDK surface. (3) The panel synthesizer/second member differ from the example notebook's (those models are not gateway seeds); pinned to seeded flash-tier models instead, guarded by `test_panel_models.py`.

## Review round (PR #1035, 2026-09-24)

Action-required (both fixed): (1) the paid button could go green having proven nothing — a pytest skip exits 0; added `SCREAMINGFACE_PAID_REQUIRED=1` (set only by the just recipe + workflow) turning every gate skip into `pytest.fail`, pinned by 5 free tests in `tests/paid/test_gating.py`; (2) `done < <(--list-bundles)` didn't trip `set -e` on a failed listing — both prepare loops now write the bundle list to a temp file first. Nonblocking (both taken): a board can no longer pass with 0 graded Cases (strict fail, rationale anchored — genuine double refusals are a cents-level rerun); `_smoke_one_board` also catches non-SDK exceptions as that board's verdict so the loop's "one broken board never hides the rest" promise holds. Minor: workflow timeout 60→90; bundle ids from `--list-bundles` refused if path-like before `rm -rf`; the prepare-loop fold note now points at a preparer `--only-missing` flag as the real home.

## Rebase + review round 2 (2026-09-25)

Rebased onto main `1f1218ee` (50 commits; zero conflicts). Main added six LAB-Bench boards and frontierscience, so the live-catalog enumeration now covers 24 boards with no code change — exactly the wholesale-lane property. From the review: hard-coded "17" counts removed from every file this PR owns (the pre-existing count in the `local-stack-notebooks` recipe comment is left alone — not this PR's line); the cost wording now names the frontier-model judge of LLM-judged boards (frontierscience → gpt-5.4) instead of "flash-tier only, under $1"; the smoke's tolerance comment records why judged boards stay strict (a rate-limited judge surfaces as `scorer_error`, indistinguishable from a broken judge route). Workflow: timeout 90→120 and the asset cache split into restore + save-right-after-prepare, because the all-in-one cache action saves only on a successful job — a failing smoke would have discarded every fresh download. Verified: the engine preparer uses no HF token and no gated dataset is baked, so the workflow needs none. #1060 (failures re-attributed to the candidate stage) needs no change — the smoke filters on code, not stage. Gates: ALL GREEN, exit code read before commit.

## Close (2026-09-25)

Merged via PR #1035 (squash). Agent-side acceptance met: 2 (loud skip, free gating tests) and 4 (per-board failure verdict with the code visible). Acceptance 1 and 3 are the paid path and the owner's to run: the workflow's "Run workflow" button exists only once the file is on `main`, and it needs the `OPENROUTER_API_KEY` repo secret, which was not configured at merge time. The first press is recorded as the owner-verify item in the Linear close comment.
