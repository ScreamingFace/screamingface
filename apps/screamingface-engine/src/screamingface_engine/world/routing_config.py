"""Routing profiles: the `[routing.profiles.<id>]` tables of the declared world (OME-1822).

FEATURE: BYOM routing pilot (spec 3.1). A profile names one classifier and binds each of its
labels to one declared chat route with its own `max_tokens`. `/route-answer` classifies a
question, takes the unique highest label and asks that label's route.

WHY in the world file: the App, a cold run and a warm child already read this one file
(`read_world_file`), so a profile has one parsed revision everywhere and `/healthz` reports the
digest of the bytes it came from.

INVARIANT: every rule is local and structural and fails startup with `WorldConfigError`. Nothing
here calls the Gateway: whether a target is visible, connected and accepts the bound parameter is
the endpoint's preflight, per caller.

INVARIANT: a refusal names the profile and the key, never a value. The file can be a mounted
Secret, and a branch model is a private route (`public_schema = false`).

FEATURE: Router Recipe extension, Unit 5.2 (contracts C2, C3, C16). A dynamic-choice profile adds
exactly `revision_scheme = "router-definition-v1"` and `instructions`, and each branch exactly
`description`; its labels are any C16 labels, in table order. It normalizes to a `ChoiceScoring`
router definition `D` whose C3 revision is the profile's revision. A fixed profile keeps exactly
its keys, its three labels and its legacy revision bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from screamingface_engine.world.config import AigatewaySection, WorldConfigError
from screamingface_engine.world.models.registry import decode_route_id
from screamingface_engine.world.router_spec import (
    MAX_DEFINITION_BYTES,
    REVISION_SCHEME,
    Definition,
    canonical,
    definition_revision,
    field_rule,
)

CLASSIFIER_CONTRACT = "classification-scores-v1"
UNIQUE_ARGMAX = "unique-argmax-v1"

ROUTING_LABELS = ("general", "code", "math")
"""The one label set this slice routes on (R5); a profile binds exactly these.

WHY fixed: the pilot's classifier wrapper answers these three, and a profile whose labels the
classifier never returns could route nothing. Other label sets are a later extension.
"""

MAX_TOKENS_LIMIT = 32768

_PROFILE_ID = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
_PROFILE_KEYS = frozenset({"classifier", "classifier_contract", "policy", "branches"})
# WHY no other generation parameter (R7): `openai-chat-basic-v1` carries `max_tokens` and drops
# every other field, so a bound `temperature` would be accepted here and never reach the model.
_BRANCH_KEYS = frozenset({"model", "max_tokens"})
_DYNAMIC_KEYS = _PROFILE_KEYS | {"revision_scheme", "instructions"}
_DYNAMIC_BRANCH_KEYS = _BRANCH_KEYS | {"description"}


@dataclass(frozen=True, slots=True)
class RoutingBranch:
    """One label's route: the declared model ID and its `max_tokens`."""

    label: str
    model: str
    max_tokens: int
    description: str | None = None
    """The choice description of a dynamic profile's branch; ``None`` in a fixed profile."""

    def params(self) -> tuple[tuple[str, str], ...]:
        """The explicit parameters of this branch's chat call, in call order.

        INVARIANT: the one source of both the parameters the branch call sends
        (`gateway_endpoints`) and the ones a dynamic profile's revision hashes (C2), so the
        revision always covers what is sent.
        """
        return (("max_tokens", str(self.max_tokens)), ("web_search", "false"))


@dataclass(frozen=True, slots=True)
class RoutingProfile:
    """One parsed profile, with its branches in file order and its revision.

    `revision` is `sha256:` and the hex digest of the canonical JSON of the bound values, so it
    changes with any binding and with nothing else.
    """

    id: str
    classifier: str
    classifier_contract: str
    policy: str
    branches: tuple[RoutingBranch, ...]
    revision: str
    revision_scheme: str | None = None
    """`router-definition-v1` for a dynamic profile; ``None`` keeps the legacy revision."""
    instructions: str | None = None
    """The choice instructions of a dynamic profile; ``None`` in a fixed profile."""

    @property
    def dynamic(self) -> bool:
        return self.revision_scheme is not None


