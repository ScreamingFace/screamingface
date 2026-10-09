# url4 2.0.0 — URI intents run as RDS code-pointer calls

**Status:** draft for review (2026-10-09) · **Branch:** `url4-rds-code-pointer` (docs only) ·
**Ledger:** [docs/work/2026-10-09-url4-rds-code-pointer.md](../../work/2026-10-09-url4-rds-code-pointer.md) ·
**Linear:** none yet (§10)

## 1. Summary

URL4 Spec B §6 gives an intent its mode by its form. Quoted text is a prompt (LLM mode). A relative
or absolute URI is a code pointer (RDS mode). A nested expression is a computed intent. url4 1.5.1
does not follow this for URIs. It fetches a URI intent as **instruction text** and gives the
sources to the default model (fan-out) or to the `process` hook (base merge). So a deterministic
combine such as `(member_1:…, member_2:…)!/ensemble/combine/v1?reducer=vote` fails with
`endpoint_not_found`, and `extract=last_number@1` in its query fails with `malformed_source`.

url4 2.0.0 makes a URI intent an RDS code-pointer call:

- The node calls the code pointer **once per group**, after the sources are terminal and quorum
  passes, with an **RDS input document**: every source by name (or `$k` when unnamed), weight-`0.0`
  sources included, a failed optional source absent, values as exact JSON strings, collections as
  JSON arrays.
- The handler gets the document as `Request.inputs`, with `mode="rds"`, and the code pointer's
  `?query-tail` as `params`, read by the grammar's `query-tail` rule, so `@` passes.
- Quoted-text intents, nested-expression intents, and LLM-mode packing (OME-534) do not change.
- The grammar, the parser and the renderer do not change. This is execution semantics and the
  param reader.
- It is a breaking change: 1.5.1 → 2.0.0.

The wire shape is our proposal. Part G §26 is not published, so Kevin McDonough confirms it (§6).

## 2. Subsystems and ownership

| Subsystem | Landing | Change |
|---|---|---|
| Classifier, query-tail rule, error codes | `packages/url4/src/url4/core/` | new pure functions; `ErrorCode` gains `intent_error`, `unsupported_mode` |
| RDS document codec, call target | `packages/url4/src/url4/wire/` | new, beside `encode_subrequest` |
| Group sites, `CodePointerNode` | `packages/url4/src/url4/dag/` | new node; routing in `_wiring.py` and `ReduceNode` |
| Dispatch, `Request`, HTTP status | `packages/url4/src/url4/peer/` | RDS marker, `Request.mode`/`inputs`, two status rows |
| Outbound url4 adapter | `packages/url4/src/url4/io/http.py` | keep the remote error code (Should) |
| Engine, SDK, Studio | — | no change (§8) |

One app/package is touched, so one issue (no sub-issues). `[implied]` (repo CLAUDE.md)

## 3. Reading order

1. This overview: §4 decisions, §5 proposed decisions, §6–§7 open items.
2. [prd/rds-code-pointer.md](prd/rds-code-pointer.md): current behavior with probes, the
   classification table (§2.5), scenarios, and the TDD plan.
3. [contracts.md](contracts.md): C1 document, C2 in-process call, C3 HTTP, C4 remote, C5 broadcast
   and reducer, C6 param reader, C7 errors, C8 layering.
4. [test-plan.md](test-plan.md): risk, lanes, coverage map, release checks.

## 4. Decisions ledger (user, 2026-10-09)

The user gave these decisions with the task. They are closed.

