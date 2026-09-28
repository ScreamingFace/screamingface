---
ticket: OME-1231
stack: screamingface
status: done
started: 2026-09-18
finished: 2026-09-19
---

# OME-1231 — Refuse a seeded run before spend when a model's provider cannot take the seed

## Intent

A seeded fusion containing `openrouter/anthropic/claude-haiku-4.5` collapses mid-run with
`provider_error` — score `null`, coverage `0.0`, nothing graded — *after* the members that did
work were billed ($0.00169 measured). The catalogue already knows the answer: that model's
`seed` carries `provider_support: "unsupported"` from `openrouter:models`.

The parameter preflight that should catch this already exists and already covers both the
ambient run seed and a Candidate's declared `params`
(`_evaluation/model_parameters.py`, called from `_evaluation/runner.py:84` / `:141`). It reads
the wrong axis. The gateway states the distinction itself
(`aigateway/core/chat_parameters/_types.py:235`): **`gateway_status` carries POLICY,
`provider_support` carries EVIDENCE, and the two are not the same claim.**
`ModelParameter.enabled` is literally `gateway_status == "enabled"` (`discovery.py:139`), so the
preflight consults the gateway's policy and never the provider's evidence sitting one attribute
away on the same object.

Evidence is the only per-model signal available here: the OpenRouter plugin rules `seed` as a
blanket passthrough for every one of its models
(`plugins/openrouter_provider/parameters.py:210`), so `gateway_status` is `enabled` even for
`claude-haiku-4.5`, and `_algebra.py:161` **deliberately** keeps discovered evidence off
`gateway_status`. This unit makes the preflight read that evidence and refuse before any spend.

## Decisions (owner, 2026-09-18 — see the Linear verification comment)

1. **Refuse pre-spend, SDK-only.** Not the ticket's original drop-and-continue: per-model seed
   suppression would need new wire granularity (`X-Answer-Seed` is one run-level header,
   `_engine/transport.py:779`) plus an Engine change, and the Engine holds no
   `provider_support` at all — zero grep hits, and `runner/` is CI-forbidden from importing the
   `catalog` package that proxies the contract. That is a cross-cutting epic; this is one file.
2. **Only `unsupported` acts.** `conditional` and `unknown` pass through silently. `unknown` is
   the default when no discovery source spoke, so refusing on it refuses on our own ignorance
   and blocks models that work today; `conditional` means the provider does support the
   parameter under a condition we cannot evaluate from a catalogue row, and no `conditional`
   seed exists anywhere to test against.
3. **A declared parameter always refuses**, matching today's behaviour for the absent and
   gateway-disabled cases. An explicitly typed parameter is a direct instruction; dropping it
   silently would mean the run did something other than what was written.

## Planned changes

- `packages/screamingface/src/screamingface/_evaluation/model_parameters.py` — `_validate_parameter`
  gains the provider-evidence check after the existing gateway-policy checks and before schema
  validation. One enforcement point, so the ambient seed and declared `params` are both covered
  for free. Seed callers get the reproducibility sentence; a declared parameter gets the plain
  refusal.
- `packages/screamingface/tests/test_unsupported_provider_parameter_preflight.py` — **new
  module**, written RED first. New rather than appended to `test_model_parameter_preflight.py`
  because the append-only gate protects prior test artifacts (the precedent is
  `test_engine_cost_breakdown_warning.py:12`).
- `packages/screamingface/CHANGELOG.md` — Bug Fixes entry.
- Ledger + `docs/tasks/` mirror.

The shared fixture `tests/_model_parameter_fixtures.py` carries no `seed` entry and is inside the
append-only glob, so the new module injects `seed` at each support level locally via
`copy.deepcopy` rather than editing it.

## Test plan

Written RED first, against the production path (`sf.Client` / `sf.AsyncClient`, real
`preflight_sync` / `preflight_async`), asserting pre-spend via the existing
`_ForbiddenTransport.called is False` idiom:

- **The measured bug.** A seeded fusion whose synthesiser marks `seed` `unsupported` raises
  `PlanningError` before dispatch; the message names both the model and `seed`; transport never
  called. INVARIANT: the failure is pre-spend, which is the whole point — money was the cost.
- **One bad member is enough.** A supporting member plus an unsupported synthesiser still
  refuses, and names the unsupported one — not the first model it happened to fetch.
- **Unseeded is untouched.** The same fusion with `answer_seed=None` reaches execution.
  INVARIANT: the seed branch is only entered when a seed is declared, which is what keeps every
  request-keyed cache identity and the byte-identical-egress tests valid.
- **The declared door.** `params={"seed": 42}` on an unsupported model refuses even with no
  ambient seed, via the same enforcement point.
- **The stated policy.** `conditional` and `unknown` both pass through to execution, seeded.
  INVARIANT: only explicit provider denial acts — refusing on absent evidence would block
  working models.
- **`supported` passes**, seeded — the control.
- **Generality.** A non-seed parameter (`temperature`) marked `unsupported` refuses too, proving
  the rule is over the field and not special-cased to `seed`.
- **Async twin** shares the same gate.

## Acceptance

