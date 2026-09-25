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
- Same file, owner-requested extension after the PR #1064 review (2026-09-25) — three
  sibling gaps where the bake silently serves text inspect never sends:
  1. a `prompt_template` whose template is a file path → refuse by name (the bake would
     serve the path as every question; unresolvable prompt templates already refuse);
  2. two or more `system_message` solvers → flag, bind nothing (inspect sends all; the
     bake delivers one — today the last silently wins);
  3. the walk covers `Task(setup=...)` before `task.solver` (inspect always runs setup
     first; a system message there was never seen).
- `apps/screamingface-engine/tests/unit/inspect/test_inspect_importer.py` — new tests appended.
- `docs/tasks/2026-09-25-OME-1272-system-message-placeholder-guard.md` — mirror.

## Test plan

- params: `system_message(module.X, persona="tutor")` → flag naming the param, no fact.
- placeholder: module constant `"Answer as {persona}."` → flag, no fact.
- escaped brace: `"Reply in {{json}}."` → flag (str.format rewrites `{{` to `{`).
- file template: module constant holding a path to an existing file → flag, no fact.
- prompt_template pointing at an existing file → ImporterError naming the file read.
- two plain-constant system messages → no fact, flag names the count.
- system message in `setup=` with a placeholder → flagged; a plain constant there binds.
- every currently imported board introspects to identical facts before/after (probe).
- plain constant (hellaswag shape) keeps binding — covered by the existing
  `test_introspect_binds_a_module_level_system_message_as_a_fact`, left unmodified.

## Acceptance

1. Non-empty params flag; the bare template is never bound.
2. A template with `{placeholder}` syntax flags.
3. hellaswag's plain-constant path and every prior test stay green and unmodified.
4. The three review follow-ups each fail loudly (refuse or flag) instead of baking silently.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
