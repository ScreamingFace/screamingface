---
ticket: OME-1496
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-06
finished: 2026-10-06
---

# paid-smoke-qwen-reasoning-low — cap qwen's reasoning in the paid smoke panel

## Intent

The paid Inspect smoke on main failed on 2026-10-06 (GH run 37442602029, head dfbe0b7a1):
`inspect-lab_bench_cloning_scenarios` graded 0/2 with `model_token_cap` x2. Member
`openrouter/qwen/qwen3.7-flash` spent all of `max_tokens=32768` on reasoning (65536 reasoning
tokens over two Cases) and returned no text, so each Fusion Case died. Trigger: #1254
(75524d974, Task replay) changed inspect's shuffle, so `slice=0:2` now picks two longer DNA
Cases (passed 2/2 at ~15k output tokens on 10-02). Owner decision: send
`reasoning_effort="low"` on the qwen member ONLY; haiku and the gemini synthesizer keep their
params, so only qwen's cache keys churn. `max_tokens` stays 32768.

## Planned changes

- `packages/screamingface/tests/paid/_panel.py` — per-member params: qwen gets
  `{**PANEL_PARAMS, "reasoning_effort": "low"}`; WHY comment with the run id.
- `packages/screamingface/tests/paid/test_panel_models.py` — append pin tests.

## Test plan

- Pin: `fusion_panel()` qwen member params == max_tokens 32768, temperature 0.0,
  reasoning_effort "low"; haiku member and synthesizer params == PANEL_PARAMS exactly.
- Forwarding: `compile_candidate(fusion_panel())` keeps `reasoning_effort="low"` in qwen's
  parameter assignment and its URL4 call, and no other model's.
- Engine side checked by reading: `model_params` coerces via json.loads → "low" stays a
  string; no allowlist strips it. Gateway: OpenRouter `reasoning_effort` direct rule (OME-993),
  catalog vocabulary lacks the name so local evidence (supported) serves preflight.

## Acceptance

- Pin + forwarding tests green; `run_gates.py screamingface` green.
- One paid dispatch on the branch (owner) grades cloning_scenarios.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1496.json` (blob-pinned
  approval for the one changed line in `_panel.py`) and the mirror
  `docs/tasks/2026-10-06-OME-1496-paid-smoke-qwen-reasoning-low.md`.
- **Commits:** `fix(screamingface): cap the paid smoke qwen member's reasoning at low` (sha in PR).
- **Gates:** `run_gates.py screamingface --base origin/main` ALL GATES GREEN (append-only via the
  OME-1496 approval; pytest 2239 passed / 26 skipped, coverage 96.17%). The paid-lane pin file
  runs only with SCREAMINGFACE_TEST_PAID=1 (deselected in merge CI); run locally with that flag
  and no key: 3 passed, $0.
- **Deviations:** (1) `_panel.py` sits under `tests/**`, so the append-only check flagged the
  owner-directed edit of `fusion_panel()`'s members line; recorded as a blob-pinned approval
  manifest rather than skipping the check. (2) The new pin tests live in the fenced paid lane
  beside the existing free seed pin, so merge CI does not run them; every paid press does.
  (3) Paid run 37453343696 on this branch (effort=low only): 57/57 boards ok, 111/114 Cases
  graded, $0.7042, but lab_bench_cloning_scenarios graded only 1/2 (`model_token_cap` x1,
  57.8k reasoning tokens over the pair) — "low" barely bounded qwen. (4) Owner then added
  max_tokens=65536 for qwen only (its OpenRouter max_completion_tokens); re-verification by
  one more paid dispatch on this branch.
