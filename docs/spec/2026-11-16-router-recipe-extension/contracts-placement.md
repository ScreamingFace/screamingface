# Contracts: Router outcome inside compositions and the url4 at-most-one source

Base `31c1158e8`. Path conventions, design citations and the strict-record rule are those of
[contracts.md](contracts.md).

## C18 — Router outcome by position (Unit 7)

The design admits a completed Router as a Gate branch, Pipeline stage, Fusion member or synthesizer
and Cascade stage under each position's existing rules (`engine/router-execution.md:203-217`). An
abstention is a non-answer for Fusion quorum, makes a Cascade Case abstain unless a
`sf.escalate_if(sf.unanswered())` line follows (`:105-110`), stops a Pipeline before downstream
stages, and stays the taken Gate branch's result without opening the other branch. A required Router
failure prevents synthesis (`:322-325`). JOIN's node value cannot carry this alone: it is `""` for
an abstention (C4), and every consumer below reads `""` as an answer today. Each consumer therefore
reads the Router's status from the C5 record JOIN published for its binding, the way a Gate's JOIN
reads its decision call (`_recorded`, `world/branch.py:800-808`), never from the text.

`R` below is the abstain reason of C13: `no_selection` when `outcome` is `no_selection`, else the
synthesis reason. Both are `AbstainReason` values after C10. A root Router, and a Router as the
final Pipeline stage, set the Case outcome through `final_operation_abstained` (C15).

### Gate branch

- Today `_call_result` (`world/branch.py:777-785`) gives the taken branch's result through
  `_terminal_answer` (`:741-752`) and `_no_branch` (`:755-766`). It reads only a nested Gate's
  `decision` and a combine's `combine` and calls every other call answered, so a Router branch that
  abstained is recorded as answered.
- Change: `_call_result` also reads `call.router`. Status `abstained` gives
  `GateResult(status="abstain", reason=R)`; `answered` gives answered. A failed Router raised in its
  JOIN, so the branch and the Gate fail. The other branch never opens.

### Pipeline stage before the last

- Today `_pipeline` (`_evaluation/candidate.py:1022-1045`) hands each stage's reference to the next
  one unconditionally, so a stage after an abstained Router runs on `""`.
- Change: the stages after a Router compile as the `then` recipe of an E4c panel Gate. Its decision
  call is that Router's JOIN, its condition is the one a Cascade line uses (`answered`,
  `_surface/lowering.py:301-305`), and its `otherwise` is a word body that makes no call.
  `_panel_reading` (`world/branch.py:639-643`) refuses an answered gate whose decision call has no
  `combine`; it also reads `call.router.status`. When the Router did not answer, `_panel_choice`
  (`:610-629`) wants no branch and `_joined` (`:707-728`) calls `_no_branch`, which copies the
  Router's result through `_call_result`: the later stages make zero calls and the Pipeline abstains
  with `R`. A failed Router fails its JOIN, on which the Gate and every later stage depend.
- The existing combine rule does not change: a combine abstention inside a Pipeline still hands `""`
  to the next stage (E4a AB-D2, `docs/spec/2026-10-02-e4a-gap-closure/prd/abstain.md:80-82`). The
  new rule applies to a Router stage only, because the design states it for Router.

### Fusion member and Cascade tier

- Today a Fusion whose members are all required under quorum `"all"` compiles without a panel
  (`_compile_fusion`, `_evaluation/candidate.py:492-508`), and its synthesis context lists every
  member's reference as `outputs` (`_fusion_context`, `:1157-1160`). The panel path (`:509-563`) and
  the skip-member panel (`_skip_panel`, `_evaluation/branch.py:314-356`) count every slot that
  resolved, `""` included (`_gather`, `packages/url4/src/url4/dag/nodes/_shared.py:214-238`). The
  skip-member `selection` (`combine/spec.py:685-704`) is read only by a reducer or writer, so it
  cannot serve a Model synthesizer.
- Change: a Fusion with a Router member always compiles through a panel. The Router member's slot
  keeps its `member_i` name, expands, and carries the at-most-one mark (C19); its value is the
  Engine's member read of that Router's binding. The read waits for the Router's JOIN and answers
  from the C5 record JOIN published for that binding, never from the text: a JSON array with no
  element when the status is `abstained`, and with the answer as its one element when it is
  `answered`. An abstention therefore contributes
  no source and no failure: url4 leaves it out of `quorum` and out of both panels, and no
  synthesizer reads it. An answer contributes `member_i: answer` like any member, `""` included. A
  failed Router failed its JOIN, so its read fails and the member's `required` or `optional`
  applies.
