---
ticket: OME-934
stack: screamingface-engine
status: done
started: 2026-09-09
finished: 2026-09-09
---

# OME-934 — Forward structured Logs without disrupting execution

## Intent

Carry URL4 Log attributes through the Engine and ensure optional activity cannot displace otherwise admissible authoritative events. Implements the Engine portion of the approved September 9 spec/plan after PR 877 merged at cfd3eb38; user authorized implementation in this session.

## Planned changes

- apps/screamingface-engine/src/screamingface_engine/runner/executor.py: Log conversion and targeted soft/hard bridge admission.
- apps/screamingface-engine/tests/unit/test_structured_log_forwarding.py: real endpoint emission, sequencing, wire conversion and lifecycle compatibility.
- apps/screamingface-engine/tests/unit/test_structured_log_pressure.py: paired lifecycle sequences, exact loss counts and authoritative-only overflow.
- docs/tasks/2026-09-09-OME-934-log-seam.md: implementation delivery link/status.

## Test plan

Write new failing tests first for lost attributes and hard-cap-before-soft-cap Log pressure. Preserve all existing tests. Exercise soft/hard boundary combinations, eviction and incoming drops, original failure behavior, concurrent run attribution, live emission before completion, and serialized events decoded by the existing Client. Run the full Engine gate runner.

## Acceptance

Approved docs/spec/2026-09-09-OME-934-log-seam.md Engine requirements and plan steps 4–6 pass. No second event type/queue, producer schema, Client code change or scoring behavior. Draft PR only; no merge or ticket closure before delivery review.

## Outcome

- **Actual files:** one production module, two new test modules, issue mirror and this ledger, as planned.
- **Commits:** fix(engine): forward structured Logs with safe buffer admission; Refs: OME-934. Commit SHA is recorded with the draft PR.
- **Gates:** full `uv run .claude/scripts/run_gates.py screamingface-engine` green: append-only, Ruff lint/format, Pyright, layering and full pytest coverage gate. 2,682 tests collected; 93% aggregate coverage. All 27 added cases pass; no existing tests changed.
- **RED evidence:** attributes converted to empty mappings; hard-cap-before-soft-cap Logs raised BridgeOverflowError. A live streaming test was corrected to allow preceding node spans; it then failed on the intended lost-attributes assertion. New test sequence comparison uses the protocol's numeric string sequence. Client probe uses actual wire aliases.
- **Deviations:** none in production scope. A new Engine-side subprocess compatibility test imports the unchanged Client source and feeds real serialized lifecycle frames through its independent decoder. No SDK dependency or source change is needed.
- **Delivery:** implementation complete; issue remains open pending draft PR review/merge. No production model-activity producer or Client rendering is included.

## Wisdom and confidence review

The buffer is always at or below its hard cap before admission, so one eviction is sufficient to admit one incoming authoritative event. Applying the existing policy at the lower limit preserves soft-cap behavior and corrects inverted-cap behavior without another queue or event type. Attributes are copied into the existing LogData representation and old severity fallback remains intact. Paired synthetic and actual endpoint runs verify lifecycle outcomes and exact loss accounting. Existing Client decoding passes with node trace attachment and structured fields. Independent standards and spec reviews found no actionable issues. The implementation adds no domain schema, I/O, privacy policy, scoring logic or cross-package production dependency.
