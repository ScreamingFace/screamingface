"""The golden of the GSM8K Fusion regression lane (OME-1289 E4a, FR#13).

Mental model: ``reducer_golden`` pins a vote lane. This module pins the Fusion lane, whose claim is
exact: the rewritten ``sf.Fusion`` (a Fan-out, a context Reduce, then a Model) must send the same
requests and give the same answers as the recording did. Two Fusion shapes are pinned
(FR-D2), each over the same ``samples`` seeded members of one model:

- ``model_synthesizer``: ``sf.Fusion(members, synthesizer=sf.Model(m))``;
- ``recipe_synthesizer``: ``sf.Fusion(members, synthesizer=<a named two-stage Pipeline>)``, whose
  second stage re-reads the first stage's answer (``CHECK_PROMPT``).

``FusionGolden.outcome(recipe)`` maps one recipe to a ``goldens.GoldenReport`` (``kind: "model"``,
no models: the same trick as ``ReducerGolden.outcome``), so ``compare_outcome`` runs its five locks
UNCHANGED. Two locks are new: the Case outputs (a vote hides a changed answer behind an unchanged
status, a Fusion does not) and the request bodies, pinned as sorted sha256 digests of every body
the Engine sent to the gateway (a canonical JSON digest, key order included).

Worked example: a 5-Case recipe lock holds five outputs and ``3 * 5 + 5 = 20`` digests for the
model synthesizer (three members and one synthesis per Case). A replay that built one member
request differently has one digest missing and one new, and is reported as "1 missing, 1 new".
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from screamingface.case_result import CaseStatus

from .goldens import GoldenFailure, GoldenReport
from .reducer_golden import lane_remediation, load_golden

FUSION_GOLDEN_SCHEMA: Final = "screamingface.fusion-golden.v1"
CHECK_PROMPT: Final = "Check the answer above. End with the final number alone on the last line."
#: WHY named: sf.Pipeline flattens an UNNAMED nested Pipeline at construction, so the block form of
#: a Fusion with an unnamed Pipeline synthesizer means something else (unit 10S, F11).
_SYNTHESIZER_NAME: Final = "check"

type FusionRecipe = Literal["model_synthesizer", "recipe_synthesizer"]
RECIPES: Final[tuple[FusionRecipe, ...]] = ("model_synthesizer", "recipe_synthesizer")

_SCRIPT: Final = "tests/e2e/fixtures/fusion_lane.py"
_SHA256_HEX = r"^[0-9a-f]{64}$"
_Sha = Annotated[str, StringConstraints(pattern=_SHA256_HEX)]


class FusionLaneSpec(BaseModel):
    """The replay INPUT of the lane: ``build(recipe)`` is the candidate the user recorded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    samples: int = Field(ge=2, le=8)
    temperature: float | None

    def members(self):  # -> list[sf.Model]
        import screamingface as sf

        return list(sf.samples(self.model, self.samples, temperature=self.temperature))

    def synthesizer(self, recipe: FusionRecipe):  # -> Recipe
        import screamingface as sf

        if recipe == "model_synthesizer":
            return sf.Model(self.model)
        return sf.Pipeline(
            [sf.Model(self.model), sf.Model(self.model, prompt=CHECK_PROMPT)],
            name=_SYNTHESIZER_NAME,
        )

    def build(self, recipe: FusionRecipe):  # -> sf.Pipeline (a chain)
        """The named form, which ``record`` runs."""
        from screamingface import _surface as sx

        return sx.Fanout(self.members()) >> sx.Synthesize(self.synthesizer(recipe))

    def build_block(self, recipe: FusionRecipe):  # -> sf.Pipeline (a chain)
        """The block form of today was Fan-out, ``Reduce("context")``, then the synthesizer
        (FR-2); the map/select/reduce surface has one form for both (R11), so it is ``build``."""

        return self.build(recipe)


