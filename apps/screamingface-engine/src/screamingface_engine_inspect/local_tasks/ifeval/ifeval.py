# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (inspect_ai, datasets),
# absent in the default (extra-less) install the typecheck gate runs against; it is loaded only
# behind `inspect_available()`, like every other module in this package.
"""IFEval as a LOCAL inspect Task — the hand-built folder in inspect's shape (OME-1527).

Think of it as the same exam, now printed by the shared press: a dataset loader that prints the
question booklet (541 prompts, each carrying the instructions a reply must follow, kept
private), a scorer that runs the vendored official checker over one reply, a tally sheet that
pools the run's instructions the way the paper does, and one `@task` that binds them.

Execution order, as the importer and the Engine see it:

    1. `ifeval()` → `load_ifeval()`: load `google/IFEval` at the pinned revision (the importer
       forces it at every build), check every row against the official file vendored beside
       the checker, and take the official text where the two differ (row key 2785 only; any
       other difference refuses the build). Each row becomes a Sample whose `input` is the
       prompt, byte for byte, and whose metadata carries the instruction ids and their
       arguments (private Grading Material). Case ids are positions, 1..541.
    2. the importer replays that twice in a clean child and seals the Cases by digest; at
       build, prepare replays it once more (and downloads nltk's punkt tokenizers into the
       bundle, since the grading job has no network) and serves nothing unless the digest
       matches.
    3. at grading, `instruction_following` runs the checker strict and loose over the reply
       and returns the paper's four numbers for the Case as one dict Score, headline first;
       its metadata carries each instruction's verdicts and, for the Corrective Loop, the
       Draft Feedback the hand-built route sent (the fraction met, the checker's own words).
    4. after the last Case, the row's whole-run metric `ifeval_accuracy` pools the run's
       instructions and returns the published numbers under the hand-built Benchmark's keys.

INVARIANT — instruction-level accuracy is POOLED over the run's instructions, never a mean of
Case fractions. Worked example: Case A follows 1 of its 1 instruction, Case B 0 of its 3. Pooled,
1 of 4 instructions were followed: 0.25. The mean of the Case fractions (1.0 and 0.0) would be
0.5, a different number under the paper's name.

INVARIANT — the Draft Feedback bytes are the hand-built route's: `satisfaction` is the unrounded
fraction of instructions met strictly, and `feedback` is "The answer failed these requirements: "
followed by the checker's description of each failed instruction, joined by " | ". In a
Corrective Loop those words go into the next round's prompt, so one changed character would move
every later Candidate request (and the recorded golden). `test_local_task_ifeval.py` pins them.

References:
    - Paper: https://arxiv.org/abs/2311.07911 (Zhou et al., 2023)
    - Checker: https://github.com/josejg/instruction_following_eval (Apache-2.0)
      @ 0c495b2f95155e8b10acb919ae283bfb4d5be6e2, vendored under ./vendor
    - Case Source: https://huggingface.co/datasets/google/IFEval (Apache-2.0)
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from importlib import resources
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import Metric, SampleScore, Score, Scorer, Target, metric, scorer
from inspect_ai.solver import TaskState, generate

from screamingface_engine_inspect.local_tasks.ifeval.grading import (
    check_case,
    describe_failures,
    describe_instructions,
)

# ── pins (the hand-built definition.py) ──────────────────────────────────────────────────
DATASET = "google/IFEval"
DATASET_REVISION = "966cd89545d6b6acfd7638bc708b98261ca58e84"
CASE_COUNT = 541

#: The one row where the pinned Hub snapshot and the official file disagree: the Hub prompt
#: says "at least one placeholder" while its own arguments (and the official prompt) require
#: 3. The official text wins; any OTHER key differing refuses the build (the pin or the
#: official file changed, which is a new exam, not something to paper over).
KNOWN_DIVERGENT_KEYS = frozenset({2785})

# ── the paper's four numbers, as the Case's Named Scores (headline first) ───────────────
PROMPT_LEVEL_STRICT = "prompt_level_strict_accuracy"
INST_LEVEL_STRICT = "inst_level_strict_accuracy"
PROMPT_LEVEL_LOOSE = "prompt_level_loose_accuracy"
INST_LEVEL_LOOSE = "inst_level_loose_accuracy"
#: The hand-built Benchmark published instruction-level strict accuracy a second time under
#: this name, which the Report's card reads; kept as a run metric.
PASS_RATE = "pass_rate"

#: The key the plugin lane reads the Candidate-safe Draft Feedback from (OME-1527, R9).
DRAFT_FEEDBACK_KEY = "draft_feedback"
#: The hand-built route's opening words for a failing draft, and its separator.
FEEDBACK_PREFIX = "The answer failed these requirements: "
FEEDBACK_SEPARATOR = " | "
#: What the hand-built route said when a failed instruction had no description at all.
UNSPECIFIED_REQUIREMENT = "unspecified requirement"


# ── dataset loader (the hand-built prepare.py, minus the bundle writing) ──────────────────
def load_ifeval() -> MemoryDataset:
    """Load the pinned dataset in its own order, verified against the official file."""

    import datasets  # recorded (and its revision forced) by the importer's Case Source recorder

    loaded: Any = datasets.load_dataset(DATASET, revision=DATASET_REVISION)
    rows: list[dict[str, Any]] = [dict(row) for split in loaded for row in loaded[split]]
    if len(rows) != CASE_COUNT:
        raise ValueError(
            f"expected {CASE_COUNT} IFEval rows at {DATASET}@{DATASET_REVISION}, got {len(rows)}"
        )
    verified: list[dict[str, Any]] = verify_against_official(rows, official_rows())
    samples: list[Sample] = [
        record_to_sample(row, case_id) for case_id, row in enumerate(verified, start=1)
    ]
    return MemoryDataset(samples=samples, name="ifeval")


def official_rows() -> list[dict[str, Any]]:
    """The vendored official dataset, in its file order — the authority rows are checked
    and patched against (sha256 in ``vendor/__init__.py``)."""

    data: Any = resources.files("screamingface_engine_inspect.local_tasks.ifeval.vendor").joinpath(
        "data/input_data.jsonl"
    )
    return [json.loads(line) for line in data.read_text("utf-8").splitlines() if line.strip()]


def verify_against_official(
    rows: Sequence[Mapping[str, Any]], official: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The rows with the official prompt patched in where they differ — or a refusal.

    Compared per official ``key`` over what is graded: the prompt, the instruction ids and
    the null-stripped arguments. A key the official file does not know, a missing or repeated
    key, differing ids or arguments, or a differing prompt outside ``KNOWN_DIVERGENT_KEYS``
    raises ``ValueError``.
    """

    by_key: dict[int, Mapping[str, Any]] = {row["key"]: row for row in official}
    seen: set[int] = set()
    patched: list[dict[str, Any]] = []
    for row in rows:
        key: object = row.get("key")
        if not isinstance(key, int) or isinstance(key, bool):
            raise ValueError(f"IFEval row has a non-int official key: {key!r}")
        if key in seen:
            raise ValueError(f"duplicate official key {key} in the dataset")
        seen.add(key)
        authority: Mapping[str, Any] | None = by_key.get(key)
        if authority is None:
            raise ValueError(f"key {key} is not in the official dataset")
        if row.get("instruction_id_list") != authority["instruction_id_list"] or strip_nulls(
            row.get("kwargs") or []
        ) != strip_nulls(authority["kwargs"]):
            raise ValueError(
                f"key {key}: instruction ids/kwargs diverge from the official dataset — "
                "the Hub pin or the vendored official file changed; audit before rebuilding"
            )
        if row.get("prompt") != authority["prompt"]:
            if key not in KNOWN_DIVERGENT_KEYS:
                raise ValueError(
                    f"key {key}: the prompt diverges from the official dataset; only "
                    f"{sorted(KNOWN_DIVERGENT_KEYS)} is a known, patched divergence"
                )
            row = {**row, "prompt": authority["prompt"]}
        patched.append(dict(row))
    return patched


