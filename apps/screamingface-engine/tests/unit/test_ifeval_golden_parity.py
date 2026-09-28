"""Golden parity: our IFEval grader equals the official fork's, on the official rows.

FEATURE: the parity proof behind every published IFEval number.
STORY: as a researcher, "our IFEval score" is comparable to published IFEval scores
because the grader is PROVEN equivalent to the community-standard fork (the pin
inspect_evals uses), not asserted equivalent by a comment.

What runs side by side, over all 541 official rows × a fixed response corpus:
- OURS:      screamingface_engine.benchmarks.ifeval.grading.check_case
- REFERENCE: vendor/evaluation.py test_instruction_following (verbatim fork code)

INVARIANT — verdict vectors must be IDENTICAL, not close. A single flipped bool is a
different exam. The four global metrics must match the reference formulas exactly,
modulo our aggregate's presentational round(…, 4).

Carve-out (owner decision 2026-08-10): keys 1122 (`letter: '#'`) and 1129
(`letter: '!'`) are EXCLUDED from parity — the official checker replaces their
non-a-z dataset letters with random ones, and we deliberately honor the literal
kwargs instead (grading._pinned_nonalpha_letter; RED coverage in
test_ifeval_grading.py). Parity is proven on the remaining 539 rows.

Determinism: the official checker is deliberately random when a constraint kwarg is
absent/invalid (the "Non-ASCII Roulette", LANL appendix A.4; e.g. an invalid
`letter` draws random.choice(ascii_letters) at vendor/instructions.py:1391). Ours
and the reference consume that randomness in DIFFERENT orders (we interleave
strict/loose per instruction; the fork runs two full passes), so seeding cannot
align the streams. Instead the fixture pins random.choice/randint/sample to
deterministic functions — both graders import the same `random` module, so both see
identical constraint parameters. This pins the roulette without touching vendored
code.
"""

from __future__ import annotations

import json
import random
from importlib import resources
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.ifeval.grade import _accuracy
from screamingface_engine.benchmarks.ifeval.grading import check_case
from screamingface_engine.benchmarks.ifeval.vendor import evaluation as official


def _official_rows() -> list[dict]:
    data = resources.files("screamingface_engine.benchmarks.ifeval.vendor").joinpath(
        "data/input_data.jsonl"
    )
    rows = [json.loads(line) for line in data.read_text("utf-8").splitlines() if line.strip()]
    assert len(rows) == 541, "the vendored official dataset must carry exactly 541 rows"
    return rows


# The corpus is small on purpose: each response exists to drive a distinct checker
# branch (commas, asterisks/highlights, multi-line loose-variant stripping, case
# checks, placeholders/brackets, bullets, quotes, postscripts, word/sentence
# counts). Coverage of the 25 instruction TYPES comes from the 541 rows, not from
# response variety.
_CANNED_RESPONSES = (
    # multi-line + markdown: exercises every loose variant and highlight counting
    "# Title\n\n*highlighted one* and *highlighted two*, plus a comma.\n\n"
    "* bullet one\n* bullet two\n\nlast line here",
    # placeholders, sections, postscript, quotes
    '"[address] is a [placeholder]"\n\nSECTION 1\ncontent\n\nP.S. a postscript line',
    # all caps, no commas, short
    "THIS RESPONSE IS ENTIRELY IN CAPITAL LETTERS WITH NO COMMA AT ALL",
    # lowercase long-form prose: word/sentence counts, keyword frequencies
    "this is a plain lowercase answer. it has several sentences. each one is "
    "short. together they exercise sentence counting and word counting paths. "
    "letters like q and z appear rarely.",
)


@pytest.fixture(autouse=True)
def _pinned_randomness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(random, "choice", lambda seq: sorted(seq)[0])
    monkeypatch.setattr(random, "randint", lambda a, b: a)
    monkeypatch.setattr(random, "sample", lambda seq, k: list(seq)[:k])
    # langdetect (used by change_case checkers via the vendored code) has its OWN
    # unseeded RNG — borderline texts flip detected language between runs, which is
    # not a grader divergence. Pin it so parity failures always mean parity bugs.
    import langdetect

    langdetect.DetectorFactory.seed = 0


