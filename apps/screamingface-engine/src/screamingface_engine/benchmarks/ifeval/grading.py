"""Per-case IFEval grading — the vendored verifier behind a crash-safe boundary.

Reimplements the ~40 protocol lines of the fork's ``evaluation.py`` (its typer/rich CLI
wrapper is not vendored) over the vendored ``instructions_registry``.

INVARIANT: the strict and loose protocols mirror the fork's ``test_instruction_following``
EXACTLY — the loose variant list, the empty-variant skip, and the ``prompt`` rebuild are
the benchmark. A different reading is a different benchmark.

ONE deliberate, documented divergence: ``keywords:letter_frequency`` kwargs whose letter is
a single non-a-z character ('#' case 1122, '!' case 1129 — the only two in the dataset) are
graded against the literal dataset character instead of the official checker's silent
``random.choice(ascii_letters)`` replacement. Rationale, evidence, and the owner decision
live on ``_pinned_nonalpha_letter``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def configure_nltk(data_dir: Path) -> None:
    """Point nltk at the prepared offline corpus, once.

    INVARIANT: the verifier's own ``ensure_nltk_resource`` downloader is NEVER called — a
    Runner Job has a read-only rootfs and no network egress, so tokenizer data must come
    from the benchmark's prepared assets.
    """

    import nltk

    selected = str(data_dir)
    if data_dir.is_dir() and selected not in nltk.data.path:
        nltk.data.path.insert(0, selected)


def check_case(
    *,
    instruction_id_list: Sequence[str],
    kwargs_list: Sequence[Mapping[str, Any]],
    prompt: str,
    response: str,
) -> dict[str, list[bool]]:
    """Check one response against its case's constraints, strict and loose."""

    if len(instruction_id_list) != len(kwargs_list):
        raise ValueError(
            "instruction_id_list and kwargs must be positionally parallel — "
            f"got {len(instruction_id_list)} instructions and {len(kwargs_list)} kwargs"
        )
    loose_responses = _loose_variants(response)
    strict: list[bool] = []
    loose: list[bool] = []
    for instruction_id, kwargs in zip(instruction_id_list, kwargs_list, strict=True):
        strict.append(_follows(instruction_id, kwargs, prompt, [response]))
        loose.append(_follows(instruction_id, kwargs, prompt, loose_responses))
    return {"strict": strict, "loose": loose}


def describe_failures(
    *,
    instruction_id_list: Sequence[str],
    kwargs_list: Sequence[Mapping[str, Any]],
    prompt: str,
    strict: Sequence[bool],
) -> list[str]:
    """The checker's own wording for every failed instruction — the retry's feedback.

    WHY the verifier's own ``build_description`` text: the feedback a corrective
    attempt sees must describe the constraint exactly as the checker enforces it —
    a paraphrase could drift from what the benchmark actually grades.
    """

    if not (len(instruction_id_list) == len(kwargs_list) == len(strict)):
        raise ValueError("instruction ids, kwargs and verdicts must be positionally parallel")
    return [
        _describe(instruction_id, kwargs, prompt)
        for instruction_id, kwargs, passed in zip(
            instruction_id_list, kwargs_list, strict, strict=True
        )
        if not passed
    ]


def describe_instructions(
    *,
    instruction_id_list: Sequence[str],
    kwargs_list: Sequence[Mapping[str, Any]],
    prompt: str,
) -> list[str]:
    """Return the official human-readable description of every checked constraint."""

    if len(instruction_id_list) != len(kwargs_list):
        raise ValueError("instruction ids and kwargs must be positionally parallel")
    return [
        _describe(instruction_id, kwargs, prompt)
        for instruction_id, kwargs in zip(instruction_id_list, kwargs_list, strict=True)
    ]


def _describe(instruction_id: str, kwargs: Mapping[str, Any], prompt: str) -> str:
    try:
        _instruction, description = _build_instruction(instruction_id, kwargs, prompt)
        return description
    except Exception:  # noqa: BLE001
        # Same crash-policy boundary as _follows: a describer bug must never take the
        # whole check down. Keep the fallback generic because instruction identifiers
        # are private grading material and must not enter Candidate context.
        return "One instruction requirement was not satisfied."


_LETTER_FREQUENCY_ID = "keywords:letter_frequency"


