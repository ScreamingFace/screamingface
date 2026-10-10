# url4 2.0.0 — code-pointer intents run as RDS calls (reshaped spec)

**Status:** draft for review (2026-10-10). This replaces the 2026-10-09 draft
`docs/spec/2026-10-09-url4-rds-code-pointer/` (branch `OME-1567-url4-rds-code-pointer`,
deleted; the draft is not in the repo). It does not carry over that draft's decisions
(Q1–Q5, P1–P19). Each rule here comes from the goal, from URL4 Spec A, B and C
(`OpenMined/screamingface-design`, `kevin-mcdonough/docs/adrs/URL4-Spec-{A,B,C}.md`),
and from the owner's answers to Q1–Q9 on 2026-10-10 (§7).
· **Base:** branch `url4-audit-fixes` (the audit fixes change the parser and dispatch
that this work touches). · **Linear:** none yet (§10).

Reading order: this file → [contracts.md](contracts.md) → [prd/rds-code-pointer.md](prd/rds-code-pointer.md)
→ [test-plan.md](test-plan.md) → [formal/README.md](formal/README.md).

## 1. Goal

Spec A §1.1 gives URL4 two execution modes with one grammar:

- **LLM mode.** The sources are context, and the intent is a prompt.
- **RDS mode.** The sources are structured inputs, and the intent is a code pointer.
  "A node binds the resolved source data to the code's input contract and executes it."
  Variable references are "mechanically required" (Spec B §6.3).

url4 1.5.1 has only the LLM mode. It reads a URI intent as **instruction text**. The
first real user is blocked by this: in the E4a deterministic combine
`(member_1:…, member_2:…)!/ensemble/combine/v1?reducer=vote&extract=last_number@1`,
the node fetches `/ensemble/combine/v1` as text (an endpoint there answers
`missing_intent`, because the fetch has no `q=`), and `@` in its query fails `param-value`. Kevin's
IFEval contracts (check-surface, gate, case-evaluation) need the same thing: run
deterministic code over named sources, with no model in the path.

**Goal:** a URL4 author writes a code pointer as the intent, and the node runs that
code once, after the sources settle, with the sources bound by position and by name.
The behavior must conform to Spec A/B/C, and it must be small enough to prove.

## 2. The design in five rules

Each rule has a Lean theorem (`formal/`) and a Python test (test-plan §2).

| # | Rule | Spec basis | Lean |
|---|---|---|---|
| R1 | **The mode is a pure function of the intent's form.** A `relative-uri` → RDS: code on this node. Quoted text → LLM. An absolute URI (`url4://`, `https://`, `s3://`, …) → LLM: it is fetched and its content is the prompt, as in 1.5.1 (owner, Q1; deviation D2 from B §6). A bare token → LLM prompt (D1, until P3). Expression, variable/self/identity ref, struct → computed, and the result is the prompt (Q3). Only a relative URI ever runs code. | B §5.2, §6; A §1.4.1 | `Intent.lean` |
| R2 | **One call per group, after the gate.** The gate is: every `;required` source resolved, and the quorum met (`all`/`N`/`majority`, counted after expansion). Aggregate `!` → one call. Broadcast `!*` → one call per resolved source, with that source first (`$current`) plus any source a `$`-reference in the pointer names. Closed gate → no call. | C §12.2, §13.6; B §6.1.2, §5.3.12.7 | `Gate.lean` |
| R3 | **The code gets the inputs by position.** Input `k` is source `k` (1-based, after expansion), with its name, weight and exact value. A failed source has no input. Weight never filters delivery. | A §1.1; B §6.2, §5.3.10.3, §5.3.12 | `Binding.lean`, `Expansion.lean` |
| R4 | **The executor is a code mount on this node, found before any source starts.** A relative code pointer resolves only against the node's code mounts (not endpoints, not data routes). A static pointer (no `$`) that is not mounted fails with `intent_error`, and its sources do not start. A pointer form the node cannot run fails the same way with `unsupported_mode`. Both fail only their group. Every execution failure is `intent_error`. | B §6 "code pointer on current node"; A §1.4.3 Mount `local`; C §13.5.2, §13.6 | `Group.lean` |
| R5 | **No new wire message.** The call is in-process. A forwarded expression whose intent is a relative code pointer carries the pointer text verbatim (C §11.6.2 rule 3); the caller never fetches it. Code on another node is out of reach until Part G defines how inputs travel (Q2). | B §3.1, §8 ABNF; C §11.6.2 | `Intent.lean` (`v1`) |

