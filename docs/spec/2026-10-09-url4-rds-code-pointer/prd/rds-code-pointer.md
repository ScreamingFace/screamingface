# PRD: URI intents run as RDS code-pointer calls

**Source:** prompt (2026-10-09) · ans:Q1–Q5 · the URL4 grammar (ABNF) and URL4 Spec A, B and C
**Priority:** P1 (blocks the E4a nested-url4 unit; breaking change)
**Lifecycle:** existing (characterize + delta)
**Owner:** Ionesio · wire shape confirmed by Kevin McDonough (open items K1–K9 in
[00-overview.md](../00-overview.md#6-open-items-for-kevin-mcdonough))

Abbreviations: `G` = `packages/url4/src/url4/`, `T` = `packages/url4/tests/`. "Group site" = the
place where the url4 engine itself runs the intent of a `(sources)!intent` group: the base merge,
the fan-out reduce, the broadcast merge and the iteration reducer.

## 1. Summary and user story

As the author of a url4 expression, I want a URI intent (`!/path?…`, `!url4://node/path?…`) to call
that code with the group's sources as structured data, so that deterministic code (a combine, a
checker, a gate) runs as Spec B §6 says, and no model sees the inputs.

Today the package reads a URI intent as **instruction text** and gives the sources to the default
processor or to the `process` hook. In 2.0.0 the node calls the code pointer **once** with every
named source, by name, as structured data. A quoted-text intent stays LLM mode. A nested-expression
intent stays computed. The author never declares the mode; the intent form gives it.

## 2. Background and constraints

### 2.1 Sources of truth

- The URL4 grammar (ABNF) is the source of truth. Spec B and Spec C explain it. `[stated prompt]`
- Spec B §6 table: quoted text = "Prompt / natural language intent (LLM/agent mode)"; absolute URI =
  "Code pointer / job reference (RDS mode)"; relative URI = "Code pointer on current node"; nested
  expression = "the intent itself is computed"; bare token = "Named job / command identifier".
  `[stated prompt]`
- Spec B §6.3: variable references "are mechanically required for RDS mode (they form the code's
  input API contract)". `[stated prompt]`
- Spec B §5.3.8: "When consumed by an outer intent in RDS mode, the result is bound to the code
  pointer's input as a JSON array (or equivalent structured format)." `[stated prompt]`
- Spec C §12.5: "Code pointers operate on structured inputs". Spec C §13.2.3: for RDS mode a
  content mismatch "is an intent execution failure (§26.2.4), not a source resolution failure".
  `[stated prompt]`
- Spec C §13.6: an expression fails when a `;required` source fails, when quorum becomes
  impossible, or when intent execution fails (`intent_error`, permanent; sources stay
  `resolved`). `[stated prompt]`
- Part G (§26, code-pointer execution) is not published. This PRD proposes the delivery shape;
  Kevin McDonough confirms it. `[stated prompt]`
- Reference only: Kevin's *IFEval Corrective Ensemble — Endpoint Contracts* (2026-09-17). Its RDS
  intents receive named sources, a weight-`0.0` source is delivered (`spec:0.0:src=$case`), and "A
  member absent from the source list failed to resolve." `[stated prompt]`

### 2.2 User decisions (see the ledger in the overview)

- **U1** A `relative-uri` intent and an absolute URI intent are RDS code pointers. The node calls
  the code pointer once with the group's sources. The old meaning ends for URI intents. Quoted text
  stays LLM mode. A nested expression stays computed (OME-502). Mode comes from the form.
  `[stated ans:Q1]`
- **U2** The code pointer receives every named source by name as structured data, weight-`0.0`
  sources included. Weight is attribution metadata. A failed optional source is absent. We propose
  the wire shape; Kevin confirms it. `[stated ans:Q2]`
- **U3a** A code pointer's `?query-tail` reaches the handler as params by the grammar's
  `query-tail` rule, not by `param-value`. `@` passes. The protocol params of a url4 URI's own query
  string keep `param-value`. `[stated ans:Q3]`
- **U3b** Free-text args are not url4 work. They travel as named quoted sources by the convention
  of the consuming endpoint. `[stated ans:Q3]`