def strip_nulls(kwargs_list: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Drop None-valued argument keys.

    WHY: a `datasets` load pads every argument dict with all-None keys for schema
    uniformity; passing a None through ``build_description`` would override a checker's
    real default and crash or, worse, silently change the constraint.
    """

    return [
        {key: value for key, value in kwargs.items() if value is not None} for kwargs in kwargs_list
    ]


def record_to_sample(row: Mapping[str, Any], case_id: int) -> Sample:
    """One verified row → the prompt (the Candidate's whole input) and its private instructions.

    The arguments ride as a LIST parallel to the instruction ids, so every key stays a string
    through the Grading Material's JSON round trip (inspect_evals keys them by integer
    position, which JSON turns into "0", "1", …).
    """

    prompt: object = row.get("prompt")
    instruction_ids: object = row.get("instruction_id_list")
    kwargs_list: object = row.get("kwargs")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError(f"case {case_id}: empty 'prompt' column")
    if not isinstance(instruction_ids, list) or not instruction_ids:
        raise ValueError(f"case {case_id}: empty instruction_id_list")
    if not isinstance(kwargs_list, list) or len(kwargs_list) != len(instruction_ids):
        raise ValueError(
            f"case {case_id}: kwargs must be positionally parallel to instruction_id_list"
        )
    return Sample(
        id=case_id,
        input=prompt,
        # No answer key: the checker grades the reply against the instructions alone.
        target="",
        metadata={
            "instruction_id_list": list(instruction_ids),
            "kwargs": strip_nulls(kwargs_list),
        },
    )


# ── the scorer ────────────────────────────────────────────────────────────────────────────
def instruction_verdicts(
    instruction_ids: Sequence[str],
    kwargs_list: Sequence[Mapping[str, Any]],
    prompt: str,
    reply: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Check one reply: each instruction's strict and loose verdict, and the Draft Feedback.

    Returns the per-instruction records (id, the checker's description, strict, loose) and
    the hand-built route's Draft Feedback for this reply. Worked example: 1 of 3 instructions
    met strictly → satisfaction 1/3 = 0.3333333333333333 (unrounded, as the hand-built route
    sent it) and feedback "The answer failed these requirements: <description 2> |
    <description 3>"; all met → satisfaction 1.0 and feedback "".
    """

    result: dict[str, list[bool]] = check_case(
        instruction_id_list=instruction_ids, kwargs_list=kwargs_list, prompt=prompt, response=reply
    )
    strict: list[bool] = result["strict"]
    loose: list[bool] = result["loose"]
    descriptions: list[str] = describe_instructions(
        instruction_id_list=instruction_ids, kwargs_list=kwargs_list, prompt=prompt
    )
    records: list[dict[str, Any]] = [
        {"id": instruction_id, "description": description, "strict": met, "loose": loosely}
        for instruction_id, description, met, loosely in zip(
            instruction_ids, descriptions, strict, loose, strict=True
        )
    ]
    violations: list[str] = describe_failures(
        instruction_id_list=instruction_ids, kwargs_list=kwargs_list, prompt=prompt, strict=strict
    )
    feedback: str = (
        ""
        if all(strict)
        else FEEDBACK_PREFIX
        + (FEEDBACK_SEPARATOR.join(str(item) for item in violations) or UNSPECIFIED_REQUIREMENT)
    )
    draft_feedback: dict[str, Any] = {
        "satisfaction": sum(1 for met in strict if met) / len(strict),
        "feedback": feedback,
    }
    return records, draft_feedback


@metric
def ifeval_accuracy() -> Metric:
    """The paper's four numbers over the run, instruction-level ones POOLED.

    Returns a dict under the hand-built Benchmark's key names: the headline
    ``prompt_level_strict_accuracy`` (the row's ``whole_run_headline``), then
    ``inst_level_strict_accuracy``, ``prompt_level_loose_accuracy``,
    ``inst_level_loose_accuracy`` and ``pass_rate`` (instruction-level strict again, the
    number the Report's card shows). Each is rounded to 4 places, as the hand-built tally did.
    The instruction-level keys also name Named Scores, so the tally publishes the pooled
    number in those columns instead of a mean of Case fractions.

    Worked example: Case A follows 1 of 1 instruction (strict and loose), Case B 0 of 3
    strictly and 1 of 3 loosely → prompt-level strict 1/2 = 0.5, instruction-level strict
    1/4 = 0.25, prompt-level loose 1/2 = 0.5, instruction-level loose 2/4 = 0.5.

    Raises KeyError on a Score that lacks its ``instructions``: only `instruction_following`
    writes them, and a guessed count would publish a wrong number under the paper's name.
    """

    def compute(scores: list[SampleScore]) -> dict[str, float]:
        prompt_strict: list[bool] = []
        prompt_loose: list[bool] = []
        instructions_strict: list[bool] = []
        instructions_loose: list[bool] = []
        for sample_score in scores:
            records: list[dict[str, Any]] = (sample_score.score.metadata or {})["instructions"]
            strict: list[bool] = [bool(record["strict"]) for record in records]
            loose: list[bool] = [bool(record["loose"]) for record in records]
            prompt_strict.append(all(strict))
            prompt_loose.append(all(loose))
            instructions_strict.extend(strict)
            instructions_loose.extend(loose)
        inst_level_strict: float = _accuracy(instructions_strict)
        return {
            PROMPT_LEVEL_STRICT: _accuracy(prompt_strict),
            INST_LEVEL_STRICT: inst_level_strict,
            PROMPT_LEVEL_LOOSE: _accuracy(prompt_loose),
            INST_LEVEL_LOOSE: _accuracy(instructions_loose),
            PASS_RATE: inst_level_strict,
        }

    return compute


def _accuracy(values: Sequence[bool]) -> float:
    """The share of True values to 4 places, 0.0 for none (the hand-built rounding)."""

    return round(sum(1 for value in values if value) / len(values), 4) if values else 0.0


@scorer(metrics=[ifeval_accuracy()])
def instruction_following() -> Scorer:
    """Mark one reply with the vendored checker: the paper's four numbers for this Case.

    The value is one dict, headline first: prompt-level strict (1.0 when every instruction is
    followed strictly), the fraction followed strictly, prompt-level loose, the fraction
    followed loosely. The metadata carries each instruction's verdicts (what the run's tally
    pools, and the Report's audit trail) and the Draft Feedback the Corrective Loop sends the
    Candidate; nothing in it is a hidden key, since every instruction is stated in the prompt.
    """

    async def score(state: TaskState, target: Target) -> Score:
        metadata: dict[str, Any] = state.metadata
        records, draft_feedback = instruction_verdicts(
            metadata["instruction_id_list"],
            metadata["kwargs"],
            state.input_text,
            state.output.completion,
        )
        strict: list[bool] = [record["strict"] for record in records]
        loose: list[bool] = [record["loose"] for record in records]
        return Score(
            value={
                PROMPT_LEVEL_STRICT: 1.0 if all(strict) else 0.0,
                INST_LEVEL_STRICT: sum(1 for met in strict if met) / len(strict),
                PROMPT_LEVEL_LOOSE: 1.0 if all(loose) else 0.0,
                INST_LEVEL_LOOSE: sum(1 for met in loose if met) / len(loose),
            },
            metadata={"instructions": records, DRAFT_FEEDBACK_KEY: draft_feedback},
        )

    return score


# ── the Task ──────────────────────────────────────────────────────────────────────────────
@task
def ifeval() -> Task:
    """IFEval: 541 prompts with verifiable instructions, graded by the official checker."""

    return Task(
        dataset=load_ifeval(),
        solver=generate(),
        scorer=instruction_following(),
    )