Why the mode must be static (R1): Spec B §5.3.4.1 makes field-path errors strict in RDS
mode and lenient in LLM mode, and Spec B §8.2.1 runs interpolation *after parsing and
before resolution*. So the mode must be known from the parse tree alone. The hybrid
reading (Q1) keeps this property: the scheme is known at parse time, so a relative URI is
always RDS and an absolute URI is always LLM. A URI is never "fetched first, then
classified", and a computed intent never selects RDS mode from its result (Q3).

## 3. What the author sees

```
(member_1:/a($input)!'P', member_2:/b($input)!'P', pattern:0.0:'ANSWER: \\d+')
  !/ensemble/combine/v1?reducer=vote&extract=last_number@1
```

The node:

1. Checks that `/ensemble/combine/v1` is a code mount. If it is not, the group fails with
   `intent_error` and `/a`, `/b` never run.
2. Resolves the three sources, then applies the gate (default `quorum=all`, all sources
   required).
3. Calls the code once with:

```python
CodeCall(
    pointer="/ensemble/combine/v1",
    params={"reducer": "vote", "extract": "last_number@1"},
    inputs=(
        CodeInput(position=1, name="member_1", value="A says 4", weight=None),
        CodeInput(position=2, name="member_2", value="B says 5", weight=None),
        CodeInput(position=3, name="pattern", value="ANSWER: \\d+", weight=0.0),
    ),
)
```

4. Uses the returned string as the group's value. No model and no processor route run.

The node owner registers the code with a new decorator, separate from endpoints:

```python
@node.code("/ensemble/combine/v1")
def combine(call: CodeCall) -> str: ...
```

## 4. Scope

| In 2.0.0 | Not in 2.0.0 |
|---|---|
| Exact intent classifier (R1), including relative/remote **expression** intents, which become computed (today they are misread as data reads). This changes the AST that `intent_atom` builds, so `render.py` changes in lockstep (round-trip stays exact) | Bare-token named jobs (deviation D1, deprecated, phase 3) |
| `CodeMount` registry, `CodeCall`/`CodeInput` types, in-process invocation | Absolute-URI intents as code (`url4://`, `https://`, `s3://`): they keep the 1.5.1 fetch-as-prompt meaning (D2; Q1, Q2) |
| RDS group at every group site: base, fan-out, broadcast, iteration body | A computed intent that resolves to a code pointer (Q3) |
| Gate per R2, including `quorum=majority` (url4 refuses it today) | Envelope fields (`intent_mode`, trigger results), capabilities document |
| Strict field paths in RDS scopes (B §5.3.4.1) | Content-type checks on inputs (C §13.2.3, waits for Part G §26.2.4) |
| A forwarded call (relative or remote) keeps a relative code-pointer intent verbatim (C §11.6.2 rule 3) | The LLM-mode and wire deviations listed in §8 |
| `intent_error` (HTTP 422), `unsupported_mode` (HTTP 501, for a node with no code port); every other permanent code → 4xx | Content types in `CodeInput` (Q7) |
| | Any grammar change, or any change to what the parser accepts |

## 5. Phases (one PR each, in order)

