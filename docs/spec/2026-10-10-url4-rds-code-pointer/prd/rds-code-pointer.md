# PRD: code-pointer intents run as RDS calls

**Sources:** URL4 Spec A §1.1, §1.4; Spec B §3, §5.2, §5.3, §6, §8; Spec C §11.6, §12,
§13 · the goal in [00-overview.md §1](../00-overview.md#1-goal) · the formal model in
[`formal/`](../formal/README.md).
**Priority:** P1 (blocks the E4a deterministic combine and the IFEval RDS endpoints).
**Lifecycle:** existing (characterize, then change).

Abbreviations: `G` = `packages/url4/src/url4/`, `T` = `packages/url4/tests/`.
Rule numbers R1–R5 are in the overview §2; contract numbers C1–C10 are in
[contracts.md](../contracts.md).

## 1. User stories

- As an **expression author**, I write `(sources)!/code?params` and the node runs that
  code once, with my sources by position and name, and with no model in the path.
- As a **node owner**, I register code with `@node.code(path)` and get a typed
  `CodeCall`. Code is never reachable as a plain HTTP endpoint, and a data route is never
  run as code.
- As a **caller**, I get permanent, spec-registry error codes when code cannot run, so
  I never retry them.

## 2. Current behavior (url4 1.5.1; probes from 2026-10-09)

| Expression | 1.5.1 result | Problem |
|---|---|---|
| `(m1:/a($input)!'P', m2:/b($input)!'P')!/ensemble/combine/v1?reducer=vote` (endpoint at the path) | `missing_intent` (probe, 2026-10-10: the intent is fetched with no `q=`, and the endpoint branch refuses it); with nothing at the path, `endpoint_not_found` | the intent is fetched as instruction text |
| same, `…&extract=last_number@1` | `malformed_source` | the query is checked as `param-value`, which has no `@` |
| same members, intent `/instr` (data route) | the default model gets `m1:\n…\n[Instruction]\nINSTRUCTION TEXT` | URI intent becomes a prompt (B §6 says code pointer) |
| `m2:0.0:/b(…)` in that group | `m2` is missing from the reducer input | weight filters delivery |
| `(x='hello', y='world')!/instr` | `process` hook gets `INSTRUCTION TEXT\n\nx: hello\ny: world` | URI intent becomes a prompt |
| `(/rows*()!'R $item')!/reduce` | `process` hook gets `/reduce\n\n["R r1","R r2"]` | the path itself is the prompt |
| `((x='hi')!'S')!/w?q=($1)!'Write'` | data read of `/w` with literal `$1` | a relative **expression** intent is classified as a data URI (`intent_atom`, `G/core/grammar.py:675`) |
| `(x)!https://a/score.py` | fetched, used as instruction text | none in 2.0: the owner keeps this meaning for every absolute URI (Q1, D2) |
| `(x)!/claude?t=90&q=(y)!'go'` | `RelUrl`, a data read | a canonical relative expression with protocol params is classified as a data URI |
| `/p(ctx)!/code` as a source | the caller fetches `/code` and sends its text to `/p` | a forwarded intent is resolved by the caller (C §11.6.2 rule 3) |

`intent_atom` decides by prefix: `'` → `Text`, `scheme://` → `Url`, `/` → `RelUrl`; only
other heads get full value detection. `_reduce_graph` (`G/dag/_wiring.py:157`) then
picks fan-out, broadcast or base merge, and each one fetches the intent as text.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**H1 — one call, no model** (R2, R3, R4)
- Given a node with endpoints `/a`, `/b`, a code mount `/ensemble/combine/v1` and no
  processor route
- When it runs `(member_1:/a($input)!'P', member_2:/b($input)!'P')!/ensemble/combine/v1?reducer=vote`
- Then `/a` and `/b` run, the code runs exactly once, and the run result is the code's
  return value.
- And `call.inputs == (CodeInput(1,"member_1","A says 4",None), CodeInput(2,"member_2","B says 5",None))`
  and `call.params == {"reducer": "vote"}`.
- And no request goes to a processor route, and the `process` hook is not called.

**H2 — byte-exact values** (R3)
- Given sources whose values hold newlines, quotes, `%`, `&`, `(`, `\`, non-ASCII text
  and JSON text
- Then each `CodeInput.value` equals the resolved string exactly, and it is a `str`.

**H3 — weight 0.0 is delivered** (R3; Lean `payload_bind_reweigh`)
- Given `(member_1:/a(…)!'P', pattern:0.0:'ANSWER: \\d+')!/combine`
- Then `call.input("pattern").value == "ANSWER: \\d+"` and its `weight == 0.0`.

**H4 — `@` and `+` in params** (C7)
- Given `!/combine?reducer=vote&extract=last_number@1&sep=a+b&dry`
- Then `call.params == {"reducer": "vote", "extract": "last_number@1", "sep": "a+b", "dry": ""}`.

**H5 — every group shape makes one call** (R2, C5)
- Given members that are calls plus a quoted weight-0.0 source (1.5.1 would take the
  base merge, not the fan-out)
- Then the code runs once with all sources.

**H6 — quoted intent is unchanged** (R1)
- `(m1:/a(…)!'P', m2:/b(…)!'P')!'Pick best'` → the 1.5.1 fan-out reduce, unchanged.

**H7 — a relative-expression intent is computed** (R1, C1)
- Given `((x='hi')!'S')!/w?q=($1)!'Write'`, with `/w` an endpoint
- Then `/w` is called as a relative expression with the substituted `$1`, and its answer
  is the prompt of the outer group. It is not a data read.
- The same holds for `/w?t=90&q=($1)!'Write'` (protocol params before `q=`).

**H8 — positional access** (R3)
- Given `(member_1:/a(…)!'P', 'free text', /doc)!/combine`
- Then the positions are 1, 2, 3; names are `member_1`, `None`, `None`;
  `call.input("$2").value == "free text"`.

### 3.2 Error paths

**E1 — unmounted pointer fails before any source** (R4; Lean `evalGroup_unmounted`)
- Given `(m1:/a(…)!'P')!/nope`, with no code mount at `/nope`
- Then the run fails with `intent_error` (permanent), and `/a` is never called.
- Given the same group as an `;optional` source of an outer group with `;quorum=1` and
  another good source
- Then the outer group succeeds without it.

**E2 — an endpoint or data route is not code** (C2)
- Given `/instr` is a data route, or `/m` is an endpoint, and no code mount
- Then `!/instr` and `!/m` fail with `intent_error`.

**E3 — the code fails** (C8; C §13.6)
- A handler `ValueError`, a handler `Url4Error(code, permanent=False)`, and a non-`str`
  return all give `intent_error`, permanent. For the `Url4Error`, its code is in the
  error detail.
- The sources that resolved stay resolved.

**E4 — required source fails** (R2; Lean `gate_eq_false_of_required_failed`)
- A required source fails → the group fails with that source's error; no call, even with
  `;quorum=1`.

**E5 — quorum not met** (R2)
- Two `;optional` members fail, `;quorum=1` → `quorum_not_met`; no call.

**E6 — absolute URIs are prompt sources, never code** (R1; Q1, D2; Lean
`v1_act_eq_invokeLocal_iff`)
- `!https://a/instr`, `!url4://n/instr` → fetched; the content is the prompt, exactly as
  in 1.5.1. No code mount is consulted, even when one exists at the same path.
- No absolute URI intent ever runs code.

**E7 — no code port** (C2)
- `run(expr, HttpIOLayer(...))` with a relative code-pointer intent → the group fails
  with `unsupported_mode` (501) and none of its sources starts.
- Inside an `;optional` source of an outer group with `;quorum=1` and another good
  source, the outer group succeeds.

**E8 — bad query** (C7)
- `!/p?x=1,2` (top level) → `malformed_source`: `,` is not in `query-tail`. The parser
  accepts it as a `RelUrl` today (probe, 2026-10-10), so the reader must refuse it. In a
  nested group, the `,` already ends the intent as a source separator.
- `!/p?x=%40` → `malformed_source` (`%` is not in `query-tail`; no second decode).
- `!/p?a=1&a=2` → `malformed_source` (Q8).

**E9 — protocol params keep `param-value`**
- `GET /v1?tone=a@b&q=(x='1')!'go'` is still refused with `malformed_source`.

**E10 — strict field paths in RDS** (C6; B §5.3.4.1)
- `records*(answer=$item.missing)!/score` → `malformed_source`.
- `records*()!'Q: $item.missing'` → the prompt gets an empty value, as today.

### 3.3 Derived scenarios

**D1 — a failed optional source is absent** (Lean `find?_pos_bind`)
- `(m1:/a(…)!'P';optional, m2:/b(…)!'P')!/combine;quorum=1`, `/a` fails
  → `call.inputs == (CodeInput(2,"m2",…),)`. Position 2 stays 2.

**D2 — weight 0.0 stays instrumental in LLM mode**
- `(q:0.0:/hidden, 'lit')!'REDUCE $q'` → unchanged 1.5.1 behavior (A1 is a separate issue).

**D3 — collections arrive as lists** (C3)
- An iteration source, a broadcast-group source and a `$ref` to a collection → `list`.
- A fetched body `["a","b"]` with no `;expand` → `str`.

**D4 — struct** (C3)
- `(cfg={k: 'v', n: 3})!/combine` → `value == {"k": "v", "n": 3}`.

**D5 — expansion** (C3; Lean `resolvedCount_expandWith_expand`)
- `(*rows:0.6:/rows, 'x')!/combine`, `/rows` gives 3 elements → inputs at positions 1–3
  named `rows[0]`…`rows[2]` with weight `0.2` each, and position 4 = `'x'`.
- Two unnamed expansions → both give `src[0]`; `call.input("src[0]")` raises
  `ValueError`; `call.input(1)` works (Q4).

**D6 — broadcast** (Lean `length_calls_broadcast`, `head?_inputs_of_mem_calls_broadcast`)
- `(a='1', b:/fails(x)!'P';optional, c='3')!*/score`, `/fails` fails → `/score` runs
  twice: `inputs == (CodeInput(1,"a","1",None),)` then `(CodeInput(3,"c","3",None),)`.
  The result is the B §6.1.4 array for positions 1 and 3.
- `(cfg='k', a='1', c='3')!*/score/$cfg` → three calls; the calls for `a` and `c` get
  `(current, cfg)`; the call for `cfg` gets `(cfg,)`.

**D7 — iteration** (C5)
- `rows*(answer=$item.a)!/score` → one call per element.
- `(/rows*()!'R $item')!/reduce` (`/reduce` mounted) → one call; `inputs[0].value == ["R r1","R r2"]`.
- `(https://rows*()!'R $item')!/reduce()!'agg'` → unchanged (A4).

**D8 — vacuous quorum** (Lean `gate_all_of_all_optional`)
- Two `;optional` members both fail, default `quorum=all` → the code runs with `inputs=()`.

**D9 — majority** (C4)
- 5 sources, 3 resolve, `;quorum=majority` → runs; 2 resolve → `quorum_not_met`.
  url4 refuses `quorum=majority` today (probe, 2026-10-10).

**D10 — `processor=` does not touch RDS**
- `processor=unknown-id` and an RDS group → success; a run that mixes an RDS group and
  an LLM group uses the processor only for the LLM group.

**D11 — the eval path** (R5)
- `GET /v1?q=(a='1', b='2')!/combine` → the node runs its own `/combine` once. No
  dispatch change is needed.

**D12 — a forwarded code-pointer intent is verbatim** (C9)
- `/p(ctx)!/code` as a source → the request to `/p` carries `q=(ctx)!/code`; the caller
  does not fetch `/code`.
- `url4://n/v1(ctx)!/code` → the request to `n` carries `q=(ctx)!/code`.
- `/p(ctx)!'Answer'` → unchanged wire (A5).

**D13 — `$` in the pointer** (C1, C6)
- `(v='2', m:/a(…)!'P')!/score/v$v` → pointer `/score/v2`; checked at call time.
- `(m:/a(…)!'P')!/score/$missing` → `unbound_reference`.
- `(cfg={k: 'v'}, m:/a(…)!'P')!/score/$cfg.missing` → `malformed_source` (strict field
  path, B §5.3.4.1).

**D14 — not applicable.** Retry: the call is not a source, so `;retry=` does not apply.
Cancel: the run's cancellation cancels the call's task. Concurrency: one call per group
(per source under broadcast), so there is no new race.

## 4. Non-functional requirements

- **Cost.** An RDS group makes zero model calls. An unmounted pointer costs zero source
  resolutions (R4).
- **Security.** Code runs only from the node's own code table. No URI content is ever
  executed or used as instructions. Endpoints and data routes are never code.
- **Size.** No size limit: the call is in-process (no request line).
- **Observability.** `NodeStarted.node_kind == "CodeCallNode"`.
- **Compatibility.** Engine, SDK and Studio suites stay green with no test edits.

## 5. Out of scope

Absolute URIs as code (Q1, Q2), computed intents that
resolve to code (Q3), content-type checks (Q7), envelope and capabilities fields,
the adjacent deviations A1–A4, any change to what the parser accepts. (The renderer gains
the `NamedJob` form, P3.)

## 6. TDD plan

RED first (an assertion fails, not an import). One behavior per test. **CHAR** rows pin
1.5.1 and pass today. A CHAR row marked *flips* changes in the same commit as the
behavior, and the PR body lists it.

### 6.1 Characterization

| # | Test | Today | After |
|---|---|---|---|
| CH1 | fan-out with quoted intent (`T/spec/test_abnf_contribution.py`) | pass | stays |
| CH2 | weight-0.0 call excluded from the LLM reducer input | pass | stays |
| CH3 | weight-0.0 source instrumental in the LLM base merge | pass | stays |
| CH4 | nested local-expression intent is executed (`T/spec/test_intent_as_value.py`) | pass | stays |
| CH5 | URI intents parse and round-trip (`T/spec/test_intent_as_value.py`, `T/unit/test_render.py`) | pass | stays |
| CH6 | relative-expression iteration reducer `/reduce()!'agg'` (`T/spec/test_iteration_spec.py`) | pass | stays (A4) |
| CH7 | eval-path protocol param refuses `@` | pass | stays |
| CH8 | `(https://a, https://b)!https://instr` → `INSTR\n\nA\nB` (`T/unit/test_dag.py`) | pass | stays (D2) |
| CH9 | `(https://a)!/doc` lowers to barrier + `RelUrlNode` (`T/unit/test_dag.py`) | pass | **flips** → `FailNode(intent_error)` without a mount, `CodeCallNode` with one |
| CH10 | `!*https://instr` fetched once (`T/unit/test_characterization.py`) | pass | stays (D2) |
| CH11 | the §2 probe table, one test per row (new `T/spec/test_rds_code_pointer.py`, written first) | pass | rows 1–7, 9, 10 flip; row 8 stays (D2) |

### 6.2 Phase P1 — classifier

| # | Test (RED) | Level | Risk |
|---|---|---|---|
| 1 | `classify_intent` gives the C1 form for one case per detection row, including the C1 traps (`/p?t=1&q=(c)!x` among them) | unit | H×H |
| 2 | `intent_mode` equals the B §6 table for every form (mirror of `IntentForm.specMode`) | unit | H×M |
| 3 | relative/remote expression intents lower as computed (H7); `render(build(t)) == t` for every trap | integration | H×M |
| 4 | absolute-URI intents (`https://`, `url4://`, `s3://`) keep fetch-as-prompt and never consult the code table, even with a mount at the same path (E6; CH8, CH10 stay) | unit | H×M |
| 5 | `query-tail` reader: H4 cases, `,` and `%` refused, duplicate refused, flag → `""` (C7, E8) | unit | H×H |
| 6 | protocol params keep `param-value` (E9, CH7) | unit | H×M |

### 6.3 Phase P2 — code mounts and RDS groups

| # | Test (RED) | Level | Risk |
|---|---|---|---|
| 7 | `@node.code` registers; overlap with endpoint/data/eval path raises; a code mount is not an HTTP endpoint (C2) | unit | M×M |
| 8 | `CodeCall.input`: by position, `$N`, name; `KeyError` absent; `ValueError` ambiguous | unit | M×M |
| 9 | binding property test: a seeded random source list (resolved/failed, weights incl. 0.0/None, names) → inputs match `find?_pos_bind`, `length_bind`, `pairwise_pos_bind`, `payload_bind_reweigh` | unit | H×H |
| 10 | gate property test: seeded random lists and quorums → `gate_mono`, `gate_eq_false_of_required_failed`, `gate_all_of_all_optional`; majority formula | unit | H×M |
| 11 | value typing table (C3; D3, D4) | unit | H×M |
| 12 | expansion naming, weight split and renumbering (D5) | unit | M×M |
| 13 | lowering: RDS routes before fan-out/base/broadcast; unmounted → `FailNode` with no source subgraph (flips CH9) | unit | H×H |
| 14 | H1 end to end: one call, no processor route, no `process` hook | integration | H×H |
| 15 | H2 byte-exact corpus (seeded) through a real `Url4Node` | integration | H×H |
| 16 | H3, H5, H8, D1 | integration | H×M |
| 17 | E1 preflight: `/a` never called; optional nesting | integration | H×M |
| 18 | E2, E3, E7 | integration | M×M |
| 19 | E4, E5, D8, D9 | integration | H×M |
| 20 | D6 broadcast, D7 iteration | integration | M×M |
| 21 | C6 strict scopes (E10, D13) | integration | M×M |
| 22 | D10 processor isolation; D11 eval path; D12 verbatim forwarded pointer (relative and remote) | integration | M×M |
| 23 | HTTP statuses: `unsupported_mode` → 501, `intent_error` → 422, unlisted permanent → 422, unlisted transient → 502, body code kept (C8) | unit | M×L |
| 24 | `NodeStarted.node_kind == "CodeCallNode"` | unit | L×M |
| 25 | E2E: the E4a 3-model vote against a stub combine gets the three member texts byte-exact plus the params | e2e | H×M |

### 6.4 Phase P3 — named jobs and quoted forwarded prompts (2.0.0, Q10)

| # | Test | Level |
|---|---|---|
| 26 | a bare-token intent with a code mount named by the token runs it; without one → `intent_error`; multi-word unquoted text stays a prompt (`PROSE`); `render(build("(a)!go")) == "('a')!go"` | integration |
| 27 | ~~P2 emits a `DeprecationWarning`~~ — dropped: no deprecation release (Q10) | — |
| 28 | a forwarded prompt intent travels quoted (`q=(ctx)!'Answer'`, escaped), an endpoint handler receives the unquoted text, an eval-path receiver reads a prompt; a prompt with a newline travels unquoted | integration |
| 29 | `@node.code("score_v1")` registers a name key; `!/score_v1` does not find it and `!score_v1` does not find `/score_v1`; an invalid name raises | unit |
| 30 | C8 default: an unlisted permanent code → 422; `internal_error` and a code-less failure → 500 | unit |
| 31 | C6: a prompt group nested in a code group's sources is lenient; a named-job group is strict | integration |
