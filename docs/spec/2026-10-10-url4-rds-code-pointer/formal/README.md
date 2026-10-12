# Formal model — url4 code-pointer intents

A small Lean 4 model (core Lean 4.34.1, no Mathlib) of the rules in
[../00-overview.md §2](../00-overview.md#2-the-design-in-five-rules). It states each rule
once and proves it. The Python tests check the implementation against the same
statements (test-plan §2).

```
cd formal && lake build      # builds every module and runs the axiom audit
```

`Url4Rds/Audit.lean` fails the build if a listed theorem uses `sorry` or any axiom
outside `propext`, `Classical.choice`, `Quot.sound`. It asks the kernel
(`collectAxioms`), so it also catches an unproved helper. I checked that it can fail:
a `theorem bogus : 1 = 2 := sorry` gives `bogus depends on axiom sorryAx`.

## Modules

| File | Models | Spec |
|---|---|---|
| `Intent.lean` | intent forms, the B §6 mode table, node profiles (`v1` = url4 2.0 with the owner decisions, `target` = full Spec B §6) | B §5.2, §6; A §1.4.1; C §13.5.2 |
| `Binding.lean` | sources → inputs (position, name, weight, value) | A §1.1; B §6.2, §5.3.10.3 |
| `Gate.lean` | required + quorum gate; call count for `!` and `!*` | C §12.2, §13.6; B §6.1.2 |
| `Expansion.lean` | `*source` / `;expand`, naming, counts | B §5.3.12 |
| `Status.lean` | our HTTP status choice against the C §13.2.1 inbound table | C §13.2.1, §13.5.2 |
| `Group.lean` | one group end to end: preflight → required → quorum → execute | C §13.6 |
| `Audit.lean` | `#assert_axioms` over every theorem below | — |

## Theorems

| Theorem | Says | Rule |
|---|---|---|
| `target_conformant` | the target profile gives every form an action its spec mode allows | R1 |
| `v1_not_conforms_iff` | url4 2.0 breaks Spec B §6 on absolute URIs (D2) only | R1 |
| `v1_act_eq_invokeLocal_iff` | only a relative URI or a named job runs code in 2.0, on this node (no foreign code ever runs) | R1 |
| `v1_act_eq_target_act` | wherever 2.0 conforms, it acts as the full Spec B profile | R1 |
| `v1_strictFields_iff` | in 2.0, field paths are strict only for code pointers and named jobs | C6 |
| `specMode_eq_rds_of_strictFields` | in any conformant profile, a strict scope is an RDS scope (LLM stays lenient) | C6 |
| `length_bind` | one input per resolved source | R3 |
| `find?_pos_bind` | the input at position `p` is exactly source `p`'s value; a failed source has none | R3 |
| `payload_bind_reweigh` | changing weights (to 0.0, or removing them) never changes what the code gets | R3 |
| `pairwise_pos_bind` | inputs are in source order | R3 |
| `gate_eq_false_of_required_failed` | quorum cannot override a failed required source | R2 |
| `gate_all_of_all_optional` | `quorum=all` with no required source always passes | R2 |
| `gate_mono` | more successes never close the gate | R2 |
| `calls_eq_nil_of_gate_false`, `calls_aggregate` | closed gate → no call; open → exactly one call with `bind S` | R2 |
| `length_calls_broadcast` | broadcast → one call per resolved source | R2 |
| `head?_inputs_of_mem_calls_broadcast` | each broadcast call starts with its own source (`$current`) | R2 |
| `length_inputs_of_mem_calls_broadcast` | with no `$`-reference in the pointer, each broadcast call has one input | R2 |
| `resolvedCount_expandWith_expand` | an expansion of `n` elements adds `n` to the quorum count | R2, R3 |
| `unnamed_expansions_collide` | two unnamed expansions give two inputs with the same name (spec gap Q4) | R3 |
| `cls_inbound_statusOf` | every code, including the class defaults for unlisted codes, keeps its class through C §13.2.1 | C8 |
| `inbound_statusOf` | every named code but `intent_error` keeps its exact code | C8 |
| `inbound_400_ne_unsupported_mode`, `cls_inbound_500_ne_cls_intentError` | why not 400 or 500 | C8 |
| `evalGroup_unsupported`, `evalGroup_unmounted` | a pointer the node cannot run, or a static pointer that is not mounted, fails its group and starts no source | R4 |
| `evalGroup_exec` | an open gate calls the executor with exactly `bind S` | R2, R3 |
| `evalGroup_ne_exec_of_gate_false` | a closed gate never reaches the executor | R2 |
| `exists_intentError_of_toOutcome_eq_failed` | every execution failure is `intent_error` (C §13.6) | R4, C8 |

`evalGroup_unsupported`, `evalGroup_unmounted` and `v1_strictFields_iff` are true by
definition (`rfl` / `decide`). They pin the definitions as the spec, so a change to the
definition breaks the build. They do not prove anything about the Python code.

## What the model does not cover

- The string-level B §5.2 detection (text → `IntentForm`). TDD row 1 tests it case by
  case against the ABNF, including the canonical-form traps.
- The cost claim on real I/O. In the model, "no source starts" is a `Bool` result, and
  `resolve` is not called on the failing branches by construction. TDD row 17 checks
  it with a spy IO.
- Composition of `expandAll` with `bind` and `gate`. The model expands first and binds
  the expanded list, so "positions and counts are post-expansion" (and "a failed
  expansion counts as one source for `majority`") hold by construction. No theorem
  states the composition.
- `$`-pointer groups: `evalGroup` models static pointers only. A `$` pointer is looked
  up at call time, after its sources resolve.
- Values: the model keeps `V` abstract. The C3 typing table is tested in Python.
- Weight splitting over expansions (`W / N`) and structured weights.
- Concurrency, cancellation and deadlines (the DAG executor's existing guarantees).

**Outside the ABNF.** url4 also accepts unquoted intent text that is not one `bare-value`
token (it has a space, a `%`, a comma, …). The implementation names it `IntentForm.PROSE`
and keeps it a prompt (LLM mode). It is not a Spec B form, so the model has no
`IntentForm` for it; it is a leniency, not a deviation.