- **U4** Call identity for attribution is deferred. `[stated ans:Q4]`
- **Release** Breaking change: 1.5.1 → 2.0.0, a CHANGELOG entry and a migration note.
  `[stated ans:Q5]`

### 2.3 Current behavior (url4 1.5.1)

Classification:

- `intent_atom` reads the intent by its first characters: a quote gives `Text`, any `scheme://`
  gives `Url`, a leading `/` gives `RelUrl`, and only other heads get full value detection
  `[existing G/core/grammar.py:916-925]`. So a relative *expression* in intent position
  (`/p(c)!x`, `/p?q=(c)!x`) is a `RelUrl`, and a remote expression is a `Url`. `[implied]`
- `RelUrl` lowers to a plain data read `[existing G/dag/_lowering.py:136-141]`; `Url` lowers to an
  absolute fetch `[existing G/dag/_lowering.py:131-133]`.

Group sites:

- **Fan-out gate.** A parenthesised group whose sources are all relative-expression calls, with at
  least one contributing call, becomes a fan-out reduce `[existing G/dag/_wiring.py:174-180]`.
- **Fan-out reduce.** The intent is fetched and used as instruction text
  `[existing G/dag/nodes/group.py:276]`. Weight-`0.0` answers are dropped from the reducer input
  `[existing G/dag/nodes/group.py:280]`. The reducer input goes to `ctx.processor` as
  `processor?q=()!<input>` `[existing G/dag/nodes/group.py:282-298]`. With no processor route the
  group fails `[existing G/dag/nodes/group.py:286-290]`. The Engine sets that route to its default
  model `[existing apps/screamingface-engine/src/screamingface_engine/world/connector.py:464]`.
- **Base merge.** Any other group with a fetch intent waits on a barrier, then calls the
  `process` hook with the packed sources and the fetched text
  `[existing G/dag/_wiring.py:263-268]`, `[existing G/dag/nodes/group.py:152-162]`. The default
  hook joins the intent text and the sources `[existing G/dag/_context.py:42-46]`.
- **Broadcast.** A fetch intent is one shared node, fetched once, merged with each source
  `[existing G/dag/_wiring.py:217-231]`, `[existing G/dag/nodes/group.py:179-190]`.
- **Iteration reducer.** A relative-expression reducer gets the row array as its intent; any other
  reducer goes to the `process` hook with the *raw reducer text*
  `[existing G/dag/nodes/iteration.py:207-215]`. So `(/rows*()!'R $item')!/reduce` passes the
  string `/reduce` as a prompt (probe, 2026-10-09). `[implied]`
- **Packing.** `_gather` packs `name: value` lines and drops weight-`0.0` ("instrumental") sources
  (OME-534) `[existing G/dag/nodes/_shared.py:213-237]`. Quorum counts only the packed sources
  `[existing G/dag/nodes/_shared.py:253-260]`.

Dispatch and params:

- `Request(path, context, intent, params)` is the only handler shape
  `[existing G/peer/_dispatch.py:51-62]`. An endpoint matches by exact path
  `[existing G/peer/_dispatch.py:164]`. A miss on every registry raises `endpoint_not_found`
  `[existing G/peer/_dispatch.py:148-152]`.
- `extract_expression_params` splits the query, decodes values with `unquote_plus`, and checks
  every value with `validate_param` `[existing G/wire/subrequest.py:184-242]`.
  `validate_param` applies `param-value`, which has no `@`
  `[existing G/core/_annotations.py:67]`, `[existing G/core/_annotations.py:131-135]`.
- HTTP and in-process share one dispatch `[existing G/peer/_http.py:69-83]`. The outbound HTTP
  adapter turns every non-2xx answer into a transient `ResolutionError`
  `[existing G/io/http.py:79-84]`.

Probes on 2026-10-09 (`uv run`, url4 1.5.1):