- A seeded run containing a model whose `seed` is `provider_support: "unsupported"` raises
  `PlanningError` before any candidate dispatch, naming the model and the parameter and saying
  the run cannot be reproducible.
- The same fusion unseeded behaves exactly as today.
- Declared `params={"seed": …}` refuses the same way.
- `supported` / `conditional` / `unknown` pass unchanged; egress byte-identical.
- `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, no ripple —
  `src/screamingface/_evaluation/model_parameters.py` (the `_PROVIDER_DENIED` / `_SEED_PARAM`
  constants carrying the stated policy, stage 3 inside `_validate_parameter`, the two message
  helpers, and a Feynman docstring on `_validate_parameter`, which had none),
  `tests/test_unsupported_provider_parameter_preflight.py` (new, RED first), `CHANGELOG.md`,
  ledger + mirror. No other source file touched; no Engine change; no wire change.
- **Commits:** three on `OME-1231-parameter-preflight`, merged as `ce147387` (PR #989) —
  `781ac803` the gate, `d731beaa` the review round, `4461fc77` the notebook-door test.
- **Gates:** `run_gates.py screamingface` **ALL GATES GREEN** — append-only, ruff check, ruff
  format, pyright, pytest with `--cov-fail-under=95`, notebook determinism, `uv build`,
  distribution check. Full suite 1631 passed / 25 skipped. RED→GREEN confirmed: the 6 refusal
  tests failed on `_ForbiddenTransport` being reached before the fix, all 10 pass after.
- **Deviations:**
  - **Direction changed from the ticket's Architecture / Design.** Refuse pre-spend, SDK-only,
    rather than drop-and-continue. The ticket's premise — that no model-parameter preflight
    exists — is false; one exists and already covers both paths. Owner-approved after the
    trade-off was re-put with the cost of the drop route measured. Full reasoning is in the
    verification comment on the issue; drop-and-continue stays open as a possible cross-cutting
    epic.
  - **No append-only waiver needed**, unlike OME-1193 and OME-1227. The change is entirely
    inside a private module (`_evaluation/model_parameters.py`, `__all__ = []`) and adds no
    public signature, so `public_surface_snapshot.json` does not move and no prior test artifact
    was modified. The new tests went into a NEW module for the same reason.
  - **The reproducibility clause is keyed on the parameter NAME**, not on which door the value
    arrived through. A declared `params={"seed": …}` and the ambient run seed are the same wire
    field, so a denial costs reproducibility either way and deserves the same sentence. The
    *rule* stays general over `provider_support`; only the *copy* knows about `seed`, and a test
    pins that a non-seed denial gets no seed wording.
- **Review round (2026-09-19):** four findings, all verified by running the code rather than
  reading it — two fixed, one relocated, two pushed back.
  - **Gate ORDER was the change's load-bearing claim and nothing pinned it.** Measured: moving
    stage 3 below stage 4, or above stage 2, left all 21 preflight tests green while changing
    what the user is told. On a row that is denied AND carries an invalid value, the reordering
    reports `invalid_model_parameter` "expected integer" instead of the denial — so the reader
    corrects the value, reruns, and hits the same wall. Above stage 2, a gateway-disabled row
    loses the message naming which credential would open it. Two tests now pin each position,
    each verified to fail under its matching mutation.
  - **`sf.evaluate` — the notebook door — was never exercised.** Every test drove
    `Client.evaluate`; the wrapper's forwarding was pinned separately with a stub client. Two
    pinned links, unpinned join, and that join is exactly what came apart in OME-1227. Added a
    test through the real `default_client` seam; verified as a pin by mutating the wrapper's two
    forwarding sites to `None` (the OME-1227 bug reproduced — that test alone fails).
  - **Stale evidence** now rides the `hint`, not `details`: a stale `unsupported` can refuse a
    run that works today, and from the message alone the only visible fix is swapping a Model
    that may be fine. Placed in the hint because it is advice about what to do next, not a fact
    about the parameter — and, usefully, that choice kept the append-only gate green.
  - **Pushed back on two.** The async-test style nit copies `test_model_parameter_preflight.py`'s
    existing idiom verbatim. The proposed `_SEED_PARAM` ↔ Engine `ANSWER_SEED_PARAM` conformance
    assertion rests on a false premise: the wire name is the GATEWAY contract's key, and both
    sides bind to it independently, so there is no drift channel between the two constants. The
    docstring did misname the source of truth, and was corrected.
  - **No append-only waiver was needed at any point.** The first attempt tripped the gate (10
    changed lines); making the fixture change additive and moving staleness to the hint brought
    it to 134 insertions / 0 deletions. The last complaint was a heuristic false positive on new
    helpers sitting between two old ones, resolved by appending them at the end of the module.
- **Owner-verify:** against a live stack, `sf.evaluate(fusion, benchmark="inspect-gsm8k",
  limit=2, answer_seed=42)` where the synthesiser is `openrouter/anthropic/claude-haiku-4.5`
  should now raise `PlanningError` immediately with **no cost recorded**, naming the model and
  `seed`. The same fusion without `answer_seed` should still score 2/2 as it did at $0.00443.
