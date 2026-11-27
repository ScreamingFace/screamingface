"""The strict Router IR ``screamingface.router-spec.v1`` and its revision (contracts C2, C3, C16).

FEATURE: Router Recipe extension, Unit 5.2. The intent of a Router's ADMIT step is this envelope;
the Engine owns its validation and the SDK is only its author. A named profile's dynamic form
normalizes into the same definition ``D`` and hashes it with the same revision.

INVARIANT: every record is a closed union. A value matches exactly one variant, every listed key
is present, ``null`` means "none" and an unlisted key is absent. Anything else is
``router_definition_invalid``, never an ignored extension.
INVARIANT: the revision is computed from the decoded values, never from the transport bytes.
INVARIANT: a refusal names the field path and the rule, never a value of the definition.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    Discriminator,
    Field,
    Tag,
    ValidationError,
    model_validator,
)

from screamingface_engine.combine.ports import CombineError, utf8_exceeds
from screamingface_engine.router_vocabulary import (
    MAX_LABEL_BYTES,
    REVISION_SCHEME,
    SCORES_CONTRACT,
    Label,
    Revision,
    RouterBinding,
    RouterPolicy,
    StrictModel,
    strict_json,
)
from screamingface_engine.router_vocabulary import field_rule as masked_field_rule

ROUTER_SPEC_SCHEMA = "screamingface.router-spec.v1"
DEFINITION_INVALID = "router_definition_invalid"
ROUTER_UNSUPPORTED = "router_unsupported"

# C16 bounds.
MAX_SPEC_BYTES = 64 * 1024
MAX_DEFINITION_BYTES = 64 * 1024
MAX_CANDIDATES = 32
MAX_DESCRIPTION_CHARS = 1024
MAX_INSTRUCTIONS_CHARS = 4096
MAX_RULE_PATTERN_CHARS = 256

_SELECTOR = re.compile(r"selector_[1-9][0-9]*")
_MODEL = re.compile(r"model_[1-9][0-9]*")
_SYNTHESIS = re.compile(r"synthesis_[1-9][0-9]*")
# WHY: a key under these fields is authored data, so a refusal path never repeats it.
_AUTHORED_MAPS = frozenset({"params", "args"})


class RouterSpecError(ValueError):
    """A definition that is not exactly one variant of every record; permanent (C11)."""

    code = DEFINITION_INVALID
    permanent = True


def canonical(value: object) -> bytes:
    """The C3 canonical JSON bytes of ``value``."""

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def definition_revision(definition: object) -> str:
    """``"sha256:" + hex(sha256(canonical({"scheme": ..., "definition": D})))`` (C3)."""

    preimage = canonical({"scheme": REVISION_SCHEME, "definition": definition})
    return "sha256:" + hashlib.sha256(preimage).hexdigest()


# --- field rules ---------------------------------------------------------------------------------


def _binding(pattern: re.Pattern[str], name: str) -> Callable[[str], str]:
    def check(value: str) -> str:
        if pattern.fullmatch(value) is None:
            raise ValueError(f"a {name} binding is {name}_N")
        return value

    return check


Description = Annotated[str, Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)]
Instructions = Annotated[str, Field(min_length=1, max_length=MAX_INSTRUCTIONS_CHARS)]
RouteId = Annotated[str, Field(min_length=1)]
SelectorBinding = Annotated[str, AfterValidator(_binding(_SELECTOR, "selector"))]
ModelBinding = Annotated[str, AfterValidator(_binding(_MODEL, "model"))]
SynthesisBinding = Annotated[str, AfterValidator(_binding(_SYNTHESIS, "synthesis"))]


class ModelRef(StrictModel):
    """C2 ``Model``: the canonical Model ID, its prompt and exactly the call's parameters."""

    model: RouteId
    prompt: str | None
    params: dict[str, str]


class FixedScoring(StrictModel):
    source: Literal["scoring"]
    model: RouteId
    contract: Literal["classification-scores-v1"]
    input: Literal["text"]


class ChoiceScoring(StrictModel):
    source: Literal["scoring"]
    model: RouteId
    contract: Literal["classification-scores-v1"]
    input: Literal["choice"]
    instructions: Instructions


class LlmSelector(StrictModel):
    source: Literal["llm"]
    model: ModelRef
    labels: tuple[Label, ...] = Field(min_length=1, max_length=MAX_CANDIDATES)
    prompt: str | None
    multi: bool