@pytest.fixture(scope="module", autouse=True)
def _nltk_corpora() -> None:
    """Provision punkt/punkt_tab for sentence-count checkers, offline-first.

    Runtime Jobs get tokenizer data from prepared assets (grading.configure_nltk);
    tests provision a user-level cache once and reuse it. The download only fires
    on a machine that has never run this test.
    """
    import nltk

    cache = str((Path.home() / ".cache" / "nltk_data").absolute())
    if cache not in nltk.data.path:
        nltk.data.path.insert(0, cache)
    for resource in ("punkt", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{resource}")
        except LookupError:
            nltk.download(resource, quiet=True, download_dir=cache)


def _responses_for(row: dict) -> tuple[str, ...]:
    return (row["prompt"], *_CANNED_RESPONSES)


# WHY excluded from parity: the only two dataset rows whose letter_frequency letter the
# official checker replaces with random.choice(ascii_letters). We honor the literal
# dataset letter instead (see grading._pinned_nonalpha_letter) — a deliberate, documented
# divergence, so parity is proven over the other 539 rows and the divergent behavior is
# pinned by its own tests in test_ifeval_grading.py.
_HONORED_NONALPHA_LETTER_KEYS = frozenset({1122, 1129})


def _parity_rows() -> list[dict]:
    return [row for row in _official_rows() if row["key"] not in _HONORED_NONALPHA_LETTER_KEYS]


def test_verdict_vectors_match_the_official_fork_on_every_official_row() -> None:
    mismatches: list[str] = []
    for row in _parity_rows():
        for response in _responses_for(row):
            ours = check_case(
                instruction_id_list=row["instruction_id_list"],
                kwargs_list=[kwargs or {} for kwargs in row["kwargs"]],
                prompt=row["prompt"],
                response=response,
            )
            ref_strict = official.test_instruction_following(row, response, strict=True)
            ref_loose = official.test_instruction_following(row, response, strict=False)
            if (
                ours["strict"] != ref_strict.follow_instruction_list
                or ours["loose"] != ref_loose.follow_instruction_list
            ):
                mismatches.append(
                    f"key={row['key']} response={response[:40]!r} "
                    f"ours={ours} ref_strict={ref_strict.follow_instruction_list} "
                    f"ref_loose={ref_loose.follow_instruction_list}"
                )
    assert not mismatches, f"{len(mismatches)} verdict mismatches:\n" + "\n".join(mismatches[:10])


def test_global_metrics_match_the_official_formulas() -> None:
    # One deterministic response per row, drawn round-robin from the corpus so the
    # metric means mix passes and failures rather than degenerating to 0.0.
    # Parity rows only: the two honored non-a-z letter rows grade differently by
    # design, so both sides of the formula comparison must exclude them.
    rows = _parity_rows()
    responses = [_responses_for(row)[index % 5] for index, row in enumerate(rows)]

    reference = official.evaluate_instruction_following(rows, responses)

    strict_all, loose_all, strict_flat, loose_flat = [], [], [], []
    for row, response in zip(rows, responses, strict=True):
        ours = check_case(
            instruction_id_list=row["instruction_id_list"],
            kwargs_list=[kwargs or {} for kwargs in row["kwargs"]],
            prompt=row["prompt"],
            response=response,
        )
        strict_all.append(all(ours["strict"]))
        loose_all.append(all(ours["loose"]))
        strict_flat.extend(bool(value) for value in ours["strict"])
        loose_flat.extend(bool(value) for value in ours["loose"])

    # Mirrors aggregate.py's candidate-result metric expressions exactly (score =
    # prompt-level strict; the other three under metrics). `_accuracy` rounds to 4
    # decimals for presentation — the reference does not — so parity is
    # ours == round(reference, 4), never approximate equality.
    assert _accuracy(strict_all) == round(reference["prompt_level_strict_accuracy"], 4)
    assert _accuracy(strict_flat) == round(reference["inst_level_strict_accuracy"], 4)
    assert _accuracy(loose_all) == round(reference["prompt_level_loose_accuracy"], 4)
    assert _accuracy(loose_flat) == round(reference["inst_level_loose_accuracy"], 4)
