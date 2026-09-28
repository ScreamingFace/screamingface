---
id: OME-1276
linear_url: https://linear.app/openmined/issue/OME-1276/expose-a-native-iteration-index-in-url4
status: In Progress
type: feature
priority: 3
labels: [url4-sdk, agentic, design-session]
created: 2026-09-23
closed:
parent: OME-1281
---

# Expose a native iteration index in URL4

## Why

Iteration exposes the current value through `$item`, but expressions also need a stable position without altering collection data or inferring order from completion time.

**Classification: proposed language extension.** The cited spec defines `$item`, slicing and result ordering, but does not define a reserved iteration-index binding.

## Proposed behavior

Expose a zero-based index alongside `$item`; approved spelling: `$index`.

- Assign the index before scheduling. Completion order, retries and failures do not change it.
- Index the selected collection after `iteration.slice`: selecting `[10:13)` gives indices `0, 1, 2`.
- Make it available in body sources and intent. Nested iterations expose their own index; authors can capture the outer index in a named binding.
- Preserve `$item` and existing named bindings. Empty selections execute no bodies.

## Spec references and decisions

[Part B §5.3.4–5.3.6: item binding, nesting and slicing](https://github.com/OpenMined/screamingface-design/blob/12d1bbe37f45a9875627957686caeead8733937d/kevin-mcdonough/docs/adrs/URL4-Spec-B.md#L772-L925); [§5.3.8: collection result ordering](https://github.com/OpenMined/screamingface-design/blob/12d1bbe37f45a9875627957686caeead8733937d/kevin-mcdonough/docs/adrs/URL4-Spec-B.md#L955-L990).

Owner approved `$index` as reserved inside iterations, taking precedence over an author binding with that name. Outside iterations it remains an ordinary named reference. Post-slice numbering starts at zero. These are new SDK semantics, not pre-existing upstream spec requirements.

## Acceptance

Deterministic tests cover unsliced/sliced collections, concurrent completion, retries/failures, nested scopes, outer-index capture, empty collections and existing-name compatibility. Document the agreed binding in the language spec and implement it through the SDK’s iteration/reference machinery.

## Related work and scope

Coordinate nested scope tests with `OME-1280`. SDK feature only; no count variable, telemetry or application-specific behavior. Parent: `OME-1281`. Implementation follows an approved spec and plan.
