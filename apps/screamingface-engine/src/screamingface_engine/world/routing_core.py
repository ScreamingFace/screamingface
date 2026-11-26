"""The shared Engine routing application boundary (Unit 5.2, contracts C2, C4, C7).

FEATURE: Router Recipe extension. Named profiles (`/route-answer`) and the Router DAG are two
adapters over one routing core: the per-caller metadata and access preflight lives here once,
the pure C6 decision in `routing_policy`, the strict C2/C3 codec in `router_spec`. Each adapter
keeps its own presentation: the profile maps a `PreflightRefusal` to its routing codes and
messages, the Router ADMIT to its refusal document.

WHY no url4 import: like `routing.py`, this module is not on the url4 allowlist
(`tests/unit/test_url4_executor.py`); it reads metadata over the world's own Gateway client.

INVARIANT: no inference. Every read is a metadata GET with the caller's identity, and a refusal
is decided only once every target was read, so a caller who cannot use one target learns
nothing about the others; a missing Connection is named before a misfit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from screamingface_engine.router_vocabulary import strict_json
from screamingface_engine.world.classifier_limits import (
    ChoiceRequest,
    TextRequest,
    choice_fits,
    read_capability,
    text_fits,
)
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.parameter_contract import value_fits
from screamingface_engine.world.request_parameters import model_params

CLASSIFIER_DETAILS_PATH = "/v1/classifiers/details"
MODEL_PARAMETERS_PATH = "/v1/model-parameters"

Refusal = Literal["unavailable", "failed", "not_found", "connection_missing", "mismatch"]

# WHY `auth_required` alone among 401s: it is the Gateway's answer for a visible target whose
# Connection must sign in again; any other 401 says the request itself was not accepted.
_REAUTH_CODE = "auth_required"

# (usable, fits) of a visible target whose Connection cannot run: its contract is unread, so it
# is not held against the caller's routing.
_NOT_CONNECTED = (False, True)


class PreflightRefusal(Exception):
    """Why the preflight refused, with no target named; each adapter presents it.

    ``unavailable`` is transient (a read could not complete); every other kind is permanent.
    """

    def __init__(self, kind: Refusal) -> None:
        super().__init__(kind)
        self.kind: Refusal = kind

    @property
    def permanent(self) -> bool:
        return self.kind != "unavailable"


@dataclass(frozen=True, slots=True)
class ClassifierTarget:
    """A scoring classifier to read: its ID, its result contract and the input it must take."""

    model: str
    contract: str
    choice: ChoiceRequest | None = None
    """The C7 choice input it must take; ``None`` keeps the scalar check (fixed profiles)."""
    text: TextRequest | None = None
    """The C7 scalar input a Router's fixed-label classifier must take (C4 ADMIT)."""


@dataclass(frozen=True, slots=True)
class ModelTarget:
    """A chat Model to read: its canonical Gateway ID and what its call sends.

    A named profile passes ``max_tokens`` (its shipped check); Router ADMIT passes the call's
    ``params`` exactly as written, checked against the whole parameter contract (C4).
    """

    model: str
    max_tokens: int | None = None
    params: tuple[tuple[str, str], ...] = ()


async def preflight(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    classifier: ClassifierTarget | None,
    models: Sequence[ModelTarget],
) -> None:
    """Read the classifier's details, then each Model's parameters, in order; no inference.

    Raises:
        PreflightRefusal: ``unavailable``, ``failed`` or ``not_found`` at the first read that
            gives one; else ``connection_missing``, then ``mismatch``, once all are read.
    """
    findings: list[tuple[bool, bool]] = []
    if classifier is not None:
        details = await _read(client, headers, CLASSIFIER_DETAILS_PATH, classifier.model)
        findings.append(_NOT_CONNECTED if details is None else _classifier(details, classifier))
    for target in models:
        document = await _read(client, headers, MODEL_PARAMETERS_PATH, target.model)
        findings.append(_NOT_CONNECTED if document is None else _model(document, target))
    if not all(usable for usable, _ in findings):
        raise PreflightRefusal("connection_missing")
    if not all(fits for _, fits in findings):
        raise PreflightRefusal("mismatch")


def _classifier(details: dict[str, Any], target: ClassifierTarget) -> tuple[bool, bool]:
    """(usable, fits) of the classifier's details document."""
    if details.get("id") != target.model:
        raise PreflightRefusal("failed")
    access, contract = details.get("execution_access"), details.get("result_contract")
    if not (isinstance(access, str) and isinstance(contract, str)):
        raise PreflightRefusal("failed")
    return access == "configured", contract == target.contract and _takes(details, target)