| Expression | 1.5.1 result |
|---|---|
| `(member_1:/a($input)!'P', member_2:/b($input)!'P')!/ensemble/combine/v1?reducer=vote` on a node with an endpoint at `/ensemble/combine/v1` | `ResolutionError endpoint_not_found` "node 't' has no endpoint, eval path, or data route at '/ensemble/combine/v1'" |
| same, query `…&extract=last_number@1` | `ParseError malformed_source` "invalid param value 'last_number@1' for 'extract'" |
| same members, intent `/instr` (a data route) | `/a`, `/b` called; the default route gets `member_1:\nA says 4\n\nmember_2:\nB says 5\n\n[Instruction]\nINSTRUCTION TEXT` |
| `member_2:0.0:/b(…)` in that group | `member_2` missing from the reducer input |
| `(x='hello', y='world')!/instr` | `process` hook: `INSTRUCTION TEXT\n\nx: hello\ny: world` |
| `(/rows*()!'R $item')!/reduce` | `/reduce\n\n["R r1", "R r2"]` (the path is the prompt) |
| `(a,b)!'it\'s \\d+'` / `(a,b)!'it''s'` | parses and round-trips / `ParseError` |

### 2.4 Delta

- **Change.** At every group site, a code-pointer intent (§2.5) produces one call to that code
  pointer with the RDS input document ([contracts.md](../contracts.md) C1). No instruction fetch, no
  reducer input, no `process` hook, no processor route.
- **Change.** The receiving node gives the handler the decoded inputs and the query-tail params
  (U3a).
- **Change.** `https://`, `http://` and other non-url4 schemes in intent position fail with
  `unsupported_mode` (P2).
- **Keep.** Quoted-text intents, bare-token intents, nested local-expression intents, relative- and
  remote-*expression* intents, a call's own intent, and the OME-534 packing in LLM mode.

### 2.5 Intent classification `[proposed]` (P1)

The classifier is one pure function in the core, for example `url4.core.intent_mode(atom) ->
IntentMode`. It reads the parse-tree atom and the ABNF production that the atom's text matches. The
grammar does not change.

| Intent text (ABNF production) | Mode | 2.0 behavior |
|---|---|---|
| `quoted-text` | `llm` | unchanged |
| `bare-value` with no `://` (a bare token, e.g. `summarize`) | `llm` | unchanged (Spec B §6 "named job": open item O3) |
| `variable-ref`, `struct-object`, `self-ref`, `identity-ref` | unchanged | unchanged (OME-502) |
| `local-expr`, `iteration-expr` | `computed` | unchanged (OME-502) |
| `relative-uri` = `"/" path-segment *( "/" path-segment ) [ "?" query-tail ]`, and its text is not a relative expression (Spec B §5.2 rule 2.3) | `rds` | **code-pointer call on the current node** |
| `bare-value` with `url4://` and no expression form (Spec B §5.2 rule 3.3, "Remote URL4 reference") | `rds` | **code-pointer call on the remote node** |
| `bare-value` with any other `scheme://` (Spec B §5.2 rule 5) | `unsupported` | **`unsupported_mode`, permanent** (P2) |
| `relative-expr` / `remote-expr` text (Spec B §5.2 rules 2.1, 2.2, 3.1, 3.2), and `/path(...)` text that is neither form (e.g. `/reduce()`) | `legacy` | unchanged in 2.0 (open item O2) |

Notes:

- The classifier must not use the `RelUrl`/`Url` node type alone, because `intent_atom` also puts
  relative and remote *expressions* in those types (§2.3). `[implied]`
- The parser accepts more than `query-tail` (for example `,` and `%`). The classifier refuses a
  code pointer whose query does not match `query-tail` after percent-decoding, with
  `malformed_source` at compile time (P9). `[proposed]`
- `path-segment` admits `$`. A `$name` in a code-pointer path substitutes against the scope that
  today's intent fetch uses (the outer scope, not the group's sources)
  `[existing G/dag/nodes/fetch.py:112]`. `[proposed]`
- An `expr-params` chain after the URI (`!/p?x=1;quorum=1`) stays an expression param, not part of
  the query-tail. The parser already splits it this way (probe). `[implied]`

### 2.6 Constraints on the solution

- Hexagonal: the core (`url4.core`) owns the classifier and the query-tail rule; the DAG owns the
  new node; the peer owns decode and dispatch; I/O stays behind `ctx.io`. The core imports no
  plugin. `[stated prompt]` (repo CLAUDE.md)
- One owner per rule: the query-tail validator lives beside `validate_param` in
  `G/core/_annotations.py`; the RDS document codec lives in `G/wire/` beside `encode_subrequest`.
  `[implied]` (OME-507 single-owner rule, `[existing G/core/_annotations.py:107-112]`)
