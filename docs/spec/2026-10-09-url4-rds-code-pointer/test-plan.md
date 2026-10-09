# Test plan — url4 RDS code pointer (url4 2.0.0)

The rows live in [prd/rds-code-pointer.md §7](prd/rds-code-pointer.md#7-tdd-plan-red--green--refactor)
(CH1–CH11, rows 1–29). This file says where rigor goes, how the rows run, and what must stay
green outside url4.

## 1. Strategy

The change alters **what an expression means**, not only how it runs. The expensive mistakes are a
silent change of meaning, a lost byte, and a code that callers retry when they should not. Most
rigor goes there.

| Risk | Impact × Likelihood | Rigor | Rows |
|---|---|---|---|
| A URI intent still reaches a model (old path not fully closed: fan-out, base, broadcast, iteration reducer) | H×H | one row per group site; assert no processor fetch and no `process` call | 9, 12, 14, 20, 21, 22 |
| An input loses or changes bytes (escaping, JSON typing, transport) | H×H | seeded random corpus through both transports; strings by default | 6, 7, 8, 24, 29 |
| The classifier takes an expression for a code pointer, or the reverse | H×H | one case per ABNF production in the §2.5 table, with the `RelUrl`/`Url` traps | 1 |
| U3a widens the protocol-param rule by accident | H×M | separate rows for the code-pointer reader and the protocol reader | 4, 5, 27, CH7 |
| An LLM call is read as RDS at dispatch | H×M | the marker needs two conditions; every LLM call shape asserts `mode="llm"` | 10, 11 |
| Weight-0.0 behavior regresses in LLM mode | H×M | CHAR pins kept | CH2, CH3, 13 |
| A remote `intent_error` is retried as transient | M×M | Should row against a real ASGI peer | 26 |
| Quorum or optional handling calls the code with the wrong set | H×M | absent, not-met and vacuous cases | 15, 16 |

Levels follow the pyramid: unit rows for the classifier, the param reader and the codec (most
rows); integration rows for each group site and each transport; one e2e row (29) for the spine.

## 2. Ground rules

- **RED first:** run the new test and see it fail on the missing behavior (an assertion), not on an
  import error. A test that passes at once proves nothing.
- **GREEN minimally; REFACTOR on green only.** One behavior per test. The name states the behavior,
  for example `test_uri_intent_calls_code_pointer_once_with_named_inputs`.
- **CHAR first.** Write CH11 (the 1.5.1 probe table) before any delta row, and run it green on
  today's code.
- **Flips.** CH8, CH9 and CH10 pin behavior that 2.0 removes
  (`T/unit/test_dag.py:440-469`, `T/unit/test_dag.py:472-483`,
  `T/unit/test_characterization.py:53-61`). They change in the same commit as rows 3 and 9, and
  the PR body lists them. All other existing url4 tests stay as they are. `[stated ans:Q5]`
- **No hypothesis dependency.** Corpus rows use a seeded `random.Random`, as
  `T/unit/test_characterization.py` already does. `[existing T/unit/test_characterization.py:177-192]`
- New spec-level tests go in `T/spec/test_rds_code_pointer.py` (group path),
  `T/spec/test_rds_code_pointer_sites.py` (broadcast, reducer) and
  `T/spec/test_rds_code_pointer_http.py` (HTTP, E2E); codec and reader unit tests go in
  `T/unit/test_rds_document.py` and `T/spec/test_param_conformance.py` (append). `[proposed]`

## 3. Lanes

| Lane | Runs | Command (from `packages/url4`) |
|---|---|---|
| url4 unit + spec | every row except 24, 26, 29 | `uv run pytest tests/unit tests/spec` |
| url4 HTTP | rows 24, 26 (ASGI app + httpx ASGI transport; no network) | `uv run pytest tests/spec/test_rds_code_pointer_http.py tests/unit/test_http_remote_errors.py -k "http or remote"` |
| url4 e2e | row 29 (the E4a 3-model vote url4 against a stub combine) | `uv run pytest tests/spec/test_rds_code_pointer_http.py -k e4a_vote` |
| url4 gates | lint, types, coverage | the package's existing CI job (`url4-tests.yml`) |
| Engine regression | the Engine suite against the new url4 (editable path dependency, `apps/screamingface-engine/pyproject.toml:111`) | the Engine's existing CI job |
| SDK regression | the `packages/screamingface` suite (it imports url4, `packages/screamingface/src/screamingface/url4.py:10`) | the SDK's existing CI job |

The Engine and SDK lanes must stay green with **no** test edits: the search in the overview §8
found no live URI intent in their code. A red Engine or SDK test is a finding, not a test to
update.

## 4. Coverage map (scenario → row)

| Scenario | Rows |
|---|---|
| H1 | 12 |
| H2 | 8, 24 |
| H3 | 13 |
| H4 | 4, 24 |
| H5 | 14 |
| H6 | CH1 |
| H7 | CH4 |
| H8 | 23 |
| E1, E2 | 17 |
| E3 | 18 |
| E4 | 19 |
| E5 | 16 |
| E6 | 15 |
| E7 | 3 |
| E8 | 2, 4 |
| E9 | 5, 27, CH7 |
| E10 | 26 |
| D1, D9 | 15 |
| D2 | CH3, 13 |
| D3, D6 | 6 |
| D4, D5 | 7 |
| D7 | 20 |
| D8 | 21, CH6 |
| D10 | 22 |
| D11 | 25 |
| D12 | 6 (one case) |
| observability (§4) | 28 |

## 5. Release checks (not tests; the PR checklist)

- The squash commit is `feat(url4)!: run URI intents as RDS code-pointer calls` with a
  `BREAKING CHANGE:` footer. Release-please then proposes 2.0.0 and writes the CHANGELOG
  (`release-please-config.json` → `packages/url4`; `.release-please-manifest.json` holds 1.5.1).
  Do not hand-edit `packages/url4/CHANGELOG.md`. `[stated ans:Q5]`, `[implied]`
- The migration note is in `packages/url4/README.md` ("Migrating to 2.0"), and the footer text
  points to it. `[proposed]`
- `docs/spec/2026-07-11-url4-package-v1-spec.md` §group shapes (the `FanoutReduceNode` and
  `BarrierNode` rows) gets a 2.0 note. `[proposed]`