def parse_routing(raw: object, section: AigatewaySection | None) -> Mapping[str, RoutingProfile]:
    """Validate the `[routing]` table against the world's declared routes. Fail-fast.

    Raises:
        WorldConfigError: any of rules R1 to R7 of spec 3.1.
    """
    if raw is None:
        return {}
    if section is None:
        raise WorldConfigError("[routing] requires [aigateway]: a profile routes to its models")
    if not isinstance(raw, Mapping):
        raise WorldConfigError("[routing] must be a table")
    unknown = sorted(set(map(str, raw)) - {"profiles"})
    if unknown:
        raise WorldConfigError(f"[routing] has unknown key(s) {unknown} (expected ['profiles'])")
    profiles = raw.get("profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        raise WorldConfigError("[routing] needs a non-empty `profiles` table")
    routes = frozenset(model.id for model in section.models)
    return {
        str(profile_id): _profile(str(profile_id), table, routes)
        for profile_id, table in profiles.items()
    }


def _profile(profile_id: str, raw: object, routes: Collection[str]) -> RoutingProfile:
    if _PROFILE_ID.fullmatch(profile_id) is None:
        raise WorldConfigError(
            f"routing profile ID {profile_id!r} must match {_PROFILE_ID.pattern!r}"
        )
    where = f"[routing.profiles.{profile_id}]"
    # WHY `revision_scheme` decides the form: it is the one key only a dynamic profile has, so
    # every other key is then checked against that form's exact set and a mix fails, named.
    dynamic = isinstance(raw, Mapping) and "revision_scheme" in raw
    table = _require_table(where, raw, _DYNAMIC_KEYS if dynamic else _PROFILE_KEYS)
    classifier = table["classifier"]
    provider, _, alias = str(classifier).partition("/")
    if not (isinstance(classifier, str) and provider and alias):
        raise WorldConfigError(f'{where} classifier must be a "<provider>/<alias>" model ID')
    _require_value(where, table, "classifier_contract", CLASSIFIER_CONTRACT)
    _require_value(where, table, "policy", UNIQUE_ARGMAX)
    branches = _branches(profile_id, table["branches"], routes, dynamic=dynamic)
    if dynamic:
        return _dynamic_profile(profile_id, table, classifier, branches)
    return RoutingProfile(
        id=profile_id,
        classifier=classifier,
        classifier_contract=CLASSIFIER_CONTRACT,
        policy=UNIQUE_ARGMAX,
        branches=branches,
        revision=_revision(profile_id, classifier, branches),
    )


def _branches(
    profile_id: str, table: object, routes: Collection[str], *, dynamic: bool
) -> tuple[RoutingBranch, ...]:
    where = f"[routing.profiles.{profile_id}.branches]"
    if not isinstance(table, Mapping):
        raise WorldConfigError(f"{where} must be a table")
    labels = set(map(str, table))
    # WHY only the fixed form pins its labels: a dynamic profile's labels are checked as C16
    # labels with its normalized definition (`_dynamic_profile`).
    if not dynamic and labels != set(ROUTING_LABELS):
        raise WorldConfigError(
            f"{where} must bind exactly the labels {list(ROUTING_LABELS)}; "
            f"missing {sorted(set(ROUTING_LABELS) - labels)}, "
            f"unknown {sorted(labels - set(ROUTING_LABELS))}"
        )
    return tuple(
        _branch(
            f"[routing.profiles.{profile_id}.branches.{label}]",
            str(label),
            entry,
            routes,
            dynamic=dynamic,
        )
        for label, entry in table.items()
    )


def _branch(
    where: str, label: str, raw: object, routes: Collection[str], *, dynamic: bool
) -> RoutingBranch:
    table = _require_table(where, raw, _DYNAMIC_BRANCH_KEYS if dynamic else _BRANCH_KEYS)
    model = table["model"]
    # WHY a route of this world: the branch is called as the ordinary chat route `/<model>`, and
    # a model ID without a provider prefix names no Gateway target a profile could bind.
    if not (isinstance(model, str) and model in routes and "/" in model):
        raise WorldConfigError(
            f"{where} model must be the ID of a declared, provider-prefixed model route"
        )
    max_tokens = table["max_tokens"]
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or not 1 <= max_tokens <= MAX_TOKENS_LIMIT
    ):
        raise WorldConfigError(f"{where} max_tokens must be an integer in [1, {MAX_TOKENS_LIMIT}]")
    description = _text(where, table, "description") if dynamic else None
    return RoutingBranch(label=label, model=model, max_tokens=max_tokens, description=description)


