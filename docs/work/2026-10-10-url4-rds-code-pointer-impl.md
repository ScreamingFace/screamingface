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

## Unit 2 — everything else in 2.0.0 (owner decision Q10, 2026-10-10)

The owner moved the rest of the spec into 2.0.0: P3 named jobs, the A5 wire fix, the C8
status default and exact C6 strictness. Planned commits, in order:

1. C8 default: unlisted permanent → 422; `internal_error` and code-less failures stay 500
   (flips `test_status_mapping.py` ×2 and `test_direct_dispatch.py` ×1). Row 30.
2. C6 nearest-group strictness: a prompt group nested in a code group's sources is
   lenient again. Row 31.
3. A5: forwarded prompt intents travel as `quoted-text`; `decode_subrequest` unquotes
   them for endpoint handlers. Row 28. Flips tests that pin the unquoted wire.
4. P3: `NamedJob` AST node, `intent_atom`, `render`, `IntentForm.PROSE`, lowering,
   name keys in `@node.code` and `StaticIOLayer(code=…)`. Rows 26, 29. Flips every test
   that used a one-word bare intent as a prompt (url4 and Engine, about 390 tests by the
   2026-10-10 probe: url4 224 with call intents counted, Engine 166 on `!go`/`!probe`;
   SDK 0).

## Unit 2 notes

- The 2026-10-10 probe over-counted (it also hit forwarded-call intents). Actual flips:
  url4 112 tests (rule A quote a prompt 82 sites, rule B `Text`→`NamedJob` 28, rule C
  quoted wire 4) plus the decoder pin in `test_server.py`; Engine 18 tests (16 sites,
  rule A only) plus the C8 rows added to `test_mount_routes.py`.
- `x_y://z` (a bad scheme) stays prose, not a named job: a token holding `://` is never
  a named job (contracts C1, "contains `://`").
- `$`, `$x-y`, `$5off` classify as `PROSE` (text with an embedded reference); behavior is
  the same `TextNode` as `VARIABLE_REF`.
- Quoting lives in the wire codec (`quote_prompt`/`unquote_prompt` in
  `wire/subrequest.py`, `encode_subrequest(…, quote=True)`), over `core/quoted.py`.
- Design review (unit 2): 0 high, 4 medium, 11 low. Fixed: M1 (codec owns quoting), M2
  (one `is_named_job`), M3 (corpus keeps named jobs), M4 (this ledger), L5 (`.value`),
  L6, L7, L9–L11, L13, L15. Recorded: L8 (above), L12 (C6 note above), L14 (no effect).

## Notes and deviations (running)

- **Preflight lives in `CodeCallNode.resolve`, not a `FailNode`.** Compilation has no IO
  (`compile_expression` runs before `ctx` exists), so the C5 `FailNode` branch cannot be
  chosen at lowering. `CodeCallNode` holds its sources off-edge (the `GuardNode`
  isolation pattern) and checks the code port and the static mount before it starts
  them. Same observable rule (Lean `evalGroup_unsupported` / `evalGroup_unmounted`):
  no source of a group that cannot run ever starts. CH9 asserts the new shape.
- **`SupportsCode` is in `core/code.py`, not `io/layer.py`** (C10a). `io/layer.py` is
  pinned to the standard library (`test_layering`), and the protocol names `CodeCall`.
  `BoundedIOLayer` forwards it like `processor_routes`.
- **Remote-expression intents stay refused by the parser** (`url4://n/p(c)!x`).
  `classify_intent` names them `EXPRESSION`; the spec keeps parser acceptance out of
  scope (overview §4), so P1 changes only `/…` intents.
- **A computed intent now reads the group's sources** (H7): the base graph wires the
  intent's `$name`/`$N` edges to the group's built sources.
- **Iteration reducers with `(`** (`/reduce()`, `/reduce(all)!'agg'`, malformed ones)
  stay on the 1.5.1 `ReduceNode` path (A4). A plain `/reduce` reducer is a code pointer.