| Q | Topic | Answer (verbatim intent) |
|---|---|---|
| Q1 | U1 conformance | An intent that is a `relative-uri` or an absolute URI (`url4://`; `https://` to decide, with a recommendation) is an RDS code pointer. The node calls it once with the group's sources. The old meaning (fetch the URI as instruction text, then reduce with the default processor) ends for URI intents. A quoted-text intent stays LLM mode. A nested-expression intent stays computed (OME-502). Mode is inferred from the intent form, never declared. |
| Q2 | U2 delivery | The code pointer receives every named source by name as structured data, including weight-`0.0` sources: weight is attribution metadata, not "do not deliver". A failed optional source is absent. The exact wire shape is ours to propose; Kevin confirms it. Propose the in-process `Request` shape and the HTTP encoding, keys for unnamed sources, value typing, and where metadata goes. |
| Q3 | U3a / U3b params | U3a: a code pointer's `?query-tail` reaches the handler as params by the grammar's `query-tail` rule, not by `param-value`; `@` passes. Protocol params of a url4 URI's own query string keep `param-value`. U3b is not url4 work: free-text args travel as named quoted sources, a convention of the consuming endpoint. |
| Q4 | U4 call identity | Deferred; future work. |
| Q5 | Release | Breaking semantic change: 1.5.1 → 2.0.0, with a CHANGELOG entry and a migration note. Search the monorepo for real users of URI intents and list them. |
| Q6 | Version and no-path pointer (2026-10-09, after the build) | This change joins 2.0.0; release PR #852 merges after it. A `url4://node` intent with no path is `malformed_source` (plan L7). |
| Q7 | O7 (2026-10-09) | url4 opt-in, default refuse: an endpoint receives code-pointer calls only when it registers with `@node.endpoint(path, rds=True)`. A code-pointer call to any other endpoint fails with `intent_error` before the handler runs. The Engine needs no change. |
| Q8 | Follow-ups (2026-10-09) | O6, O7 and the module-size splits ship in this PR (plan, "Follow-ups"). |
| — | Sources of truth | The URL4 grammar (ABNF) is the source of truth; Spec B and C explain it. Kevin's IFEval contract is a reference, not the truth. `[stated prompt]` |

## 5. Proposed decisions (ours; tagged `[proposed]` in the docs)

| # | Decision | Where |
|---|---|---|
| P1 | One classifier maps the intent text to the ABNF production (table in PRD §2.5). `relative-uri` → RDS on this node; plain `url4://` reference → RDS on that node; relative/remote *expression* text → unchanged (`legacy`). It does not trust the `RelUrl`/`Url` node type, because `intent_atom` also puts expressions there. | PRD §2.5 |
| P2 | **`https://`, `http://` and other non-url4 schemes as an intent fail at compile time with `unsupported_mode`, permanent.** Reasons: Spec B §3.5 says an `https://` target expects no URL4 behavior, so it cannot read our input document; Part G §26 (non-URL4 handling) is unpublished; and a later move from "refused" to "runs" is not a breaking change, while the reverse is. | PRD E7, C7 (K3) |
| P3 | The payload is one JSON object `{"v": 1, "inputs": {…}}`. `v` leaves room for metadata and U4. | C1 (K1) |
| P4 | Keys: the name for a named source; `$k` (1-based position after expansion) for an unnamed one; a named `;expand` source is one array under its name; an unnamed `;expand` source gives one `$k` per element. | C1 (K5) |
| P5 | Values are exact JSON strings by default. A JSON array only when the expression makes the source a collection (iteration, broadcast group, inline collection, named expansion). A JSON object for a `struct-object` source. Never by sniffing content. | C1 (K1) |
| P6 | No weights, budgets, content types or call identity in v1 (Part D §17, Part E §22, U4). | C1 (K7) |
| P7 | `Request` gains `mode: Literal["llm","rds"] = "llm"` and `inputs: Mapping[str, RdsValue] \| None = None`. For RDS, `context` is the document text and `intent` is `""`. Same `@node.endpoint` registry; 1.x handlers keep working. | C2 (K1) |
| P8 | HTTP: `GET <path>?<query-tail>&q=(<percent-encoded document>)` with **no `!` tail**. The marker is "no `!` tail" plus "a valid v1 document". Escape all but unreserved and `! $ * , ; : @ / ? =`. | C2, C3 (K2) |
| P9 | Query-tail reader: split on `&` and the first `=`, decode with `unquote` (`+` stays `+`), validate against `query-tail`, refuse a `q` key and duplicate keys, `malformed_source`. Used at compile time and at dispatch. | C6 |
| P10 | Broadcast `!*` with a code pointer: one call per resolved source, `inputs == {"current": <value>}`, results as Spec B §6.1.4. In scope, because 2.0 must close every old fetch-as-text path. | C5 (K4) |
| P11 | Quorum counts every resolved input (weight-`0.0` included). A required failure or an unmet quorum stops the group before the call. A vacuous `quorum=all` (every source optional and failed) calls with `{}`, as Spec C §12.2 reads; Kevin's contract §3.5 says authors set `;quorum=1`. | PRD E5, E6, D9 (K8) |
| P12 | Errors use Spec C codes: unknown code pointer (also a data-route-only path) → `intent_error`; handler crash → `intent_error`; a handler's own `Url4Error` keeps its code; no content sniffing of sources. | C7 (K6) |
| P13 | `processor=` (§27.3) does not apply to an RDS group: the code pointer's URI is its executor. An RDS group needs no processor route and never fails on `unknown_processor`. Mixed runs use the route only for LLM groups. | PRD D10 (K9) |
| P14 | In LLM mode a weight-`0.0` source stays instrumental (OME-534). Only RDS delivers it. | PRD D2 |
| P15 | An iteration reducer that is a `relative-uri` or a `url4://` reference is a code pointer: one call with `{"$1": [rows]}`. A relative-*expression* reducer (`/reduce(all)!'agg'`) does not change. | C5 |
| P16 | Out of this change: a call's own URI intent (`/p(ctx)!/code`, its top-level fold), relative/remote *expression* intents, bare-token intents. See O1–O3. | PRD §5 |
| P17 | `strict_fields` stays a run option and does not follow the intent mode. | PRD §5 |
| P18 | (Should) For a `url4://` target, the outbound adapter keeps the remote `{"error": {"code"}}` and its permanence, so a remote `intent_error` is not retried as transient. | C4 |
| P19 | Release through release-please: `feat(url4)!:` + `BREAKING CHANGE:` footer; migration note in `packages/url4/README.md`. | §9 |