- HTTP and in-process must behave the same: both go through `_dispatch.fetch`
  `[existing G/peer/_dispatch.py:79-91]`. `[implied]`

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**H1 — A group calls its relative code pointer once** `[stated ans:Q1]`
- Given a node with endpoints `/a`, `/b` and `/ensemble/combine/v1`, and no processor route
- When it runs `(member_1:/a($input)!'P', member_2:/b($input)!'P')!/ensemble/combine/v1?reducer=vote`
- Then `/a` and `/b` run first, `/ensemble/combine/v1` runs exactly once, and the run result is the
  handler's return value, unchanged.
- And the handler gets `mode == "rds"`, `inputs == {"member_1": "A says 4", "member_2": "B says 5"}`,
  `params == {"reducer": "vote"}` and `intent == ""`.
- And no fetch goes to a processor route, and the `process` hook is not called.

**H2 — Inputs are named, ordered and byte-exact** `[stated ans:Q2]`
- Given sources whose values hold newlines, quotes, `%`, `&`, `(`, non-ASCII text and JSON text
- When the code pointer runs in-process and over HTTP
- Then each `inputs[name]` equals the source's resolved string exactly, in both transports, and the
  key order is the source order.

**H3 — A weight-0.0 source is delivered** `[stated ans:Q2]`
- Given `(member_1:/a(…)!'P', extract_pattern:0.0:'ANSWER: \\d+')!/combine`
- When it runs
- Then `inputs["extract_pattern"] == "ANSWER: \\d+"` (the unescaped text `ANSWER: \d+`).

**H4 — `@` passes in the code pointer's query** `[stated ans:Q3]`
- Given the intent `/ensemble/combine/v1?reducer=vote&extract=last_number@1&normalize=numeric@1`
- When it runs
- Then `params == {"reducer": "vote", "extract": "last_number@1", "normalize": "numeric@1"}`.

**H5 — A mixed group still makes one call** `[stated ans:Q1]`
- Given members that are relative-expression calls plus a quoted weight-0.0 source (so the 1.5.1
  fan-out gate would not fire)
- When it runs with a code-pointer intent
- Then the code pointer runs once with all sources. The fan-out/base split does not apply to RDS.

**H6 — Quoted text stays LLM mode** `[stated ans:Q1]`
- Given `(member_1:/a(…)!'P', member_2:/b(…)!'P')!'Pick best'`
- When it runs
- Then the 1.5.1 fan-out reduce runs unchanged: labeled sections, `[Instruction]`, processor route.

**H7 — A nested-expression intent stays computed** `[stated ans:Q1]`
- Given `(https://src)!(https://a, https://b)!agg`
- When it runs
- Then `https://a` and `https://b` are fetched, as `T/spec/test_intent_as_value.py:37-50` pins.

**H8 — A remote url4 code pointer** `[proposed]` (P1)
- Given the intent `url4://scorer.example/score/v1?k=2`
- When the group runs
- Then the node sends one outbound fetch of kind `url4` to
  `url4://scorer.example/score/v1?k=2&q=(<document>)`, and the result is the response body.

### 3.2 Error paths

**E1 — Unknown code pointer** `[proposed]` (P12)
- Given the intent `/nope` and no endpoint at `/nope`
- When the group runs
- Then the run fails with code `intent_error`, permanent, and the message names `/nope`.
- And every source that resolved stays resolved (Spec C §13.6).

**E2 — A data route is not a code pointer** `[proposed]` (P12)
- Given the intent `/instr` where `/instr` is only a data route
- When the group runs
- Then the run fails with `intent_error`. A data route is never read as instructions in 2.0.

**E3 — The code pointer fails** `[stated prompt]` (Spec C §13.6) and `[proposed]` (P12)
- Given a handler that raises `ValueError`
- Then the run fails with `intent_error`, permanent.
- Given a handler that raises a `Url4Error` with its own code and permanence
- Then the run fails with that code and permanence.

**E4 — A soft-error input** `[stated prompt]` (Spec C §13.2.3) and `[proposed]` (P12)
- Given a source that answers HTTP 200 with an error page or an `{"error": …}` body
- When the group runs
- Then the node delivers that body as the input. The node does not sniff content.
- And if the code pointer rejects it, the run fails with `intent_error` and the source stays
  `resolved`.