def _dynamic_profile(
    profile_id: str,
    table: Mapping[str, object],
    classifier: str,
    branches: tuple[RoutingBranch, ...],
) -> RoutingProfile:
    """The dynamic form: its C2 normalization, checked against C16, and its C3 revision."""
    where = f"[routing.profiles.{profile_id}]"
    _require_value(where, table, "revision_scheme", REVISION_SCHEME)
    instructions = _text(where, table, "instructions")
    definition = normalized_definition(classifier, instructions, branches)
    encoded = canonical(definition)
    if len(encoded) > MAX_DEFINITION_BYTES:
        raise WorldConfigError(
            f"{where} normalizes to more than {MAX_DEFINITION_BYTES} bytes of canonical JSON (C16)"
        )
    try:
        Definition.model_validate_json(encoded)
    except ValidationError as exc:
        # WHY translated: the operator wrote branches and instructions, not the normalized `D`;
        # the rule names a branch by its position, never by a value.
        rule = field_rule(exc).replace("classifier.choice.", "", 1)
        rule = rule.replace("candidates", "branches", 1)
        raise WorldConfigError(f"{where} breaks a router definition rule at {rule}") from None
    return RoutingProfile(
        id=profile_id,
        classifier=classifier,
        classifier_contract=CLASSIFIER_CONTRACT,
        policy=UNIQUE_ARGMAX,
        branches=branches,
        revision=definition_revision(definition),
        revision_scheme=REVISION_SCHEME,
        instructions=instructions,
    )


def normalized_definition(
    classifier: str, instructions: str, branches: tuple[RoutingBranch, ...]
) -> dict[str, object]:
    """The C2 `ChoiceScoring` definition `D` of a dynamic profile, candidates in table order.

    INVARIANT: each Model is the canonical Gateway ID with `prompt: null` and exactly the
    parameters its branch call sends, so the revision covers the call (C2, C3).
    """
    return {
        "classifier": {
            "source": "scoring",
            "model": classifier,
            "contract": CLASSIFIER_CONTRACT,
            "input": "choice",
            "instructions": instructions,
        },
        "policy": {"type": UNIQUE_ARGMAX},
        "candidates": [
            {
                "label": branch.label,
                "description": branch.description,
                "model": {
                    "model": decode_route_id(branch.model),
                    "prompt": None,
                    "params": dict(branch.params()),
                },
            }
            for branch in branches
        ],
        "default": None,
        "synthesizer": None,
        "quorum": None,
    }


def _require_table(where: str, table: object, keys: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(table, Mapping):
        raise WorldConfigError(f"{where} must be a table")
    present = set(map(str, table))
    if present != keys:
        raise WorldConfigError(
            f"{where} must have exactly the keys {sorted(keys)}; "
            f"missing {sorted(keys - present)}, unknown {sorted(present - keys)}"
        )
    return table


def _text(where: str, table: Mapping[str, object], key: str) -> str:
    """A string value; its C16 bounds are checked with the normalized definition."""
    value = table[key]
    if not isinstance(value, str):
        raise WorldConfigError(f"{where} {key} must be a string")
    return value


def _require_value(where: str, table: Mapping[str, object], key: str, expected: str) -> None:
    if table[key] != expected:
        raise WorldConfigError(f"{where} {key} must be {expected!r}, the one this Engine supports")


def _revision(profile_id: str, classifier: str, branches: tuple[RoutingBranch, ...]) -> str:
    canonical = {
        "id": profile_id,
        "classifier": classifier,
        "classifier_contract": CLASSIFIER_CONTRACT,
        "policy": UNIQUE_ARGMAX,
        "branches": {
            branch.label: {"model": branch.model, "max_tokens": branch.max_tokens}
            for branch in branches
        },
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CLASSIFIER_CONTRACT",
    "MAX_TOKENS_LIMIT",
    "ROUTING_LABELS",
    "UNIQUE_ARGMAX",
    "RoutingBranch",
    "RoutingProfile",
    "normalized_definition",
    "parse_routing",
]