class RegexRule(StrictModel):
    """One rule as ``RegexClassifier._spec()["rules"]`` writes it (the E4c Keywords rule)."""

    label: Label
    pattern: str = Field(min_length=1, max_length=MAX_RULE_PATTERN_CHARS)
    ignore_case: bool = False

    @model_validator(mode="after")
    def _runs(self) -> RegexRule:
        # WHY imported here: `extract` imports RE2 (google-re2), an Engine dependency that a
        # world-file reader such as the SDK runtime may lack; only a regex rule needs it.
        # INVARIANT: without RE2 this raises ModuleNotFoundError, which pydantic does not turn
        # into a refusal, so a regex selector is never admitted (fail closed, before any read).
        from screamingface_engine.combine.operators.extract import compile_regex

        try:
            compile_regex({"pattern": self.pattern, "ignore_case": self.ignore_case})
        except CombineError as exc:
            raise ValueError("a rule pattern is one RE2 can run") from exc
        return self


class RegexSelector(StrictModel):
    source: Literal["regex"]
    rules: tuple[RegexRule, ...] = Field(min_length=1, max_length=MAX_CANDIDATES)
    multi: bool


def _classifier_tag(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    source = value.get("source")
    if source == "scoring":
        return "choice" if "instructions" in value or value.get("input") == "choice" else "fixed"
    return source if source in ("llm", "regex") else None


Classifier = Annotated[
    Annotated[FixedScoring, Tag("fixed")]
    | Annotated[ChoiceScoring, Tag("choice")]
    | Annotated[LlmSelector, Tag("llm")]
    | Annotated[RegexSelector, Tag("regex")],
    Discriminator(_classifier_tag),
]


class PlainCandidate(StrictModel):
    label: Label
    model: ModelRef


class DescribedCandidate(StrictModel):
    label: Label
    model: ModelRef
    description: Description


def _candidate_tag(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    return "described" if "description" in value else "plain"


Candidate = Annotated[
    Annotated[PlainCandidate, Tag("plain")] | Annotated[DescribedCandidate, Tag("described")],
    Discriminator(_candidate_tag),
]


class UniqueArgmax(StrictModel):
    type: Literal["unique-argmax-v1"]


Policy = Annotated[RouterPolicy | UniqueArgmax, Field(discriminator="type")]


class ModelSynthesizer(StrictModel):
    kind: Literal["model"]
    model: ModelRef


class PinnedStep(StrictModel):
    """A combine-spec pinned step: the operator id and its arguments."""

    op: Annotated[str, Field(min_length=1)]
    args: dict[str, Any]


class VoteSynthesizer(StrictModel):
    kind: Literal["vote"]
    extract: PinnedStep | None
    normalize: PinnedStep | None


Synthesizer = Annotated[ModelSynthesizer | VoteSynthesizer, Field(discriminator="kind")]


class Definition(StrictModel):
    """C2 ``D``: everything that enters the revision."""

    classifier: Classifier
    policy: Policy
    candidates: tuple[Candidate, ...] = Field(min_length=1, max_length=MAX_CANDIDATES)
    default: ModelRef | None
    synthesizer: Synthesizer | None
    quorum: Literal["all"] | int | None

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(candidate.label for candidate in self.candidates)

    @model_validator(mode="after")
    def _check(self) -> Definition:
        labels = self.labels
        if len(set(labels)) != len(labels):
            raise ValueError("candidate labels are unique")
        self._check_candidates(labels)
        if isinstance(self.policy, UniqueArgmax):
            if not isinstance(self.classifier, FixedScoring | ChoiceScoring):
                raise ValueError("unique-argmax-v1 reads a scoring classifier")
            if (self.default, self.synthesizer, self.quorum) != (None, None, None):
                raise ValueError("unique-argmax-v1 has no default, synthesizer or quorum")
            return self
        self._check_policy(self.policy)
        return self

    def _check_candidates(self, labels: tuple[str, ...]) -> None:
        classifier = self.classifier
        if isinstance(classifier, FixedScoring):
            if not all(isinstance(candidate, PlainCandidate) for candidate in self.candidates):
                raise ValueError("fixed-label scoring candidates carry no description")
        elif isinstance(classifier, ChoiceScoring):
            if not all(isinstance(candidate, DescribedCandidate) for candidate in self.candidates):
                raise ValueError("choice scoring candidates each carry a description")
        else:
            declared = (
                classifier.labels
                if isinstance(classifier, LlmSelector)
                else tuple(rule.label for rule in classifier.rules)
            )
            if len(set(declared)) != len(declared) or set(declared) != set(labels):
                raise ValueError("selector labels are unique and equal the candidate labels")

    def _check_policy(self, policy: RouterPolicy) -> None:
        scoring = isinstance(self.classifier, FixedScoring | ChoiceScoring)
        if (policy.match == "best") != scoring:
            raise ValueError("match best reads a scoring classifier and exact a selector")
        if policy.match == "best" and policy.select == "all":
            raise ValueError("match best selects one")
        if policy.select == "one" and (self.synthesizer, self.quorum) != (None, None):
            raise ValueError("select one has no synthesizer or quorum")
        if policy.select == "all" and (self.synthesizer is None or self.quorum is None):
            raise ValueError("select all has a synthesizer and a quorum")
        if isinstance(self.quorum, int) and not 1 <= self.quorum <= len(self.candidates):
            raise ValueError("quorum is all or 1..the candidate count")


class Calls(StrictModel):
    """The compiler binding each role's model call carries; not part of the revision."""

    classifier: SelectorBinding | None
    candidates: tuple[ModelBinding, ...]
    default: ModelBinding | None
    synthesizer: SynthesisBinding | None

    def bindings(self) -> tuple[str, ...]:
        roles = (self.classifier, *self.candidates, self.default, self.synthesizer)
        return tuple(binding for binding in roles if binding is not None)


class RouterSpec(StrictModel):
    """The validated ``router-spec.v1`` envelope."""

    schema_id: Literal["screamingface.router-spec.v1"] = Field(alias="schema")
    router: RouterBinding
    revision: Revision
    revision_scheme: Literal["router-definition-v1"]
    calls: Calls
    definition: Definition

    @model_validator(mode="after")
    def _check(self) -> RouterSpec:
        definition = self.definition
        if not isinstance(definition.policy, RouterPolicy):
            raise ValueError("a router spec carries a router-policy")
        calls = self.calls
        if (calls.classifier is None) == isinstance(definition.classifier, LlmSelector):
            raise ValueError("calls.classifier names the llm selector call, else null")
        if len(calls.candidates) != len(definition.candidates):
            raise ValueError("calls.candidates names one binding per candidate")
        if (calls.default is None) != (definition.default is None):
            raise ValueError("calls.default names the default call, else null")
        if (calls.synthesizer is None) != (definition.synthesizer is None):
            raise ValueError("calls.synthesizer names the synthesizer call, else null")
        bindings = calls.bindings()
        if len(set(bindings)) != len(bindings):
            raise ValueError("calls bindings are unique")
        return self


def parse_router_spec(text: str) -> RouterSpec:
    """Validate one ``router-spec.v1`` envelope (C2) and recompute its revision (C3).

    INVARIANT: the decoded definition is read once, here, for its revision, and never kept: the
    typed spec is the one form every later reader uses (ADMIT records it for the later steps).

    Raises:
        RouterSpecError: ``router_definition_invalid``; the message names a field and a rule.
    """

    if utf8_exceeds(text, MAX_SPEC_BYTES):
        raise RouterSpecError("router spec is larger than 64 KiB")
    try:
        raw = strict_json(text)
    except ValueError as exc:
        raise RouterSpecError("router spec is not strict JSON") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("definition"), dict):
        raise RouterSpecError("router spec is a JSON object with a definition object")
    try:
        spec = RouterSpec.model_validate_json(text)
    except ValidationError as exc:
        raise RouterSpecError(f"router spec is invalid at {field_rule(exc)}") from None
    if definition_revision(raw["definition"]) != spec.revision:
        raise RouterSpecError("router spec revision does not recompute from its definition")
    return spec


def field_rule(exc: ValidationError) -> str:
    """The first failing field path and its rule, with authored map keys masked."""
    return masked_field_rule(exc, _AUTHORED_MAPS)


__all__ = [
    "DEFINITION_INVALID",
    "MAX_CANDIDATES",
    "MAX_DEFINITION_BYTES",
    "MAX_DESCRIPTION_CHARS",
    "MAX_INSTRUCTIONS_CHARS",
    "MAX_LABEL_BYTES",
    "MAX_SPEC_BYTES",
    "REVISION_SCHEME",
    "ROUTER_SPEC_SCHEMA",
    "ROUTER_UNSUPPORTED",
    "SCORES_CONTRACT",
    "Calls",
    "ChoiceScoring",
    "DescribedCandidate",
    "Definition",
    "FixedScoring",
    "LlmSelector",
    "ModelRef",
    "ModelSynthesizer",
    "PlainCandidate",
    "RegexSelector",
    "RouterPolicy",
    "RouterSpec",
    "RouterSpecError",
    "UniqueArgmax",
    "VoteSynthesizer",
    "canonical",
    "definition_revision",
    "field_rule",
    "parse_router_spec",
    "strict_json",
]