- Quorum stays the enclosing Fusion's. Under quorum `"all"`, one abstained Router ends in
  `quorum_not_met` with no synthesis call. Under a numeric quorum, the members that answered are
  synthesized when they meet it, else `quorum_not_met`. Under the skip-member floor an abstained
  Router counts as selected and unanswered (`_check_floor`, `combine/endpoint.py:1599-1612`).
  `required` and `optional` decide only what a Router failure does, unchanged: a required Router
  failure fails the Fusion.
- A Cascade tier needs no rule of its own. A bare Model or Router tier before
  `sf.escalate_if(sf.unanswered())` becomes `Fanout([value]) >> Vote()` with optional members and
  quorum 0 (`_surface/cascade.py:206`, `:209-210`, `:214-228`). An abstained or failed Router leaves
  the panel empty, the Vote abstains `no_votes` (`combine/endpoint.py:491-494`) and the answered
  gate runs the next tier. A bare tier before any other line is refused
  (`_surface/cascade.py:203-205`), and a Router as the last tier is a Gate branch.

### Budget

Under `sf.WithBudget`, the enclosing E4c decision treats one Router branch or tier as one optional
branch with its authored `sf.Estimate`; it never budget-gates the classifier, selected Models or
internal synthesizer separately (`engine/router-execution.md:111-117`). A branch refused before start
records `budget_refused` and makes zero classifier/model calls. Once started, the Router's actual
classifier, selected/default and synthesis charges reach later budget decisions; unknown classifier
cost counts as zero with the existing warning for the decision but stays unknown in Router evidence.
Pinned replay carries the captured classifier price through `cache.reference`, so live and replayed
budget decisions are equal. These are existing E4c budget rules, not a Router-specific budget policy.

### Fusion synthesizer

A Router synthesizer compiles through `_recipe_synthesizer` (`_evaluation/candidate.py:676-678`,
`:744`), so the Fusion's terminal call is the Router's JOIN and the Fusion ends as the Router ends.
This is the current synthesizer projection, with no new rule. The enclosing consumer reads that
JOIN: a root Fusion through `final_operation_abstained` (C15), a Gate branch through `_call_result`,
a Pipeline through the gate above, an outer Fusion through the member slot.

### Left to Unit 7, pinned here before code

The exact url4 text of the member read, its route and the marked member slot, and of the Pipeline
gate; how the IR lets a panel Gate name a Router as its decision call (a panel is a Fusion today,
`_surface/lowering.py:280-311`); and how the report shows that Gate. Each form is pinned with byte
tests of both panels. A form that cannot meet a rule above stops Unit 7, and the question goes to PR
#35 (overview §7).

## C19 — url4 at-most-one source (url4 leaf, before Unit 7)

C18 needs a Fusion member slot that contributes nothing, and no failure, when its Router abstained,
and contributes `member_i: answer` when it answered. No url4 form does both today:

- A plain source contributes one position, its `$name` binding and the packed entry `name: value`
  (`_gather`, `packages/url4/src/url4/dag/nodes/_shared.py:214-238`). It contributes nothing only by
  failing under `;optional`, which is a failure (`SourceFailure`,
  `packages/url4/src/url4/dag/node.py:60`).
- An `;expand` source contributes nothing for an empty collection, with no failure: an empty body is
  zero elements (`packages/url4/src/url4/dag/semantics/collection.py:57`). Its elements pack bare in
  the text panel, and its name binds the whole array (`_gather_expanded`,
  `packages/url4/src/url4/dag/nodes/_shared.py:241-251`). They are named `name[j]` in the broadcast
  collection (`packages/url4/src/url4/dag/nodes/broadcast_result.py:51`) and in a code binding,
  which divides the weight among them
  (`packages/url4/src/url4/dag/semantics/code_binding.py:72-94`).
  An answered member would lose its `member_i` label. Those are rules of the url4 language spec
  (§5.3.12.4-6).

The change defines one package extension through Spec B's existing extensible `exec-key=value` form;
it changes no grammar production. Its exact wire spelling is `expand.at_most_one=true`. It refines
the existing expansion and does not replace it: the marked source keeps `;expand`, and the mark bounds
that expansion to zero or one element and gives the one element its source's name. Spec C's unknown-key
fallback supplies old-reader degradation. This file pins the public extension behavior, wire and
compatibility Unit 7 relies on; renaming it after release would be a wire migration.

Form:

- The only accepted mark is exactly `expand.at_most_one=true`, appearing once. Another value or a
  duplicate is refused. It is an execution key, not a new flag or expression parameter.