class FusionRecipeLock(BaseModel):
    """The expected outcome of one recipe over the lane's Cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expression_sha: str = Field(pattern=_SHA256_HEX)
    final_score: str | None
    case_count: int = Field(ge=0)
    gradeable_count: int = Field(ge=0)
    case_statuses: dict[str, CaseStatus]
    case_failures: dict[str, tuple[GoldenFailure, ...]] = {}
    case_outputs: dict[str, str | None]
    request_bodies: tuple[_Sha, ...]

    @model_validator(mode="after")
    def _outputs_cover_the_cases(self) -> FusionRecipeLock:
        if set(self.case_outputs) != set(self.case_statuses):
            raise ValueError("case_outputs and case_statuses must list the same cases")
        return self


class FusionGolden(BaseModel):
    """The frozen expected outcome of the Fusion lane (the field docs are in goldens.py)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_: Literal["screamingface.fusion-golden.v1"] = Field(
        alias="schema", default=FUSION_GOLDEN_SCHEMA
    )
    lane: Literal["inspect-gsm8k-fusion"]
    board: Literal["inspect-gsm8k"]
    revision: str = Field(min_length=1)
    limit: int | None
    candidate: FusionLaneSpec
    recipes: dict[FusionRecipe, FusionRecipeLock]

    def outcome(self, recipe: FusionRecipe) -> GoldenReport:
        """The five-lock answer sheet of one recipe, so ``compare_outcome`` runs unchanged."""
        lock = self.recipes[recipe]
        return GoldenReport(
            # `models` stays empty: the lane builds its candidates from `FusionLaneSpec`.
            kind="model",
            board=self.board,
            revision=self.revision,
            limit=self.limit,
            expression_sha=lock.expression_sha,
            final_score=lock.final_score,
            case_count=lock.case_count,
            gradeable_count=lock.gradeable_count,
            case_statuses=lock.case_statuses,
            case_failures=lock.case_failures,
        )

    @model_validator(mode="after")
    def _has_every_recipe_and_each_agrees_with_the_five_lock_golden(self) -> FusionGolden:
        # INVARIANT: both shapes are pinned, and each tells one story. GoldenReport owns the
        # counter and failure rules, so it is asked, not copied.
        if set(self.recipes) != set(RECIPES):
            raise ValueError(f"recipes must be exactly {', '.join(RECIPES)}")
        for recipe in RECIPES:
            try:
                self.outcome(recipe)
            except ValidationError as exc:
                raise ValueError(f"{recipe}: {lane_remediation(str(exc), _SCRIPT)}") from exc
        return self


def body_digests(records: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """The sorted sha256 of every captured request body, one per body, duplicates kept.

    This is a canonical JSON digest, not a digest of the wire bytes: the capture proxy parses each
    body, and the digest hashes the re-encoded JSON (compact separators, ``ensure_ascii=False``).
    The encoding keeps the key order the Engine wrote (no ``sort_keys``): the gateway keys its cache
    on the parsed body, but a body that is built in another order is another build.
    """
    return tuple(
        sorted(
            hashlib.sha256(
                json.dumps(
                    record["request_body"], ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            for record in records
        )
    )


def case_outputs(cases: Sequence[Any]) -> dict[str, str | None]:
    """case id -> the Case's final output text (None when it has none)."""
    return {str(case.case_id): case.output for case in cases}


def assert_fusion_replay(
    lock: FusionRecipeLock, cases: Sequence[Any], digests: Sequence[str]
) -> None:
    """FR#13: the replay's Case outputs and request body digests are the recorded ones.

    Raises ``AssertionError`` naming the first Case whose output drifted (golden, actual) or that
    one side lacks, or, after the outputs, how many request bodies are missing and how many are new
    (a multiset compare, so a body sent twice instead of once is a drift too).
    """
    assert_outputs(lock.case_outputs, cases)
    golden_bodies, replayed_bodies = Counter(lock.request_bodies), Counter(digests)
    missing = sum((golden_bodies - replayed_bodies).values())
    new = sum((replayed_bodies - golden_bodies).values())
    if missing or new:
        raise AssertionError(f"request bodies drifted: {missing} missing, {new} new")


def assert_outputs(golden: Mapping[str, str | None], cases: Sequence[Any]) -> None:
    """Every Case output is the recorded one, and the Case sets agree (first drift, in saved order).

    Raises ``AssertionError`` naming the first Case whose output drifted (golden, actual) or that
    one side lacks.
    """
    actual = case_outputs(cases)
    for case_id in (*golden, *(key for key in actual if key not in golden)):
        _assert_output(case_id, golden, actual)


def _assert_output(
    case_id: str, golden: Mapping[str, str | None], actual: Mapping[str, str | None]
) -> None:
    if case_id not in golden or case_id not in actual:
        where = "golden" if case_id not in golden else "replay"
        raise AssertionError(f"case {case_id!r} is missing from the {where}")
    if golden[case_id] != actual[case_id]:
        raise AssertionError(
            f"case {case_id!r} output drifted (golden, actual): "
            f"{golden[case_id]!r} != {actual[case_id]!r}"
        )


def load_fusion_golden(path: Path) -> FusionGolden:
    """Read + validate one ``*.fusion-golden.json``; any shape problem raises at load time."""
    return load_golden(path, FusionGolden)