def _pinned_nonalpha_letter(instruction_id: str, kwargs: Mapping[str, Any]) -> str | None:
    """The dataset's literal letter kwarg IFF the official checker would randomize it away.

    Mental model: the official ``LetterFrequencyChecker`` has a bouncer at the door —
    any single character outside a-z (checked as ``ord(letter.lower())`` outside 97..122)
    is turned away and replaced by ``random.choice(ascii_letters)``. The official DATASET,
    however, pins exactly two such letters: case 1122 ``'#'`` ("include at least 4
    hashtags") and case 1129 ``'!'``. So upstream grades those prompts against a letter
    the prompt never mentioned — and a fresh random one per instantiation, which is how
    one live run showed a label demanding 'q', feedback demanding 'm', and loose failing
    while strict passed on the same answer.

    Owner decision (2026-08-10, ledger
    ``docs/work/2026-08-10-OME-TBD-ifeval-letter-frequency-kwarg-fidelity.md``): honor the
    dataset kwarg. This is a DELIBERATE divergence from the official verifier on those 2
    of 541 cases — grading a requirement the prompt never stated is not a benchmark. The
    vendored verifier stays byte-identical; the override lives here at the grading
    boundary, applied by ``_build_instruction`` after ``build_description``.

    Returns the literal letter to re-pin, or None when official behavior already honors
    the kwarg (a-z letters — untouched for leaderboard comparability) or when there is
    nothing to honor (missing/multi-char letter stays on the official random path).
    """

    if instruction_id != _LETTER_FREQUENCY_ID:
        return None
    letter = kwargs.get("letter")
    # INVARIANT: mirror the vendored bouncer's predicate EXACTLY — re-pin only what it
    # would randomize, so a-z kwargs keep byte-identical official grading.
    if isinstance(letter, str) and len(letter) == 1 and not ("a" <= letter.lower() <= "z"):
        return letter.lower()
    return None


def _build_instruction(
    instruction_id: str, kwargs: Mapping[str, Any], prompt: str
) -> tuple[Any, str]:
    """Build one verifier instruction plus its rendered description, honoring pinned kwargs.

    Stages, in execution order:
    1. Instantiate the vendored instruction and ``build_description(**kwargs)`` — the
       official protocol (this is also where the checker may swap a non-a-z letter for a
       random one, see ``_pinned_nonalpha_letter``).
    2. Official quirk kept verbatim: instructions whose args carry ``prompt`` are rebuilt
       with the case prompt.
    3. Re-pin: when the dataset's letter kwarg would have been randomized, overwrite the
       checker's ``_letter`` with the literal dataset character and re-render the
       description from the checker's own pattern — so label, strict, loose, and feedback
       all speak the same requirement (``check_following`` counts via
       ``Counter(value.lower())[self._letter]``, which counts any single character).

    Every call site (strict check, loose check, labels, feedback) MUST build through this
    helper — a direct ``build_description`` call reintroduces the random-letter split.
    """

    from screamingface_engine.benchmarks.ifeval.vendor import instructions_registry

    instruction_cls = instructions_registry.INSTRUCTION_DICT[instruction_id]
    instruction = instruction_cls(instruction_id)
    description = instruction.build_description(**kwargs)
    args = instruction.get_instruction_args()
    if args and "prompt" in args:
        description = instruction.build_description(prompt=prompt)
    pinned = _pinned_nonalpha_letter(instruction_id, kwargs)
    if pinned is not None:
        instruction._letter = pinned  # noqa: SLF001  # WHY: the vendored checker offers no setter; vendor/ is contractually unmodifiable
        description = instruction._description_pattern.format(  # noqa: SLF001
            letter=instruction._letter,  # noqa: SLF001
            let_frequency=instruction._frequency,  # noqa: SLF001
            let_relation=instruction._comparison_relation,  # noqa: SLF001
        )
    return instruction, str(description)


def _loose_variants(response: str) -> list[str]:
    # IFEval's loose protocol (Zhou et al., arXiv:2311.07911): the response plus 7
    # markdown/edge-line-stripped variants;
    # compliant under ANY variant counts. Mirrors evaluation.py verbatim.
    variants = [
        response,
        response.replace("*", ""),
        "\n".join(response.split("\n")[1:]).strip(),
        "\n".join(response.split("\n")[:-1]).strip(),
        "\n".join(response.split("\n")[1:-1]).strip(),
    ]
    variants += [variant.replace("*", "") for variant in variants[2:]]
    return variants


def _follows(
    instruction_id: str,
    kwargs: Mapping[str, Any],
    prompt: str,
    responses: Sequence[str],
) -> bool:
    instruction, _description = _build_instruction(instruction_id, kwargs, prompt)
    return any(response.strip() and instruction.check_following(response) for response in responses)


__all__ = ["check_case", "configure_nltk", "describe_failures", "describe_instructions"]