- The mark is valid only on a named source with `;expand` and exactly one of `;required` or
  `;optional`, which the renderer writes with the `*` prefix
  (`packages/url4/src/url4/core/render.py:285`). A mark without `;expand`, with an `;expand` that
  carries a value (`;expand=false`; the grammar reads `;expand` by its key alone, so on an
  unmarked source it still expands, as before), without a guard, with both guards, with a guard
  that carries a value (`;optional=false`; the runtime reads a guard by its key alone), or on a
  source with no valid name (an identifier other than `src`, §4.3) is refused at parse, and
  `url4.src` and the renderer refuse the same forms
  (`packages/url4/src/url4/core/builders.py:142`). A tree built in code skips the parser, so one
  walk checks every source in it (`check_tree`,
  `packages/url4/src/url4/core/at_most_one.py:175-198`). An unnamed expansion calls its elements
  `src[i]` (`packages/url4/src/url4/dag/semantics/code_binding.py:72-94`), so an unnamed marked
  source would have no name to give its element.
- Some url4 stays raw text that a run parses later: an iteration's body, intent and reducer, a
  relative call's context, a Form-3 `processor=` expression and, on the text path, a deferred
  group. The entry check (`check_target`,
  `packages/url4/src/url4/dag/_at_most_one_texts.py:34-45`) parses each such text as the run will
  and adds its trees to the walk; a row's body and intent are read apart (`:120-128`), and a
  reducer's own `;` chain is checked for the mark before its source side (`:131-137`).
  `compile_expression` calls it before lowering (`packages/url4/src/url4/dag/_lowering.py:608-613`).
  `run` reads the run text and its processor with it before its run-start file phase, and never
  swallows its error (`packages/url4/src/url4/dag/_run_files.py:323-340`); a Form-3 processor is
  read this way before the resolve-time grammar reads it, so one too deep to read is refused, not
  a crash (`_processor_scan`, `:216-227`). `run(tree)` and `run(text)` thus enforce the C19
  marked-source and reserved-param constraints in every text they parse, before any fetch or
  call.
- Among one group's members a C19 error outranks any other, at every depth, so a member that
  breaks another rule never hides it (`checked_members`,
  `packages/url4/src/url4/core/at_most_one.py:124-149`); without one the first error is raised, as
  before. A member that breaks another rule in its own chain or intent is not read further: the
  check is not a full validator, and any other parse error keeps its base behavior. A text too
  deep for the eager parser cannot be read: one that names the mark is refused, FAIL CLOSED, a
  well-formed mark included (`refuse_too_deep`, `:152-172`), as the remote-call precheck refuses
  such a text (`packages/url4/src/url4/dag/_remote_walk.py:229-234`); any other keeps its base
  behavior. The public eager readers refuse it the same way: `parse`, `parse_value`, `build` and
  `classify_intent`, and so the client front door, which builds the text itself for a node target
  or protocol params, each call `refuse_too_deep` in an `except RecursionError` of its own frame
  and re-raise. So does every other reader of a text given as an intent: the builders' intent and
  reducer (`_rewrite_reducer_iteration` and `_intent_node`,
  `packages/url4/src/url4/core/builders.py:286-294`, `:320-338`), and so the client helpers that
  build through them; `is_named_job` (`packages/url4/src/url4/core/intent.py:195-204`), for a
  named job `render` checks and a code name `Url4Node.code` mounts; and `render` reading a
  structured intent back (`_render_intent`, `packages/url4/src/url4/core/render.py:229-233`).
  The parser re-enters none of them while it reads, so the refusal runs once the stack has
  unwound and adds no frame to a read: an unmarked text near the limit reads as deep as at base,
  and every internal reader keeps its base behavior.
- An intent is natural language first: one that only looks like url4 and fails to parse stays
  prose, and a `/` intent that fails stays a code pointer. One that fails on a C19 rule parsed
  as url4 up to a broken mark, so it is refused, never read as prose, a code pointer or a
  reference: the grammar's intent fallbacks and the intent classifier re-raise it
  (`raise_if_c19`, `packages/url4/src/url4/core/at_most_one.py:58-67`; `classify_intent`,
  `packages/url4/src/url4/core/intent.py:110-133`). A malformed mark in a group's, a row's or a
  Form-3 processor's intent thus never reaches a model as a prompt.
