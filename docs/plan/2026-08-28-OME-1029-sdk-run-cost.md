# OME-1029 — Implementation plan

**Spec:** `docs/spec/2026-08-28-OME-1029-sdk-run-cost.md`
· **Ledger:** `docs/work/2026-08-28-OME-1029-sdk-run-cost.md`
· **Branch:** `OME-1029-sdk-run-cost` · **Stack:** screamingface

Gates: `uv run .claude/scripts/run_gates.py screamingface --base origin/main`
→ append-only · ruff check · ruff format · pyright · pytest --cov=screamingface **--cov-fail-under=95**
· notebook determinism · `uv build` · distribution check

Note the 95% floor and the notebook check — this stack is stricter than scoreboard's.

## Ordering principle

The absent/zero distinction is the whole risk. A null read as zero would place an unpriced run at
the cheapest end of the Pareto frontier `OME-923` is about to build, so that boundary is pinned
first and separately from the happy path.

---

### Step 1 — the three cost states

**RED:**
- a priced run puts a decimal **string** in the payload, not a float and not a `Decimal`;
- an unpriced run (`cost_usd is None`) puts `None` — asserted as `is None`, never `== 0`;
- a run costing exactly nothing puts `"0"`, and that is distinguishable from the unpriced case.

**GREEN:** `_cost_text()` helper plus one key in `_submission()`.

**Why a string is asserted, not just "truthy":** the payload goes to `json=`, which raises on a
`Decimal`, and a `float` silently loses precision on money. Both failures are invisible to a test
that only checks the value is present.

---

### Step 2 — the payload is otherwise untouched

**RED:** the full key set of `_submission()` gains exactly `run_cost_usd` and nothing else; every
existing field keeps its value.

**Why:** this is a submission path every user depends on. A characterisation test makes an
accidental change to a neighbouring field fail loudly rather than ship.

---

### Step 3 — both submit paths

**RED:** the async submit sends the field too.

**GREEN:** nothing — both call `_submission()`. The test exists to keep that true, since a future
divergence between sync and async would be silent.

---

### Step 4 — round-trip against Scoreboard's schema

**RED:** the emitted payload validates as a `ScoreSubmission` and yields the expected `Decimal`,
including `"0"` → `Decimal("0")` and `None` → `None`.

**Why:** the SDK and Scoreboard are separate packages with no shared type. A string the SDK is
happy with but Pydantic rejects would only surface at runtime, against a live board.

---

### Step 5 — close out

Ledger Outcome · conventional commits, `Refs: OME-1029` · PR · green CI · squash-merge · close
comment · close the `docs/tasks/` mirror.

**Reviewers differ from recent work:** CODEOWNERS puts `/packages/screamingface/` on
`@IonesioJunior` and `@keelancj`, not `@HupBaHa`.

## Risks

| Risk | Handling |
|---|---|
| `null` coerced to `0` somewhere downstream | Step 1 asserts `is None`, and Step 4 round-trips it through the real schema |
| Precision lost via `float` | Step 1 asserts the wire type is a string |
| Breaking an existing submission path | Step 2's characterisation test |
| Coverage floor is 95%, not 80% | Small change, but the new helper needs all three branches covered |

## Out of scope

`duration_ms` / run timing · making cost required (`OME-822`) · the Pareto marks (`OME-923`) ·
any Scoreboard change.
