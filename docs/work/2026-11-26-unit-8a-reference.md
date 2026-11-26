---
ticket: OME-2046
stack: repo
status: in_progress
started: 2026-11-26
finished:
---

# Unit 8A — Isolated fixed-label reference

## Intent

Implement the model-free reference boundary in the approved Unit 8A C7 fragment, on
`99072d273706f5ac673d49f5cd605a763e66c220`. Accept only verified offline artifacts and inject the
tokenizer and head through narrow ports. Production artifact provisioning is separate.

## Planned changes

- Standalone package, lock, build, usage and descriptor under `e2e/reference/bert-classifier/`.
- Closed artifact reader, immutable verified bytes, classifier and loopback HTTP adapter.
- Model-free tests and fixtures in that same project. No cross-project dependency in its lock.

## Test plan

- Start with the normative fake manifest, native media/refusal and 511/512/513-token cases RED.
- Verify the digest, schema, file and snapshot boundaries with independent negative controls;
  prove exact text, full stable softmax, request precedence and network/logging isolation.
- Run the frozen offline project test, lint, typing and build gates; inspect the built archive.
  Record actual environments and distinguish synthetic tests from composed product proof.

## Acceptance

- No file is loaded for an invalid artifact set. A valid loader sees only verified bytes.
- The loopback server implements the pinned HTTP contract with no weights and no product changes.

## Outcome

- **Actual files:** New isolated `e2e/reference/bert-classifier/` project and this ledger. The
  package has one HTTP runtime dependency (`uvicorn==0.54.0`, with `h11==0.16.0` from the lock).
  The verifier opens directory-relative files without following symlinks and passes the loader
  the read-only map of bytes it verified. The real model loader remains a provisioning concern.
- **Commits:** None; the candidate is ready for independent review.
- **Gates:** 81 tests failed against the initial stubs. The final 82 tests, lock check, Ruff lint
  and format, Pyright (package source), and wheel/sdist builds passed offline on Linux x86_64 /
  Python 3.12.16. Inspected both archive inventories. Repository gates passed on macOS and Linux; scalar
  composition passed over loopback under macOS Python 3.12.9 with independent frozen product
  environments. Gateway statuses and send counts were `(200, 1)`, `(400, 0)`, `(404, 0)`,
  `(400, 0)`, and `(502, 1)` for success, denied grant, missing synthetic authorization,
  character limit, and token limit. Four in-memory negative controls failed their targeted tests
  as expected; the candidate files were unchanged by those controls.
- **Deviations:** The composition harness replaces account storage and credential resolution at
  test seams; it does not create Connections. Qualification of a production backend, a complete
  real artifact manifest and model behavior remains separate from these model-free checks.

### Regression coverage follow-up

- Appended seven cases in `tests/test_manifest.py` and `tests/test_http.py`. Wrong model and
  revision use freshly pinned manifests over a complete valid tree. The 128/129-character
  basename cases rename the real fixture file and preserve its digest and order. Numeric-string,
  null and negative-infinite logits all return `classifier_failed`.
- The three in-memory review controls now fail the intended cases: skipped identity comparisons
  (2 failures), unbounded basename length (1 failure), and float coercion (1 failure). All 82
  earlier cases and the package source were preserved. Final offline suite: 89 passed on Linux
  x86_64 / CPython 3.12.16 and macOS / CPython 3.12.9. Ruff, Pyright, isolated build, archive
  inspection, repository gates and the separate scalar composition witness passed.