- A relative call's context that fails on a C19 rule is refused, never read as prose; a context
  with a segment that is not a source for another reason stays prose and ships verbatim, the mark
  in it included (`read_source_list`, `packages/url4/src/url4/dag/_at_most_one_texts.py:48-75`).
  The entry check reads each segment as lowering does (`_slot_from_text`,
  `packages/url4/src/url4/dag/_lowering.py:381`): a group the text path defers is a source
  whatever its sources hold, read here for a C19 error only (`_context_member`,
  `packages/url4/src/url4/dag/_at_most_one_texts.py:105-117`); any other error in it is met when
  it runs, as before. Whether a context holds a holdings ref is read with no C19 refusal
  (`holds_holdings_ref`, `packages/url4/src/url4/dag/source_scan.py:258-281`): it is a question
  about the context's structure, so an `@` in quoted text or a URL never makes a context with a
  broken mark the receiver's. That reading parses each segment in order, so a segment too deep
  for it is refused when the context names the mark, FAIL CLOSED, unless a holdings ref comes
  first (`_receiver_owned`, `packages/url4/src/url4/dag/_at_most_one_texts.py:78-91`); any
  other keeps its base error. A node answers each such refusal with HTTP 400, where a deep text
  once escaped as an HTTP 500.
  Three contexts are the receiver's to parse, and the caller forwards each byte for byte: a remote
  call's (C6; the caller never lowers it, `packages/url4/src/url4/dag/_lowering.py:189-204`), a
  relative reducer's (it ships to its route with the rows as the intent,
  `packages/url4/src/url4/dag/nodes/reduce.py:44-51`) and one that holds a holdings ref (spec
  §5.6.3.1/.2). A receiving node of this version refuses a malformed mark at its own entry; an
  older one ignores the key (Spec C §10.2), and readers-first rollout keeps a writer from sending
  the mark to one. Only a relative call's own context, in its sugar or its canonical relative
  form, is resolved caller-side (`packages/url4/tests/spec/test_abnf_call_context.py`).
- The C19 entry guarantee covers public text and core parse-tree inputs. A custom lowering
  registry is trusted executable code and a pre-built `Graph` or `DagNode` a trusted internal
  representation: neither is scanned for C19.
- The mark is a generic execution key, outside the closed `coord.` set, so every reader at or after
  `455166b0d` accepts it (`validate_exec_annotations`,
  `packages/url4/src/url4/core/_annotations.py:143-159`). It joins neither the §8.1.3 exclusive key
  set nor its prefixes, so every reader splits a `;` chain at the same key (`classify_boundary`,
  `:238-252`).
- The mark is never an expression parameter. The param validator (`validate_param`,
  `packages/url4/src/url4/core/_annotations.py:180-183`) refuses it, and every reader of expression
  params shares that validator: the `;` chain, a group or iteration envelope, the canonical call
  form `/p?k=v&q=(a)!'i'`, both render paths (with `check=False` too) and a node's HTTP query. A
  node thus refuses over HTTP what it refuses in text (`OME-507`), with HTTP 400 like any other
  invalid param. Two readers skip that validator and refuse the mark themselves
  (`refuse_mark_as_param`): the inner tail of a reduce over iteration, which keeps only its
  `iteration.*` directives (`packages/url4/src/url4/core/_iteration_envelope.py:64-66`), and the
  tree walk above, for the params of every expression, relative call and remote call in a tree, an
  inline collection's included.
- On an expression-valued source the mark follows a source-level key: a sugar-form chain that puts
  the mark before every source-level key, or carries none, would make it an expression parameter,
  and is refused. The builder and renderer path matches it: `url4.src` writes `;required` or
  `;optional` before extension keys and the mark right after that guard (`exec_annotations`,
  `packages/url4/src/url4/core/_builder_exec.py:31-34`;
  `packages/url4/src/url4/core/builders.py:178-180`; `with_mark`,
  `packages/url4/src/url4/core/at_most_one.py:84-94`), an SDK member slot always carries one of them
  (`_evaluation/candidate.py:523-531`), and the renderer already refuses any other order
  (`_guard_annotation_boundary`, `packages/url4/src/url4/core/render.py:307-323`).

New reader:

- The marked source's value is parsed as a collection, as `;expand` parses it: an empty body is zero
  elements, and a JSON string element is its raw text
  (`packages/url4/src/url4/dag/semantics/collection.py:377`).
- Zero elements: no position, no `$name` binding, no text-panel entry and no broadcast part.
  `quorum` does not count it in either panel (`_check_quorum`,
  `packages/url4/src/url4/dag/nodes/_shared.py:254-258`; the broadcast gate,
  `packages/url4/src/url4/dag/_wiring.py:218`). It is not a failure: nothing is recorded as one, and
  `;optional` and `;required` do not apply.
- One element: exactly what a plain source holding that element contributes, in every consumer that
  names expansion elements. One position, `$name` bound to the raw element, `name: element` in the
  text panel, `source_name: name` (never `name[0]`) in the broadcast collection, `name` in a code
  binding, and the declared weight undivided.