def _takes(details: dict[str, Any], target: ClassifierTarget) -> bool:
    """Whether the classifier takes the target's input under its published C7 limits.

    WHY a scalar target reads no limits: a fixed profile keeps today's check, and C7 lets a
    text-only classifier publish none (`limits: null`).
    WHY an invalid row only misfits: a strict C7 reader treats it as unusable, never repaired.
    """
    request = target.choice or target.text
    if request is None:
        return True
    capability = read_capability(details.get("input_contracts"), details.get("limits"))
    if isinstance(request, ChoiceRequest):
        return capability is not None and choice_fits(capability, request)
    return capability is not None and text_fits(capability, request)


def _model(document: dict[str, Any], target: ModelTarget) -> tuple[bool, bool]:
    """(usable, fits) of one Model's parameter document."""
    identity, context, parameters = (
        document.get("model"),
        document.get("context"),
        document.get("parameters"),
    )
    if not (
        isinstance(identity, dict)
        and identity.get("id") == target.model
        and isinstance(context, dict)
        and isinstance(context.get("execution_access"), str)
        and isinstance(parameters, dict)
    ):
        raise PreflightRefusal("failed")
    usable = context["execution_access"] == "configured"
    fits = target.max_tokens is None or _admits(parameters.get("max_tokens"), target.max_tokens)
    return usable, fits and _params_fit(parameters, target.params)


def _params_fit(parameters: dict[str, Any], params: tuple[tuple[str, str], ...]) -> bool:
    """Whether every value the call sends fits its published row (C4), typed as it is sent.

    WHY `model_params`: it is the call's own projection, so an Engine-interpreted param never
    needs a row and a Runner-owned field misfits here exactly as the call would refuse it.
    """
    try:
        values = model_params(dict(params))
    except RunnerRequestError:
        return False
    return all(value_fits(parameters.get(name), value) for name, value in values.items())


async def _read(
    client: httpx.AsyncClient, headers: dict[str, str], path: str, model: str
) -> dict[str, Any] | None:
    """One metadata document, or ``None`` for a visible target whose Connection cannot run."""
    try:
        response = await client.get(path, params={"model": model}, headers=headers)
    except httpx.TransportError:
        raise PreflightRefusal("unavailable") from None
    except httpx.HTTPError:
        raise PreflightRefusal("failed") from None
    return _document(response)


def _document(response: httpx.Response) -> dict[str, Any] | None:
    status = response.status_code
    if status == 429 or 500 <= status < 600:
        raise PreflightRefusal("unavailable")
    if status in (400, 404):
        # WHY one kind: the Gateway answers both for a target the caller may not see.
        raise PreflightRefusal("not_found")
    if status == 409 or (status == 401 and _detail_code(response) == _REAUTH_CODE):
        return None
    if status != 200:
        raise PreflightRefusal("failed")
    try:
        # INVARIANT: strict JSON, so a repeated key is never settled by "last wins"
        # and a non-finite number never reads as a limit; `strict_json` maps deep nesting too.
        document = strict_json(response.content.decode("utf-8"))
    except ValueError:
        raise PreflightRefusal("failed") from None
    if not isinstance(document, dict):
        raise PreflightRefusal("failed")
    return document


def _detail_code(response: httpx.Response) -> object:
    try:
        payload = response.json()
    except (ValueError, RecursionError):
        return None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return detail.get("code") if isinstance(detail, dict) else None


def _admits(rule: object, value: int) -> bool:
    """Whether a published `max_tokens` rule accepts ``value``: enabled, integer, in bounds."""
    if not isinstance(rule, dict):
        return False
    gateway, schema = rule.get("gateway"), rule.get("schema")
    return (
        isinstance(gateway, dict)
        and gateway.get("status") == "enabled"
        and isinstance(schema, dict)
        and _schema_admits(schema, value)
    )


def _schema_admits(schema: dict[str, Any], value: int) -> bool:
    kinds = schema.get("type")
    if not (kinds == "integer" or (isinstance(kinds, list) and "integer" in kinds)):
        return False
    low, high = schema.get("minimum"), schema.get("maximum")
    return (low is None or (_number(low) and low <= value)) and (
        high is None or (_number(high) and value <= high)
    )


def _number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float)


__all__ = [
    "CLASSIFIER_DETAILS_PATH",
    "MODEL_PARAMETERS_PATH",
    "ClassifierTarget",
    "ModelTarget",
    "PreflightRefusal",
    "Refusal",
    "preflight",
]