- **Strictness scope (C6):** unit 1 used one context variable for a code group's whole
  source subtree. Unit 2 (5afb5326f) makes it exact: a group node declares `rds_scope`
  (True for a code group, False for a prompt group), and the executor sets `RDS_STRICT`
  before it starts the node's dependencies; each task copies it. A forwarded call has no
  `rds_scope`, so its context substitutes with the strictness of the group around it
  (decision recorded: the call's own intent is resolved by the receiver).
- **Expansion elements:** objects and arrays decode; scalar elements stay `str`
  (the collection parser hands elements over as strings, and JSON-encodes structured
  ones, so a string element `"[1,2]"` also decodes). Reducer rows (`kind="rows"`) stay
  exact strings. An iteration used as a SOURCE arrives as its §5.3.8 serialization
  decoded, so a row that is visibly JSON is decoded there.
- **One `CodeCallNode` for `!*`** (C5 sketches one node per source plus a
  `BroadcastCollectNode`): the calls run inside the one node, so `NodeStarted` fires once.
- **`SupportsCode.invoke_code` returns `object`** (C2 says `str`): the RDS node checks
  the type (C §13.6), so a non-`str` return is `intent_error`, not a type lie.
- **Unbound references fail in RDS scopes** (B §6.3, C8): a reference the scope does not
  bind raises `unbound_reference`, including quoted text in a code group's sources
  (`'costs $5'` needs `$$5`). LLM scopes are unchanged.
- **Value kind (C3) is read from the source's parse form** (`_Slot.form`), so the text
  and AST paths type a value alike; a bare `$name`/`$N` to an earlier sibling inherits
  its kind; a `$ref` with a field path is `text`.
- **`peer/_code.py` mixin**: `server.py` is at its size cap (315/315), so the code table
  lives in a mixin. `has_code`/`invoke_code` share `invoke_mounted` with `StaticIOLayer`.
- **Design review (design-reviewer, 2026-10-10):** 0 high, 5 medium, 9 low. Fixed: M1
  (a handler's transient `intent_error` is made permanent), M2 (kind from form), M3,
  M4 (rows), M5 (one quorum parser; `majority` refused for LLM groups), L1, L2, L6–L9,
  T1–T4. Recorded above: L4, L5.
- **Status table (C8):** explicit rows `intent_error → 422`, `unsupported_mode → 501`.
  The C8 class default (unlisted permanent → 422) is NOT applied: three pinned regression
  tests (`test_status_mapping.py`, `test_direct_dispatch.py`) assert "any other → 500"
  and cite the spec. Owner decision needed.
- **TDD order:** the P1 classifier and parts of P2 were written before their tests
  (probe-driven); CH11 was written and green first.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `core/_call_head.py` (path validators moved out of
  the capped grammar), `dag/_code_wiring.py`, `dag/semantics/code_binding.py`,
  `peer/_code.py`, `tests/unit/test_code_binding.py`, `tests/unit/test_code_mounts.py`,
  `tests/unit/test_code_types.py`. `io/layer.py` is unchanged (see `SupportsCode`).
- **Commits:** 650d9f6b8 (CH11), 1389629ef (types, query-tail, codes), e41abf20c (P1
  classifier), and the P2 commit that carries this ledger.
- **Gates:** url4 ruff, format, pyright, 1871 passed / 17 xfailed, coverage 98.83%,
  module size, suppressions 5/5; Engine 4678 passed + layering OK; SDK green (the 12
  widget failures need the `notebook` extra: 159 passed with it); `lake build` green.
- **Flipped tests:** CH9 (`test_dag.py::test_relative_url_intent_lowers_to_one_code_call`),
  CH11 rows 1–7, 9, 10 (`tests/spec/test_rds_code_pointer.py`). Row 8 stays (D2).
- **Deviations:** see "Notes and deviations" above. Open for the owner: the C8 class
  default (unlisted permanent → 422). P3 (named jobs) is not started.