## 6. Open items for Kevin McDonough

Part G §26 is not published. These are the points where our proposal stands in for it. Each has a
recommended default, and the docs follow the default until Kevin answers.

| # | Question | Recommended default |
|---|---|---|
| K1 | Is the RDS input document `{"v": 1, "inputs": {…}}` with exact-string values (P3, P5), and `Request.mode` / `Request.inputs` (P7), the delivery shape you want for code pointers? | yes, as written |
| K2 | Is "no `!` tail + valid v1 document in `q=`" an acceptable marker for an RDS call over HTTP GET, and is the escape set right (P8)? Two facts from code review (contracts C2): a context-only LLM call (`q=(ctx)`, used by the Engine judge) whose context is a v1 document reads as RDS; and a 1.x node runs a 2.0 RDS call silently as an LLM call. With the opt-in (ans:Q7), a `q=` with no tail that holds a document that is not v1 (e.g. `{"v":2,…}`) still reaches an endpoint without `rds=True` as an LLM call, so the "never sees a document" promise holds only for v1 (design review, 2026-10-09). | yes; alternative is a separate `@node.code_pointer` registry, rejected because it splits the routing table |
| K3 | Should `https://` (and other non-url4 schemes) as an intent be refused with `unsupported_mode` until §26 exists (P2)? | yes |
| K4 | In broadcast, is the per-call key `current` right, or do you want the source's own key (P10)? | `current` (Spec B §6.1.2) |
| K5 | For a named `;expand` source, one array under the name, or `name[i]` keys per Spec B §5.3.12.5 (P4)? And: `$k` counts resolved sources (as a template's `$k` does), so in `(/a, /missing;optional, /c)!/code` the third source arrives as `$2`. Should `$k` be the written position instead (`$2` absent), or should an RDS group with an unnamed `;optional` source require names? | one array; `$k` as the template counts (as built) |
| K6 | For an unknown code pointer, is `intent_error` right, or do you want a dedicated `x.` code (P12)? | `intent_error` |
| K7 | Should v1 carry per-input metadata (weight, content type for the Spec C §13.2.3 content check), or wait for Part D/E (P6)? | wait |
| K8 | With every source optional and failed and `quorum=all`, call with `{}` (Spec C §12.2 read literally) or refuse (P11)? | call with `{}` |
| K9 | Should `processor=` be ignored for an RDS group, or should it select a code runner (P13)? | ignored |

## 7. Open items for the owner (not url4 2.0 scope unless the owner says so)

| # | Item | Recommended next step |
|---|---|---|
| O1 | A call's own URI intent (`/p(ctx)!/code`, `url4://n/p(ctx)!/code`) is still resolved by the **caller** and sent as text `[existing packages/url4/src/url4/dag/_lowering.py:149-165]`. For a remote call that reads `/code` on the wrong node. | separate issue under OME-500 |
| O2 | `intent_atom` classifies relative and remote **expressions** in intent position as `RelUrl`/`Url` by their first characters `[existing packages/url4/src/url4/core/grammar.py:916-925]`, so they run as data reads: `((x='hi')!'S')!/w?q=($1)!'Write'` sends the literal context `$1` and the intent `'Write'` with its quotes (probe, 2026-10-09). This contradicts OME-502 ("nested expression = computed"). **It affects E4a:** the nested-url4 PRD's "Next stage" form `((members)!/ensemble/combine/v1?…)!<route>?q=($1)!'<prompt>'` relies on `$1`, and this spec does not change it. | separate OME-500 issue. No longer blocks E4a: its Next-stage form now uses a call whose context is the previous stage, `(0.0:<route>(<previous stage>)!'…')!'$1'`, which runs on 1.5.1 (E4a GE45) |
| O3 | Spec B §6 reads a bare-token intent as a "Named job / command identifier". url4 treats it as prompt text. | keep; revisit with Part G |
| O4 | Spec A §1.4.1 says a computed intent "must ultimately resolve" to a prompt or a code pointer. url4 always uses the computed result as prompt text. | keep; revisit with Part G |
| O5 | U4 call identity for attribution (deferred, ans:Q4). The document's `v` field leaves room. | future issue |
| O7 | A handler that never reads `Request.mode` accepts an RDS call. The Engine's model routes (`_ModelEndpoint`, `connector.py:345`) would send the document JSON, weight-0.0 sources included, to a model: `(a, b)!/<model-route>` failed with `endpoint_not_found` in 1.5.1 and is a paid call in 2.0 (code review, 2026-10-09). | in this PR, in url4 (ans:Q7, plan U2): endpoints opt in with `rds=True`; the Engine needs no change |
| O8 | `apps/screamingface-engine/tests/unit/test_no_private_url4_dispatch_import.py:17` forbids importing `url4.peer._dispatch` and `_http`, but not the new private `url4.peer._code_pointer` and `_request` (design review, 2026-10-09). | Engine follow-up (a one-line addition to that guard test) |
| O6 | An LLM-mode broadcast (`(a, b;optional)!*'…'`) calls the `process` hook with `""` for a failed optional source and keeps a row with an empty result, so the collector's skip never fires (found while building D7, 2026-10-09). The RDS broadcast does not do this. | in this PR (ans:Q8, plan U1) |

## 8. Real users of URI intents (monorepo search, 2026-10-09)

Searched: `apps/` (Engine, Studio, others), `packages/screamingface` (SDK), `packages/url4`
(`src`, `README.md`, `ARCHITECTURE.md`, `examples/`), `docs/`, `scripts/`, notebooks. Patterns:
`)!/…`, `)!*/…`, `)!url4://…`, `)!https://…`, `!/reduce`, programmatic `RelUrl`/`Url` intents,
`f"…)!{…}"` builders. The scout's first report listed the corrective-loop routes; a recheck showed
those are **sources** with quoted intents (`/route(ctx)!'text'`), not URI intents.

| Area | Hit | Effect of 2.0 |
|---|---|---|
| Engine (`apps/screamingface-engine/src`) | none live. `world/connector.py:465` sets `default_processor` (used by text-intent fan-outs; unchanged). `benchmarks/registry.py:97` mentions `!/reduce()` in a comment about route collection. | none |
| Engine fixtures (`tests/unit/data/*corrective*.url4`) | none (no `)!/`) | none |
| SDK (`packages/screamingface/src`) | none; it builds `RelExpr` calls with `Text` intents | none |
| Studio (`apps/screamingface-studio/frontend/src/lib/recipe.ts:221,243`) | source calls `name:0.0:/path(ctx)!intent` and a quoted root `'$ref'` | none |
| url4 tests | `T/unit/test_dag.py:440-469`, `:472-483`; `T/unit/test_characterization.py:53-61` | flip (CH8–CH10) |
| url4 tests, parse/render only | `T/spec/test_intent_as_value.py:85-122`, `T/unit/test_render.py:242-245,287,632`, `T/unit/test_builders.py:257`, `T/spec/test_grammar_conformance.py:87,95` | none |
| url4 tests, relative-*expression* reducers | `T/spec/test_iteration_spec.py:236`, `T/unit/test_iteration.py:436`, `T/unit/test_parser.py:61,168,176`, `T/unit/test_dag.py:915` | none |
| Docs | `docs/PROJECT-OVERVIEW.md:280-363` (`)!/data/check_correct.py`, `)!/data/calculate_accuracy.py`, legacy canvas expressions) and `docs/ISSUES.md:132` (I-17) | these are already written as code pointers; 2.0 gives them the meaning they assume |
| Docs | `docs/spec/2026-07-25-OME-605-screamingface-client-v1.md:722` (`(...)!/aggregators/draco/1()!'…'`) | a relative-*expression* intent (O2); unchanged |
| Local, unpushed | E4a nested-url4 PRD (branch `e4a-deterministic-combine`, `docs/spec/2026-10-02-e4a-gap-closure/prd/nested-url4.md`) | **first real user**; blocked on U1, U2, U3a (its ans:Q27); see O2 for its Next-stage form |
| External reference | Kevin's IFEval contract (`check-surface`, `gate`, `case-evaluation`, `run-evaluation` as RDS intents) | the target behavior |

`T` = `packages/url4/tests/`. Conclusion: no live production code depends on the 1.5.1 meaning, so
the break is safe to ship. `[implied]`

## 9. Grammar productions touched (checked against the ABNF)

No production changes. These productions get new or confirmed execution meaning.

| Production | Role in this change |
|---|---|
| `intent = value` | the classifier reads which `value` alternative the intent text is (PRD §2.5) |
| `intent-op = "!" / "!*"` | `!*` → one call per resolved source (P10) |
| `relative-uri = "/" path-segment *( "/" path-segment ) [ "?" query-tail ]` | code pointer on this node |
| `path-segment` (admits `$`) | `$name` in the path substitutes from the outer scope, as today |
| `query-tail = *( ALPHA / DIGIT / unreserved / ":" / "@" / "/" / "?" / "+" / "&" / "=" )` | the U3a reader (C6); `,` and `%` are outside it |
| `bare-value` (with `://`) | `url4://` reference → remote code pointer; other schemes → `unsupported_mode` |
| `relative-expr-canonical` / `-sugar`, `remote-expr-canonical` / `-sugar`, `local-expr` | not code pointers; unchanged (O2 for the first four) |
| `expr-params`, `expr-param` | `;quorum=…` after a code pointer stays an expression param |
| `query-string`, `protocol-param`, `param-value`, `rel-query-params`, `nested-param-value` | unchanged; protocol params keep `param-value` (ans:Q3) |
| `source-list`, `annotated-source`, `attrib-chain`, `name-part`, `scalar-weight`, `sugar-source` | give the input keys; weight never filters RDS delivery |
| `exec-flag` (`required` / `optional`) | a required failure stops the call; an optional failure is absent |
| `variable-ref = "$" ( name-part / 1*DIGIT ) [ field-path ]` | `$k` keys for unnamed sources |
| `struct-object`, `iteration-expr` (and Spec B §5.3.11 inline collections) | JSON object / JSON array values |
| `quoted-text`, `quoted-char` (`\'`, `\\`) | U3b args travel as named quoted sources; `''` doubling is not valid (probe) |

## 10. Release, migration and filing

- **Version.** 1.5.1 → 2.0.0 through release-please. `main` already holds a breaking url4
  change (#1085), and release PR #852 proposes 2.0.0 for it. The user decided (2026-10-09) that
  this change joins 2.0.0: it merges before #852, and #852 then lists both. The
  release-please entry is `release-please-config.json` → `packages/url4`. The squash commit is `feat(url4)!: run URI intents as RDS code-pointer calls`
  with a `BREAKING CHANGE:` footer; release-please writes the CHANGELOG entry. `[stated ans:Q5]`
- **Footer text (draft).** "A relative-URI or `url4://` intent is now an RDS code pointer: the node
  calls it once with the group's sources as a JSON input document, instead of fetching it as
  instruction text for the default processor. `https://` and other non-url4 intents now fail with
  `unsupported_mode`. Code-pointer query params follow `query-tail`, so `@` is allowed. See
  packages/url4/README.md, 'Migrating to 2.0'."
- **Migration note (draft for `packages/url4/README.md`).**
  1. If a URI intent held instruction text, write that text as a quoted intent (`!'…'`). This keeps
     the 1.5.1 fan-out path exactly.
  2. If the text must stay remote, bind it as a weight-`0.0` source and reference it in a quoted
     intent: `(member_1:…, instr:0.0:/instr)!'$instr'`. Note: a group that is not all calls takes
     the base merge (`process` hook), not the fan-out reduce.
  3. To run code, register the code at the path with `@node.endpoint` and read `request.inputs`
     and `request.params` when `request.mode == "rds"`.
  4. Replace `https://` intents with a url4 endpoint or a `url4://` reference.
- **Engine.** It uses url4 as an editable path dependency
  (`apps/screamingface-engine/pyproject.toml:111`), so it moves to 2.0 in the same merge. Its CI
  lane must stay green with no test edits (test-plan §3).
- **Linear.** No issue now. At PR time, after the user confirms, one issue goes under the url4
  grammar conformance epic **OME-500**, mirrored in `docs/tasks/`; the branch is renamed
  `OME-N-url4-rds-code-pointer`, and the PR body carries `Refs: OME-N`. `[stated prompt]`