- Two or more elements fail the source with `x.expansion_too_many`, a new
  `ErrorCode.EXPANSION_TOO_MANY` raised as a `CollectionError` (`at_most_one_payload`,
  `packages/url4/src/url4/dag/nodes/_at_most_one.py:22-26`, which `ExpandNode` calls), as
  `expansion_not_iterable` is (`packages/url4/src/url4/dag/nodes/iteration.py:49-56`). It is
  permanent, the `Url4Error` default (`packages/url4/src/url4/core/errors.py:117`): the same value
  always holds the same count. A node therefore answers it with HTTP 422 (`status_for_code`,
  `packages/url4/src/url4/peer/_http.py:125-141`). The `x.` prefix marks a package code outside the
  language spec, as `x.attachments_too_many` does (`packages/url4/src/url4/core/errors.py:97`). A
  value that is not a collection keeps the expansion's own failure, `expansion_not_iterable`
  (`packages/url4/src/url4/dag/nodes/iteration.py:49-56`). The guard wraps the expansion
  (`packages/url4/src/url4/dag/_descriptor.py:54-64`), so `;required` and `;optional` apply to
  either failure as to any other.
- Unmarked and `;expand` sources keep their behavior and rendered bytes, and every prior url4 test
  runs unchanged. Exception for text beyond the eager parser's recursion depth: if the unreadable
  text contains the literal reserved-key substring `expand.at_most_one`, the reader refuses it
  fail-closed even when a successful parse might have classified that occurrence as quoted text or
  prose. Text without that substring keeps its base behavior: a `RecursionError` where base raised
  one, a lazy compile where base compiled lazily.
- `url4.src` gains one keyword, `at_most_one: bool = False`
  (`packages/url4/src/url4/core/builders.py:142-196`). `src(value, name=..., required=...,
  expand=True, at_most_one=True)` writes `expand.at_most_one=true` right after `;required` or
  `;optional`, whichever argument gave the guard (`with_mark`,
  `packages/url4/src/url4/core/at_most_one.py:84-94`), and the renderer writes it. `src` applies the
  form rules above to its final annotations whatever their origin and refuses a broken form with
  `ValueError`, as it refuses a bad name or weight. The same mark passed through `annotations=` is
  checked the same way, and the keyword plus that annotation is a duplicate. The SDK writes the mark
  through the builders it uses today (`_evaluation/candidate.py:14`, `:523-531`).

Older reader. url4 Spec C §10.2.1 tells a node to ignore an unknown annotation key silently
(`kevin-mcdonough/docs/adrs/URL4-Spec-C.md:108-125` in the design repo at `3e903bd`). The reader at
`455166b0d` keeps the mark and lowers the source by its expansion alone
(`packages/url4/src/url4/core/grammar.py:230-260`,
`packages/url4/src/url4/dag/_descriptor.py:33-60`,
`packages/url4/src/url4/dag/attachment_sources.py:66-77`). Because the mark rides on `;expand`, that
reader loses the label and the bound, never the absence:

- Zero elements: no source. `quorum` counts one source fewer, and the SDK writes quorum `"all"` as
  the member count (`_evaluation/candidate.py:534`), so an abstained Router is never read as an
  answer and no synthesis reads it.
- One element: one source, packed bare in the text panel and named `name[0]` in the broadcast
  collection; `$name` binds the one-element array.
- Two or more elements: as many sources, with no failure.
- A raw chain with the mark before every source-level key: the mark becomes an expression parameter,
  and the expansion still applies.

A mark without `;expand` would give that reader one source holding `[]`, packed as `name: []` and
counted by `quorum`: an abstention read as an answer. That is why the mark requires `;expand`. The
exact label and the bound hold only on the new reader, and an older worker also lacks the C18 member
read, so Router work still depends on C12: the SDK writes the mark only after `router-placement-v1`.

Readers first:

1. The url4 leaf lands the package extension contract, parser validation, lowering, both panels, code
   binding, builder and renderer, and ships on the url4 release lane. On an expression-valued source,
   its canonical form places `expand.at_most_one=true` after `;required` or `;optional`, so old and new
   readers choose the same source boundary.
2. The Engine reads the in-repo url4 (`apps/screamingface-engine/pyproject.toml:142`), and the SDK
   wheel vendors url4 from the same tree at build time
   (`packages/screamingface/scripts/runtime_build_hook.py:36-44`), so an Engine bundled with an SDK
   reads what that SDK writes.
3. An Engine advertises `router-placement-v1` only under the C12 fleet rules: every worker that
   can take a current or queued run has this reader and C18. The SDK writes the mark, or any Router
   below the Recipe root, only after that check.