**E5 — A required source fails** `[existing G/dag/nodes/guard.py:57-64]`
- Given a required source that fails
- Then the group fails with that source's error, and the code pointer is not called.

**E6 — Quorum not met** `[stated prompt]` (Spec C §12.2) and `[proposed]` (P11)
- Given two `;optional` members that both fail and `;quorum=1`
- Then the run fails with `quorum_not_met`, and the code pointer is not called.

**E7 — A non-url4 scheme** `[proposed]` (P2)
- Given the intent `https://code.example/score.py`
- When the expression compiles
- Then it fails with `unsupported_mode`, permanent, before any source resolves.

**E8 — A query outside `query-tail`** `[proposed]` (P9)
- Given the intent `/p?x=1,2`, or `/p?q=hello`, or `/p?a=1&a=2`
- When the expression compiles
- Then it fails with `malformed_source`, permanent (`,` is not in `query-tail`; `q` is reserved for
  the transport; a key may appear once).

**E9 — Protocol params keep `param-value`** `[stated ans:Q3]`
- Given an eval-path request `GET /v1?tone=a@b&q=(x='1')!'go'`
- Then dispatch still refuses `tone=a@b` with `malformed_source`, as in 1.5.1.

**E10 — A remote code pointer keeps the error code** `[proposed]` (P18, Should)
- Given a remote url4 node whose code pointer fails with `intent_error`
- When the caller reads the answer
- Then the caller raises `intent_error`, permanent, not a transient `resolution_failed`.

### 3.3 Derived scenarios (risk order)

**D1 — An optional source that failed is absent** (H×H) `[stated ans:Q2]`
- Given `(member_1:/a(…)!'P';optional, member_2:/b(…)!'P')!/combine;quorum=1` and `/a` fails
- Then `inputs` has `member_2` only. No `null`, no placeholder.

**D2 — Weight 0.0 stays instrumental in LLM mode** (H×M) `[stated prompt]` (OME-534)
- Given `(q:0.0:/hidden, 'lit')!'REDUCE $q'`
- Then the 1.5.1 result is unchanged: `$q` substitutes, and `/hidden` is not packed
  (`T/spec/test_abnf_contribution.py:47-53`).

**D3 — Unnamed sources use positional keys** (H×M) `[proposed]` (P4)
- Given `(member_1:/a(…)!'P', 'free text', /doc)!/combine`
- Then the keys are `member_1`, `$2`, `$3`, in that order. `$k` is the 1-based position after
  expansion, the same position `$k` names in a template.

**D4 — Collections arrive as JSON arrays** (H×M) `[stated prompt]` (Spec B §5.3.8) and
`[proposed]` (P5)
- Given a source that is an iteration expression, a broadcast group, an inline collection, or a
  named `;expand` source
- Then its input value is a JSON array (rows typed as `_rows_to_json` types them,
  `[existing G/dag/nodes/_shared.py:118-127]`), not a string.
- Given a fetched source whose body happens to be JSON array text, with no `;expand`
- Then its value is a string. Collection-ness comes from the expression, never from content.

**D5 — A struct-object source arrives as a JSON object** (M×M) `[proposed]` (P5)
- Given `(cfg={k: 'v', n: 3})!/combine`
- Then `inputs["cfg"] == {"k": "v", "n": 3}`.

**D6 — An unnamed `;expand` source** (M×L) `[proposed]` (P4)
- Given `(*/rows, 'x')!/combine` where `/rows` gives three elements
- Then the keys are `$1`, `$2`, `$3` (the elements) and `$4` (`'x'`).

**D7 — Broadcast makes one call per resolved source** (M×M) `[proposed]` (P10)
- Given `(a='1', b='2';optional, c='3')!*/score` and `b` fails
- Then `/score` runs twice, each time with `inputs == {"current": <value>}`.
- And the result is the Spec B §6.1.4 array with rows for positions 1 and 3.

**D8 — An iteration reducer that is a relative-uri** (M×M) `[proposed]` (P15)
- Given `(/rows*()!'R $item')!/reduce`
- Then `/reduce` runs once with `inputs == {"$1": ["R r1", "R r2"]}`.
- Given `(https://rows*()!'R $item')!/reduce()!'agg'` (a relative-expression reducer)
- Then the 1.5.1 behavior is unchanged (`T/spec/test_iteration_spec.py:236`).

