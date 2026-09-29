"""IFEval feedback sanitization — the #528 sealed-envelope precedent.

FEATURE: sanitized retry feedback (consumed today by the check-surface port).
STORY: as a corrective loop's member, the feedback I read describes the failed
constraint in the verifier's own words — and NEVER names a private instruction
id, because instruction ids are the marking scheme.

Migrated from the retired `test_ifeval_iterative_correction.py` (OME-796): the
corrective variants died, but `describe_failures` lives on behind the
check-surface adapter, and its leak guard is the contract every future adapter
(DRACO axis-level, HealthBench theme-level) must replicate.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.ifeval.grading import describe_failures

_SPECS = {
    1: {
        "key": 1000,
        "prompt": "No commas; at least five words.",
        "instruction_id_list": [
            "punctuation:no_comma",
            "length_constraints:number_words",
        ],
        "kwargs": [{}, {"relation": "at least", "num_words": 5}],
    },
    2: {
        "key": 1001,
        "prompt": "Wrap the answer in quotes.",
        "instruction_id_list": ["startend:quotation"],
        "kwargs": [{}],
    },
}


def test_describe_failures_returns_official_description_text_for_failed_only() -> None:
    descriptions = describe_failures(
        instruction_id_list=_SPECS[1]["instruction_id_list"],
        kwargs_list=_SPECS[1]["kwargs"],
        prompt=_SPECS[1]["prompt"],
        strict=[True, False],
    )

    assert len(descriptions) == 1
    # WHY the verifier's own wording: the feedback the retry sees must describe the
    # benchmark's constraint exactly as the checker enforces it — no paraphrase drift.
    assert "5" in descriptions[0] or "five" in descriptions[0].lower()


def test_describe_failures_is_empty_when_everything_passed() -> None:
    assert (
        describe_failures(
            instruction_id_list=_SPECS[2]["instruction_id_list"],
            kwargs_list=_SPECS[2]["kwargs"],
            prompt=_SPECS[2]["prompt"],
            strict=[True],
        )
        == []
    )


def test_describe_failures_does_not_leak_instruction_id_when_description_crashes() -> None:
    descriptions = describe_failures(
        instruction_id_list=["bogus:not_an_instruction"],
        kwargs_list=[{}],
        prompt="anything",
        strict=[False],
    )

    assert descriptions == ["One instruction requirement was not satisfied."]
    assert "bogus:not_an_instruction" not in descriptions[0]