| Phase | Content | Breaks |
|---|---|---|
| P1 Classifier | `IntentForm` + `classify_intent` in `url4.core`; `intent_atom` and `render.py` in lockstep; relative/remote expression intents compile as computed; absolute-URI intents keep the fetch-as-prompt path | relative-URI intents stop being fetched as prompts; relative/remote expression intents are evaluated instead of read as data |
| P2 Code mounts | `@node.code`, `CodeCall`, `CodeInput`, `SupportsCode` port, preflight, `CodeCallNode` at every group site, binding, gate with `majority`, strict scopes, error codes and statuses (permanent → 4xx), verbatim forwarded pointer | relative-uri intents now run code; permanent errors that were 500 become 422 |
| P3 Named jobs | bare token → code mount lookup by name (target profile; `target_conformant`) | bare-token prompts; needs one minor release of deprecation warnings after P2 |

P1 and P2 ship together as 2.0.0. P3 is 3.0.0, or 2.x with an opt-in flag, as the owner decides.

## 6. Conformance register

| Item | Status | Basis |
|---|---|---|
| Mode by form (static) | conformant (P1) | B §6, §8.2.1 |
| Relative code pointer runs on this node | conformant (P2) | B §6, A §1.4.3 |
| Absolute URI (`url4://`, `https://`, …) fetched as the prompt | **deviation D2** (owner, Q1): follows A §1.4.1 "must resolve to a prompt", breaks B §6 "code pointer" | A §1.4.1 vs B §6 |
| Bare token as prompt | **deviation D1** until P3 | B §6 "named job" |
| Computed intent → prompt only | **restriction** (owner, Q3) | A §1.4.1 allows code pointer |
| Weight-0.0 delivered in RDS | conformant | B §5.3.10.3 |
| Expansion naming `name[i]`/`src[i]` | conformant; names are not unique keys (Q4) | B §5.3.12.5 |
| Gate (`all`, `N`, `majority`) | conformant after P2 | C §12.2 |
| RDS field paths strict, LLM lenient (keyed on the action taken) | conformant after P2 | B §5.3.4.1 |
| Every execution failure is `intent_error` (handler code kept as detail) | conformant | C §13.6 |
| Broadcast inputs: `$current` + `$`-referenced sources | conformant | B §6.1.2 |
| Status codes | conformant: class preserved through C §13.2.1 for every code | C §13.2.1 |
| `quorum=all` = all required sources | follows C §12.2 (owner, Q9); B §5.3.12.7 reads it differently | C §12.2 |
| Forwarded prompt intents lose their quotes and are resolved by the caller | **existing deviation A5**, unchanged | C §11.6.2, B §8 ABNF |
| No soft-error detection on sources | existing deviation, unchanged (§8) | C §13.2.3 SHOULD |

## 7. Decisions (owner, 2026-10-10) and spec issues for Kevin McDonough

The owner answered Q1–Q9. The "For Kevin" column names what the spec text should fix or
confirm; the decision does not wait on it.