**D9 — Vacuous quorum** (M×L) `[stated prompt]` (Spec C §12.2; IFEval contract §3.5) and
`[proposed]` (P11)
- Given two `;optional` members that both fail and the default `quorum=all`
- Then the code pointer runs with `inputs == {}`. Authors who need a floor set `;quorum=1`.

**D10 — `processor=` does not touch an RDS group** (M×M) `[proposed]` (P13)
- Given `processor=unknown-id` on the run and a code-pointer intent
- Then the run succeeds. The node resolves no processor for an RDS group.
- Given a run that mixes an RDS group and an LLM group
- Then only the LLM group uses the processor route.

**D11 — The eval path runs RDS on the remote node** (M×L) `[implied]`
- Given `GET /v1?q=(a='1', b='2')!/combine`
- Then the node evaluates the group itself and calls its own `/combine` once.

**D12 — Duplicate names** (M×L) `[proposed]`
- Today `build` and `compile_expression` both accept `(a='1', a='2')!/c` (probe, 2026-10-09).
- Given two sources with the same name and a code-pointer intent
- When the expression compiles
- Then it fails with `malformed_source`, permanent: one document cannot hold two equal keys, and
  the code would get only one of them. LLM-mode groups keep today's behavior.

**D13 — Not applicable** — cancel: the run's cancellation already cancels the one fetch; retry:
the code-pointer call is not a source, so `;retry=` does not apply to it; concurrency: there is one
call per group (per source under broadcast), so no new race exists.

## 4. Non-functional requirements

- **Cost.** An RDS group makes zero model calls and zero processor-route calls. `[stated prompt]`
- **Calls.** Exactly one code-pointer call per group, N under broadcast with N resolved sources.
  `[stated ans:Q1]`
- **Size.** In-process calls have no size limit. Over HTTP the input document travels in the GET
  query, like today's reducer input `[existing G/dag/nodes/group.py:297]`. The server's
  request-line limit applies. The encoder escapes only what a query cannot carry raw, so prose
  grows only by its spaces and reserved characters. A measurement of the limit for `url4 serve` is
  a task in the implementation plan. `[proposed]`
- **Observability.** The new node appears as `node_kind == "CodePointerNode"` in `NodeStarted`
  `[existing G/observe.py:45-50]`. That is the in-package `intent_mode = "rds"` signal. The
  Spec C envelope field `intent_mode` is out of scope (the package has no envelope). `[proposed]`
- **Security.** A relative code pointer resolves only against the node's own registered endpoints.
  A data route is never executed as code. A non-url4 scheme is refused (P2). `[proposed]`

## 5. Out of scope

- **U3b** free-text arg conventions (endpoint-side). `[stated ans:Q3]`
- **U4** call identity for attribution. `[stated ans:Q4]`
- Weights and other attribution metadata in the input document (Part D §17 envelope, Part E §22
  attribution). `[proposed]` (P6)
- A call's own URI intent (`/p(ctx)!/code`, `url4://n/p(ctx)!/code`, and the top-level fold
  `[existing G/dag/_wiring.py:181-205]`). The endpoint at `/p` is the intent processor for that
  call. Open item O1.
- Relative- and remote-*expression* intents (O2), bare-token "named job" intents (O3), a computed
  intent whose result is a code pointer (O4).
- `https://` code pointers beyond the refusal (Part G §26 is unpublished). `[proposed]` (P2)
- Changes to the grammar, the parser or the renderer. `[stated prompt]`
- `strict_fields` ("RDS mode" for field-path errors, `[existing G/dag/_run.py:122-126]`) stays a
  run option. It does not follow the intent mode. `[proposed]`

## 6. Open questions

