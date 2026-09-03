"""Download the pinned HealthBench Professional dataset and emit its runtime assets.

Think of this as printing the exam papers AND the answer key before exam day: the
question booklet (``cases.json``) goes where students can see it; the marking
scheme (``rubrics/``) stays locked in the teachers' room.

NOTE — this bakes ALL 525 rows, not just the 157-row worst-30% subset. The subset
is a serve-time SELECTION (``runtime._select_cases`` over ``WORST30_CASE_IDS``),
never a build-time fork, because:

1. Engine Case ids are positions in the FULL file — baking only the subset would
   force a renumbering layer, exactly the silent answer-key drift this build
   refuses to allow.
2. The assets cover every professional row, so the served exam stays a pure
   filter over one immutable answer key.
3. 525 conversations of JSON is cheap; a filter is simpler than a fork.

``WORST30_CASE_IDS`` appears here only in the drift assertion (see ``emit``).

Run at IMAGE BUILD time, never at run time: a Job's rootfs is read-only apart from
``/tmp`` and holds no HuggingFace credential, so every benchmark artifact must exist
before the Job starts.

    uv run python -m screamingface_engine.benchmarks.healthbench.prepare \
        --out /opt/benchmarks/healthbench

Emits::

    <out>/cases.json          [{"id": 1..525, "input": <chat envelope>}] — ALL a client sees
    <out>/rubrics/<id>.json   {"hf_id", "items": [{"rubric_id", "criterion", "points"}]}
                              — private, read by runtime.py and aggregate.py only

INVARIANT — ``cases.json`` carries NO rubric. The client receives Case ids and chat
envelopes while the rubric stays in the image, so a Candidate cannot be tuned against
the answer key through the Engine. (The dataset itself is public on HF — this boundary
keeps the ENGINE honest; it is not anti-cheat.)

INVARIANT — Engine Case ids are 1-based positions in the HF file's row order. This is
the exact rule ``subset.WORST30_CASE_IDS`` froze; the build ASSERTS the mapping and any
drift (HF re-ordering, a new dataset revision) fails the image build loudly instead of
silently shipping a different answer key. All points must be ints (the judge sees
``[7]``, never ``[7.0]``) and every row must carry a positive-points item (the score's
denominator).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError
from screamingface_engine.benchmarks.healthbench.definition import PROFESSIONAL_CASE_COUNT
from screamingface_engine.benchmarks.healthbench.pins import DATASET, DATASET_REVISION
from screamingface_engine.benchmarks.healthbench.subset import WORST30_CASE_IDS, WORST30_HF_IDS


class PrepareError(BenchmarkAssetPreparationError):
    """The dataset could not be turned into declared HealthBench assets."""


def load_rows() -> list[dict[str, Any]]:
    """Download the pinned dataset revision and return its rows in file order.

    Reference counterpart: the dataset load in ``HealthBenchEval.__init__``
    (https://github.com/openai/simple-evals/blob/main/healthbench_eval.py) —
    moved to image build time and pinned to one revision.

    ``datasets`` is NOT a dependency of screamingface-engine — this runs at image build time on a
    machine that has it (see the draco preparer for the importlib rationale).
    """

    try:
        datasets_mod = importlib.import_module("datasets")
    except ModuleNotFoundError as exc:
        raise PrepareError(
            "the `datasets` package is required to prepare a benchmark — "
            "`uv pip install datasets` in the build environment"
        ) from exc
    loaded = datasets_mod.load_dataset(DATASET, revision=DATASET_REVISION)
    rows: list[dict[str, Any]] = []
    for split in loaded:
        for row in loaded[split]:
            rows.append(dict(row))
    if not rows:
        raise PrepareError(f"{DATASET}@{DATASET_REVISION} produced no rows")
    return rows


def case_messages(row: dict[str, Any], case_id: int) -> list[dict[str, str]]:
    """Decode one row's native conversation turns."""

    conversation = row.get("conversation")
    if isinstance(conversation, str):
        try:
            conversation = json.loads(conversation)
        except ValueError as exc:
            raise PrepareError(f"case {case_id}: conversation is not JSON: {exc}") from None
    if not isinstance(conversation, dict) or not isinstance(conversation.get("messages"), list):
        raise PrepareError(f"case {case_id}: conversation must carry a messages list")
    messages: list[dict[str, str]] = []
    for index, message in enumerate(conversation["messages"]):
        if not isinstance(message, dict):
            raise PrepareError(f"case {case_id}: message {index} must be an object")
        role = message.get("role")
        content = message.get("content")
        if not isinstance(role, str) or not isinstance(content, str) or not content.strip():
            raise PrepareError(f"case {case_id}: message {index} must carry role and content")
        messages.append({"role": role, "content": content})
    if not messages:
        raise PrepareError(f"case {case_id}: conversation has no messages")
    return messages


def rubric_items(row: dict[str, Any], case_id: int) -> list[dict[str, Any]]:
    """Validate one row's flat rubric list under the build invariants above."""

    raw = row.get("rubric_items")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise PrepareError(f"case {case_id}: rubric_items is not JSON: {exc}") from None
    if not isinstance(raw, list) or not raw:
        raise PrepareError(f"case {case_id}: rubric_items must be a non-empty list")
    items = [_rubric_item(item, index, case_id) for index, item in enumerate(raw, start=1)]
    if not any(item["points"] > 0 for item in items):
        raise PrepareError(
            f"case {case_id}: no positive-points rubric item — the score denominator would be zero"
        )
    return items


def envelope(messages: list[dict[str, str]]) -> str:
    """The candidate-input envelope as PLAIN JSON — the data-file form.

    WHY not ``chat_input()``: that helper renders a url4 STRUCT for authoring inline
    expressions; a struct only becomes JSON when the expression resolves it. A value
    baked into ``cases.json`` is substituted into the Candidate call VERBATIM as data,
    so it must already be the JSON the Runner's envelope decoder ``json.loads``es.
    """

    return json.dumps(
        {"schema": CANDIDATE_INPUT_SCHEMA, "messages": messages},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _rubric_item(item: Any, index: int, case_id: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise PrepareError(f"case {case_id}: rubric item {index} must be an object")
    criterion = item.get("criterion_text")
    points = item.get("points")
    if not isinstance(criterion, str) or not criterion.strip():
        raise PrepareError(f"case {case_id}: rubric item {index} lacks criterion_text")
    if isinstance(points, bool) or not isinstance(points, int):
        # INVARIANT: ints only — the judge must see "[7]", never "[7.0]" (a float here
        # would silently change grader-prompt bytes for every future run).
        raise PrepareError(
            f"case {case_id}: rubric item {index} points must be an integer, got {points!r}"
        )
    return {"rubric_id": index, "criterion": criterion, "points": points}


def emit(rows: list[dict[str, Any]], out: Path) -> tuple[int, int]:
    """Write the public cases file and the private rubric assets — ALL rows.

    Every HF row becomes a Case and a rubric file; the worst-30% subset is not
    filtered here (it is a serve-time selection — see the module NOTE).

    Before writing anything, it proves the frozen subset still matches reality:
    ``subset.WORST30_CASE_IDS`` froze "the worst-30% rows sit at THESE 1-based
    positions in the HF file". If the dataset gained/lost/reordered rows since,
    position 42 is no longer the conversation the challenge means by Case 42 —
    so the build refuses to bake a silently different answer key.
    """

    # The professional board declares exactly this many Cases, so the file must hold
    # exactly this many rows. WHY its own check: the frozen-position assertion below only
    # proves the worst-30% rows did not MOVE — a row appended at the END passes it, and the
    # image would bake a 526-Case exam under a 525-Case identity.
    if len(rows) != PROFESSIONAL_CASE_COUNT:
        raise PrepareError(
            f"{DATASET}@{DATASET_REVISION} holds {len(rows)} rows, but the professional "
            f"board declares {PROFESSIONAL_CASE_COUNT} Cases; refusing to bake a "
            "differently-sized exam under that identity"
        )
    # Where does each frozen HF row id sit in TODAY'S file? (1-based position)
    positions = {
        hf_id: index for index, hf_id in enumerate((str(row.get("id")) for row in rows), start=1)
    }
    missing = [hf_id for hf_id in WORST30_HF_IDS if hf_id not in positions]
    if missing:
        raise PrepareError(
            f"{len(missing)} frozen worst-30% ids are absent from {DATASET}@"
            f"{DATASET_REVISION}: {missing[:3]}…"
        )
    # Today's positions must equal the frozen mapping exactly — else the dataset moved.
    frozen = tuple(positions[hf_id] for hf_id in WORST30_HF_IDS)
    if frozen != WORST30_CASE_IDS:
        raise PrepareError(
            "the HF row order no longer matches subset.WORST30_CASE_IDS — the dataset "
            "moved under the frozen mapping; refusing to bake a different answer key"
        )
    rubric_dir = out / "rubrics"
    rubric_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for case_id, row in enumerate(rows, start=1):
        cases.append({"id": case_id, "input": envelope(case_messages(row, case_id))})
        (rubric_dir / f"{case_id}.json").write_text(
            json.dumps(
                {"hf_id": str(row.get("id")), "items": rubric_items(row, case_id)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    (out / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(cases), len(WORST30_CASE_IDS)


def _prepare(out: Path) -> dict[str, Any]:
    emit(load_rows(), out)
    # INVARIANT: count what LANDED, not what was declared. `emit` already refuses any row
    # count but PROFESSIONAL_CASE_COUNT, so echoing its inputs would restate a constant the
    # build enforced rather than report this bake — a record that can never differ is not
    # evidence. Reading the written bundle back is the only observation available here.
    # WHY not also count `rubrics/`: `emit` writes one rubric per Case and never clears the
    # directory, so that count equals this one on a fresh bake and is inflated by leftovers on a
    # re-prepare — redundant when accurate, misleading when not. `cases.json` is rewritten whole,
    # so reading it back is both a count of THIS bake and proof the file landed intact.
    cases = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    return {
        "professional_cases": len(cases),
        # The worst-30% board is a serve-time SELECTION over frozen ids (see the module
        # docstring), never its own bake. Named `declared_` so an operator reading the build
        # log cannot mistake a compile-time constant for something this run produced.
        "declared_worst30_cases": len(WORST30_CASE_IDS),
        "out": str(out),
    }


def prepare(out: Path) -> dict[str, Any]:
    """Prepare the complete HealthBench assets shared by both registered boards."""

    return _prepare(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = _prepare(args.out)
    except PrepareError as exc:
        print(f"healthbench prepare failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"healthbench: baked {summary['professional_cases']} cases into {args.out} "
        f"— the professional board serves all {summary['professional_cases']}, "
        f"worst30 serves {summary['declared_worst30_cases']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())


__all__ = [
    "PrepareError",
    "case_messages",
    "emit",
    "envelope",
    "load_rows",
    "prepare",
    "rubric_items",
]