| # | Question | Decision | For Kevin |
|---|---|---|---|
| Q1 | Spec A §1.4.1: a URI intent "must ultimately resolve to" a prompt or code. Spec B §6: a URI intent **is** a code pointer. | **Hybrid by scheme.** A relative URI is code on this node. Every absolute URI (`url4://`, `https://`, `s3://`, …) keeps the 1.5.1 meaning: fetched, content used as the prompt (D2). | Reconcile A §1.4.1 and B §6; say whether an absolute URI intent is code or a prompt source. |
| Q2 | No conformant way to send *resolved* inputs to another node: `quoted-char` is printable ASCII (no newline, no non-ASCII), and a collection cannot be a literal source. | **Refuse until Part G.** Under Q1 no 2.0 intent form reaches this rule; it applies when absolute URIs become code. | Part G §26: define the input transport for remote code. |
| Q3 | Can a computed intent resolve to code? That makes the mode dynamic (B §8.2.1 + §5.3.4.1). | **Always a prompt.** | Confirm, or define dynamic-mode interpolation. |
| Q4 | B §5.3.12.5 names two unnamed expansions `src[0]…` twice (`unnamed_expansions_collide`). | **Position is the key.** `CodeCall.input(name)` raises `ValueError` on an ambiguous name. | Make expanded names unique. |
| Q5 | Error code for an unmounted code pointer. | **`intent_error`** (permanent, 422). | — |
| Q6 | How a bare-token named job (P3) is found. | **One code table, own keys:** `@node.code("/score/v1")` vs `@node.code("score_v1")`; `!score_v1` finds only the name key. | Confirm the "named job" lookup. |
| Q7 | Content types in the input contract (C §13.2.3). | **Not in 2.0.** Add `content_type` beside `weight` with Part G §26.2.4. | Part G §26.2.4. |
| Q8 | Duplicate keys in a code pointer's `query-tail`. | **Refuse** at compile time (`malformed_source`). | Say whether `query-tail` has key/value semantics. |
| Q9 | `quorum=all`: B §5.3.12.7 "all sources after expansion" vs C §12.2 "all `;required` sources". | **C §12.2** (url4 1.5.1 already reads it this way). | Fix B §5.3.12.7. |

## 8. Adjacent deviations found (not changed here; one issue each)

- **A1** LLM mode drops weight-0.0 sources from the context (OME-534). Spec A §1.1 says
  "the model receives all source data regardless".
- **A2** Package error codes outside the C §13.5.2 registry have no `x.` prefix
  (`quorum_not_met`, `endpoint_not_found`, `missing_intent`, `unknown_processor`, …).
- **A3** No soft-error detection for HTTP 200 sources (C §13.2.3 SHOULD).
- **A4** The iteration "relative-expression reducer" (`(rows*(…))!/reduce()!'agg'`)
  passes the rows into `/reduce`. Under B §6 the intent is a computed expression that is
  evaluated on its own sources. P1 keeps this special case and lists it.
- **A5** A forwarded call (`/p(ctx)!'Answer'`, `url4://n/v1(…)!'…'`) is sent with the
  caller-resolved intent text and no quotes (`q=(…)!Answer text`). That is not an ABNF
  expression, and the receiver cannot tell the prompt `/x` from the pointer `/x`. The
  conformant form keeps the intent's source text (quotes included). It changes the wire
  for every forwarded call, so it is its own issue; 2.0 fixes only code-pointer intents
  (R5, C9).

## 9. Release and migration

- **Version.** P1+P2 → url4 2.0.0 through release-please. Squash title:
  `feat(url4)!: run code-pointer intents as RDS calls`, with a `BREAKING CHANGE:` footer.
- **Who breaks.** Only relative-URI intents change meaning, and relative/remote
  expression intents now evaluate (they were broken data reads). The monorepo search on
  2026-10-09 found no live URI intent in Engine, SDK or Studio (only tests and docs).
  Absolute-URI and bare-token intents keep their 1.5.1 behavior.
- **Migration note** (url4 README, "Migrating to 2.0"):
  1. A URI intent that held instruction text → write the text as a quoted intent, or
     bind it as a weight-`0.0` source and reference it: `(…, instr:0.0:/instr)!'$instr'`.
  2. Code that ran behind an `@node.endpoint` as a reducer → register it with
     `@node.code` and read `call.inputs` and `call.params`.
  3. To run code on another node, send the whole expression to that node, as the
     top-level request (`url4://n/v1?q=(…)!/code`) or as a source
     (`(r:url4://n/v1(…)!/code)!'…'`). An absolute-URI *intent* is still a prompt source.

## 10. Filing

No Linear issue now. At PR time, after the user confirms: one issue per phase under the
url4 grammar-conformance epic OME-500, mirrored in `docs/tasks/`, with `Refs: OME-N` in
each PR body. The four adjacent deviations (§8) get their own issues under the same epic.
