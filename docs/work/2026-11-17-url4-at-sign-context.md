---
ticket: OME-1945
stack: python
status: done
started: 2026-11-17
finished: 2026-11-17
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

- **Actual files:** as planned — `packages/url4/src/url4/dag/_lowering.py` (import +
  predicate swap in `_context_slots`), `packages/url4/tests/unit/test_context_holdings_scan.py`
  (+3 tests: `test_an_at_sign_url_context_reaches_the_model_like_the_same_url_without_it`,
  `test_a_real_holdings_ref_context_still_reaches_the_route_verbatim[@|@emily]`).
- **Commits:** 967083da9 — fix(url4): lower an attachment URL containing "@" like any source
- **Gates:** url4: ruff check pass, ruff format --check pass (314 files), pyright 0 errors,
  pytest 3315 passed / 17 xfailed (no xdist in url4, run serially). Engine
  `-n auto -k "attach or holdings or fetch_bytes"`: 104 passed, 132 skipped.
  RED: the new @-URL test failed before the fix (context was the raw
  `src=…;accept=image/png`; the plain URL gives the bare URL).
- **Deviations:** none. The holdings-ref verbatim test passed before and after (it pins the
  invariant; it is not a RED test).
