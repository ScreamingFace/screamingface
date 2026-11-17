---
ticket: OME-1945
stack: python
status: in_progress
started: 2026-11-17
finished:
---

# url4-at-sign-context — lower an attachment URL containing "@" like any source

## Intent

`_lowering._context_slots` skipped slot lowering whenever a call's context contained `@` as a
plain substring, so a jsDelivr-style attachment URL (`…/repo@<sha>/file.jpg`) made the model
receive the raw `src=…;accept=…` text as its context, while the run-start scan
(`source_scan.holds_holdings_ref`, parsed-AST test) still fetched and attached the file. Lowering
and the scan must agree: reuse the scan's predicate so an `@` inside a URL lowers like any source,
while a genuine holdings ref (`@` / `@name`, spec §5.6.3.1/.2) still travels verbatim.

## Planned changes

- `packages/url4/src/url4/dag/_lowering.py` — `_context_slots` uses `holds_holdings_ref`
  instead of `"@" in context`.
- `packages/url4/tests/unit/test_context_holdings_scan.py` — RED tests on `request.context`.

## Test plan

- An `@`-bearing src= URL yields the same `request.context` as the same source without `@`
  (no `src=` / `;accept=` syntax reaches the model).
- A real holdings ref (`@`, `@emily`) in the context still reaches the route verbatim.

## Acceptance

- New tests pass; url4 gates (ruff, format, pyright, pytest) and engine attachment tests green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
