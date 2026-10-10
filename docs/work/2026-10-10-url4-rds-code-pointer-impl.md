---
ticket: unfiled   # filed at PR-open under OME-500 after the user confirms (one PR for the branch)
stack: url4
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-10
finished:
---

# url4-rds-code-pointer-impl — run relative code-pointer intents as RDS calls (P1 + P2)

## Intent

Implement phases P1 (intent classifier) and P2 (code mounts and RDS groups) of the
reshaped spec `docs/spec/2026-10-10-url4-rds-code-pointer/` on branch
`url4-audit-fixes`. A URL4 author writes a relative code pointer as the intent
(`(m1:…, m2:…)!/ensemble/combine/v1?reducer=vote`), and the node runs code registered
with `@node.code` once, after the gate, with the sources bound by position and name. No
model runs. This unblocks the E4a deterministic combine and the IFEval RDS endpoints.
P3 (bare-token named jobs) is out of scope (3.0.0).

## Planned changes

Units, in order (one commit each, TDD per the PRD §6 rows):

1. **CHAR** — `tests/spec/test_rds_code_pointer.py`: CH11, the PRD §2 probe table on
   today's code (green before any delta).
2. **P1 classifier** (rows 1–4) — `src/url4/core/intent.py` (new: `IntentForm`,
   `IntentMode`, `classify_intent`, `intent_mode`); `core/grammar.py` (`intent_atom`
   uses the classifier); `core/render.py` (lockstep); `tests/unit/test_intent_classify.py`.
3. **P1 query-tail** (rows 5–6) — `core/_annotations.py` (`parse_query_tail`);
   cases appended to `tests/spec/test_param_conformance.py`.
4. **P2 types + mounts** (rows 7–8) — `core/code.py` (new: `CodeCall`, `CodeInput`,
   `CodeHandler`, `CodeValue`); `core/errors.py` (`INTENT_ERROR`, `UNSUPPORTED_MODE`);
   `io/layer.py` (`SupportsCode`, `StaticIOLayer(code=…)`); `peer/server.py`
   (`Url4Node.code`, in-process adapter); `url4/__init__.py` re-exports.
5. **P2 binding + gate** (rows 9–12) — binding/gate helpers; `quorum=majority`;
   `tests/unit/test_code_binding.py` (property tests against the Lean definitions).
6. **P2 lowering** (rows 13–22, 24) — `dag/_wiring.py`, `dag/nodes/code.py` (new
   `CodeCallNode`), `dag/_lowering.py` (C9 verbatim forwarded pointer), strict scopes (C6);
   CH9 flips.
7. **P2 statuses** (row 23) — `peer/_http.py` (`status_for_code` class defaults).
8. **E2E + docs** (row 25) — E4a vote e2e; `README.md` "Migrating to 2.0";
   `ARCHITECTURE.md` rows.

## Test plan

PRD §6 rows 1–25 and CH1–CH11; the test-plan §2 theorem → test map. RED first; CHAR
first; CH9 and the CH11 rows marked *flips* change in the commit that changes the
behavior (each listed in the PR body).

## Acceptance

- `uv run .claude/scripts/run_gates.py url4` green (ruff, format, pyright, pytest ≥95%
  coverage), plus the module-size, suppression, layering and parity ratchets.
- Engine and SDK suites green with no test edits.
- `cd docs/spec/2026-10-10-url4-rds-code-pointer/formal && lake build` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
