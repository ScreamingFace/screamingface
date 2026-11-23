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
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from screamingface_engine.world.config import AigatewaySection, WorldConfigError

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


@dataclass(frozen=True, slots=True)
class RoutingBranch:
    """One label's route: the declared model ID and its `max_tokens`."""

    label: str
    model: str
    max_tokens: int


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
    table = _require_table(where, raw, _PROFILE_KEYS)
    classifier = table["classifier"]
    provider, _, alias = str(classifier).partition("/")
    if not (isinstance(classifier, str) and provider and alias):
        raise WorldConfigError(f'{where} classifier must be a "<provider>/<alias>" model ID')
    _require_value(where, table, "classifier_contract", CLASSIFIER_CONTRACT)
    _require_value(where, table, "policy", UNIQUE_ARGMAX)
    branches = _branches(profile_id, table["branches"], routes)
    return RoutingProfile(
        id=profile_id,
        classifier=classifier,
        classifier_contract=CLASSIFIER_CONTRACT,
        policy=UNIQUE_ARGMAX,
        branches=branches,
        revision=_revision(profile_id, classifier, branches),
    )


def _branches(profile_id: str, table: object, routes: Collection[str]) -> tuple[RoutingBranch, ...]:
    where = f"[routing.profiles.{profile_id}.branches]"
    if not isinstance(table, Mapping):
        raise WorldConfigError(f"{where} must be a table")
    labels = set(map(str, table))
    if labels != set(ROUTING_LABELS):
        raise WorldConfigError(
            f"{where} must bind exactly the labels {list(ROUTING_LABELS)}; "
            f"missing {sorted(set(ROUTING_LABELS) - labels)}, "
            f"unknown {sorted(labels - set(ROUTING_LABELS))}"
        )
    return tuple(
        _branch(f"[routing.profiles.{profile_id}.branches.{label}]", str(label), entry, routes)
        for label, entry in table.items()
    )


def _branch(where: str, label: str, raw: object, routes: Collection[str]) -> RoutingBranch:
    table = _require_table(where, raw, _BRANCH_KEYS)
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
    return RoutingBranch(label=label, model=model, max_tokens=max_tokens)


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
    "parse_routing",
]
