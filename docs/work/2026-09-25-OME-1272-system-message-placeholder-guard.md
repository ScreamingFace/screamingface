---
ticket: OME-1272
stack: screamingface-engine
status: in_progress
started: 2026-09-25
finished:
---

# OME-1272 — flag a system message whose text the eval rewrites at run time

## Intent

The importer binds an eval's module-level `system_message` template as a fact, and the bake
delivers that constant's text verbatim as leading input (OME-1253). inspect's
`system_message(template, **params)` does not send the template verbatim: it reads the
template through `resource()` (a path or URL becomes the file's contents) and runs
`str.format` over it with the params plus sample metadata and store. Any of those three turns
the baked text into a different exam with every guard green. Close the hole at introspection
time: when the delivered text could differ from the constant's text, flag the solver for
review by name and bind no fact.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py` — in
  `_solver_facts`' system_message branch, a new helper names why the constant's text would not
  be what inspect sends (extra params · braces in the text · template read from a file); when
  it names a reason, record the review flag and leave `system_message_ref` None.
- `apps/screamingface-engine/tests/unit/inspect/test_inspect_importer.py` — new tests appended.
- `docs/tasks/2026-09-25-OME-1272-system-message-placeholder-guard.md` — mirror.

## Test plan

- params: `system_message(module.X, persona="tutor")` → flag naming the param, no fact.
- placeholder: module constant `"Answer as {persona}."` → flag, no fact.
- escaped brace: `"Reply in {{json}}."` → flag (str.format rewrites `{{` to `{`).
- file template: module constant holding a path to an existing file → flag, no fact.
- plain constant (hellaswag shape) keeps binding — covered by the existing
  `test_introspect_binds_a_module_level_system_message_as_a_fact`, left unmodified.

## Acceptance

1. Non-empty params flag; the bare template is never bound.
2. A template with `{placeholder}` syntax flags.
3. hellaswag's plain-constant path and every prior test stay green and unmodified.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