Kevin's items K1–K9 and the owner items O1–O5 are in
[00-overview.md §6–§7](../00-overview.md#6-open-items-for-kevin-mcdonough). Each has a recommended
default, and this PRD is written to that default.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: core-out. The classifier and the param rule are pure and decide everything else, so they
come first. Then the document codec, then dispatch, then the group sites, then transports.

Discipline: RED first (the test fails on the missing behavior, not on an import error); GREEN
minimally; REFACTOR on green only; one behavior per test. **CHAR** rows pin 1.5.1 and pass on
today's code. A CHAR row marked "flips" pins behavior that 2.0 removes: that test changes in the
same commit as the behavior (approved by ans:Q5), and the PR body lists it.

### 7.1 Characterization rows

| # | Test (CHAR) | Level | Source | Today | 2.0 |
|---|---|---|---|---|---|
| CH1 | fan-out with text intent labels sections and calls the processor route | unit | `[existing T/spec/test_abnf_contribution.py:82-91]` | pass | stays |
| CH2 | weight-0.0 call excluded from the LLM reducer input | unit | `[existing T/spec/test_abnf_contribution.py:94-101]` | pass | stays |
| CH3 | weight-0.0 source instrumental in the LLM base merge | unit | `[existing T/spec/test_abnf_contribution.py:47-53]` | pass | stays |
| CH4 | nested-expression intent is executed | unit | `[existing T/spec/test_intent_as_value.py:37-50]` | pass | stays |
| CH5 | URI intents parse and round-trip (`!/plain/path`, `!https://…`, `!/reduce()`) | unit | `[existing T/spec/test_intent_as_value.py:85-122]`, `[existing T/unit/test_render.py:242-245]` | pass | stays (grammar unchanged) |
| CH6 | relative-expression iteration reducer `/reduce()!'agg'` | integration | `[existing T/spec/test_iteration_spec.py:236]` | pass | stays |
| CH7 | eval-path protocol param refuses `@` | unit | `[existing G/core/_annotations.py:131-135]` (new pin) | pass | stays |
| CH8 | `(https://a, https://b)!https://instr` → `INSTR\n\nA\nB` | unit | `[existing T/unit/test_dag.py:440-469]` | pass | **flips** to `unsupported_mode` (row 3) |
| CH9 | `(https://a)!/doc` lowers to Barrier + data-read `RelUrlNode` | unit | `[existing T/unit/test_dag.py:472-483]` | pass | **flips** to `CodePointerNode` (row 9) |
| CH10 | `!*https://instr` fetched once, rows `TAG\n\nA` | unit | `[existing T/unit/test_characterization.py:53-61]` | pass | **flips** to `unsupported_mode` (row 3) |
| CH11 | the §2.3 probe table, one test per row (new file `T/spec/test_rds_code_pointer.py`, written first, marked flips where 2.0 changes the row) | integration | `[implied]` | pass | rows 1, 2, 4, 6 flip |

### 7.2 Delta rows

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `intent_mode` classifies every row of the §2.5 table (one parametrized case per row, including `/p(c)!x`, `/p?q=(c)!x`, `url4://n/p(c)!x` as `legacy`) | unit | `[stated ans:Q1]` | H×H | pure function in `G/core/`; match the ABNF productions, not node types |
| 2 | relative code pointer with `query-tail` outside chars (`,`) refused at compile, `malformed_source` | unit | `[proposed]` | M×M | reuse the query-tail validator from row 4 |
| 3 | `https://`/`http://`/`s3://` intent refused at compile with `unsupported_mode`, permanent, before any fetch (flips CH8, CH10) | unit | `[proposed]` | H×M | add `UNSUPPORTED_MODE` and `INTENT_ERROR` to `ErrorCode` |
| 4 | query-tail param reader: `extract=last_number@1` kept; `+` literal; `%40` → `@`; flag `k` → `""`; key `q` refused; duplicate key refused | unit | `[stated ans:Q3]` | H×H | new `validate_query_tail` beside `validate_param`; decode with `unquote`, not `unquote_plus` |
| 5 | eval-path and url4-URI protocol params still use `param-value` (`tone=a@b` refused) | unit | `[stated ans:Q3]` | H×M | the reader picks the rule from the request kind, not from the key |
| 6 | RDS document encoder: names, `$k` keys, source order, weight-0.0 included, failed optional absent; duplicate names refused at compile (D12) | unit | `[stated ans:Q2]` | H×H | new codec in `G/wire/`; reuse `_gather` ordering; do not drop instrumental slots |
| 7 | RDS document typing: string default; struct-object → object; iteration/broadcast/inline/named-expand → array; JSON-looking fetched text → string | unit | `[proposed]` | H×M | mark collection payloads by type (for example a `CollectionText(str)` like `FetchedText`), never by content |
| 8 | wire round-trip: seeded random corpus (newline, quotes, `%`, `&`, `(`, `)`, `#`, `+`, non-ASCII, empty string) → URL → decode → identical document | unit | `[stated ans:Q2]` | H×H | percent-encode per C2; decode with one `unquote` |
| 9 | `(…)!/code` compiles to a `CodePointerNode` with the group's slots (flips CH9) | unit | `[stated ans:Q1]` | H×H | route in `_reduce_graph` **before** the fan-out gate and the fold |
| 10 | dispatch: `q=(<doc>)` with no `!` tail → handler gets `mode="rds"`, `inputs`, `context` = document text, `intent=""`, query-tail params | unit | `[proposed]` | H×H | decode the q payload first, then choose the param rule |
| 11 | dispatch: every LLM call shape still yields `mode="llm"` and `inputs=None` | unit | `[implied]` | H×M | the marker needs both "no `!` tail" and a valid v1 document |
| 12 | H1: members run, `/ensemble/combine/v1` runs once, no processor route, no `process` hook | integration | `[stated ans:Q1]` | H×H | `CodePointerNode` fetches through `ctx.io` |
| 13 | H3 + D2: weight-0.0 delivered in RDS; still instrumental in LLM | integration | `[stated ans:Q2]` | H×H | RDS gather keeps instrumental slots |
| 14 | H5: mixed calls + quoted source → one call | integration | `[stated ans:Q1]` | H×M | — |
| 15 | D1 + E6 + D9: optional absent; `quorum=1` all failed → `quorum_not_met`, no call; `quorum=all` vacuous → call with `{}` | integration | `[stated prompt]` | H×M | quorum counts every resolved input |
| 16 | E5: required source fails → group fails, no call | integration | `[existing G/dag/nodes/guard.py:57-64]` | M×M | — |
| 17 | E1 + E2: unknown path and data-route-only path → `intent_error`, permanent | integration | `[proposed]` | H×M | map `endpoint_not_found` from the call to `intent_error` |
| 18 | E3: handler `ValueError` → `intent_error`; handler `Url4Error(code, permanent)` kept | integration | `[proposed]` | M×M | wrap non-`Url4Error` only |
| 19 | E4: a 200 error body is delivered, not sniffed | integration | `[stated prompt]` | M×L | — |
| 20 | D7: broadcast → one call per resolved source with `{"current": v}`; §6.1.4 rows | integration | `[proposed]` | M×M | `MergeNode` gets an RDS branch, or a per-source `CodePointerNode` |
| 21 | D8: iteration reducer `/reduce` → one call with `{"$1": [...]}`; `/reduce(all)!'agg'` unchanged | integration | `[proposed]` | M×M | branch in `ReduceNode` on `intent_mode` |
| 22 | D10: `processor=unknown-id` + RDS group succeeds; mixed run uses the route only for the LLM group | integration | `[proposed]` | M×M | `CodePointerNode` never reads `ctx.processor` |
| 23 | H8: `url4://` code pointer → one outbound fetch, kind `url4`, target per C3 | integration | `[proposed]` | M×M | reuse `RemoteFetchNode` target building |
| 24 | H2 over HTTP: ASGI node + httpx ASGI transport; byte-exact inputs and `@` params through a real HTTP hop | integration | `[stated ans:Q2]` | H×M | — |
| 25 | D11: eval path `/v1?q=(…)!/combine` calls the node's own `/combine` | integration | `[implied]` | M×L | — |
| 26 | E10: remote `intent_error` keeps its code and permanence at the caller (Should) | integration | `[proposed]` | M×M | the `url4` kind reads `{"error": {"code"}}` from the body |
| 27 | E9: CH7 still holds after rows 4–5 (guard) | unit | `[stated ans:Q3]` | H×M | — |
| 28 | observability: `NodeStarted.node_kind == "CodePointerNode"` for an RDS group | unit | `[proposed]` | L×M | — |
| 29 | E2E: the E4a 3-model vote url4 (§1 of the E4a nested-url4 PRD) runs against a stub combine and gets the three member texts byte-exact plus the five params | e2e | `[stated prompt]` | H×M | the spine; one test |
