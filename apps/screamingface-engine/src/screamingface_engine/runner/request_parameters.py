"""Validate URL4 model-call parameters and apply an active retrieval ceiling.

INVARIANT: a nested call may narrow its active retrieval policy, but it cannot enable retrieval
or remove excluded domains forbidden by its parent invocation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from screamingface_engine.retrieval_policy import RetrievalPolicy, normalize_excluded_domains
from screamingface_engine.runner.errors import RunnerRequestError
from screamingface_engine.world_config import ModelSpec

WEB_SEARCH_PARAM = "web_search"
WEB_SEARCH_EXCLUDE_PARAM = "web_search_exclude"
_INTERPRETED_PARAMS = frozenset({WEB_SEARCH_PARAM, WEB_SEARCH_EXCLUDE_PARAM})
_RUNNER_OWNED_FIELDS = frozenset(
    {"model", "messages", "tools", "tool_choice", "stream", "web_search_excluded_domains"}
)


def apply_retrieval_policy(
    params: Mapping[str, str],
    policy: RetrievalPolicy | None,
) -> dict[str, str]:
    """Apply the active Benchmark ceiling while allowing a nested call to narrow it."""
    selected = dict(params)
    if policy is None:
        return selected
    if not policy.web_search:
        selected[WEB_SEARCH_PARAM] = "false"
        selected.pop(WEB_SEARCH_EXCLUDE_PARAM, None)
        return selected
    if selected.get(WEB_SEARCH_PARAM) != "false":
        selected[WEB_SEARCH_PARAM] = "true"
        excluded = {*policy.excluded_domains, *caller_exclusions(selected)}
        if excluded:
            selected[WEB_SEARCH_EXCLUDE_PARAM] = ":".join(sorted(excluded))
    return selected


def wants_web_search(params: Mapping[str, str], spec: ModelSpec) -> bool:
    """Resolve an optional URL4 search toggle against the declared route capabilities."""
    declared = spec.web_search
    raw = params.get(WEB_SEARCH_PARAM)
    if raw is None:
        return declared
    if raw not in {"true", "false"}:
        raise RunnerRequestError(
            "web_search must be true or false",
            code="web_retrieval_invalid",
            permanent=True,
        )
    wanted = raw == "true"
    if wanted and not declared:
        raise RunnerRequestError(
            f"web_search=true but route /{spec.id} declares web_search = false",
            code="web_retrieval_unavailable",
            permanent=True,
        )
    return wanted


def caller_exclusions(params: Mapping[str, str]) -> tuple[str, ...]:
    """Decode and normalize the URL4 form of the caller's exclusion list."""
    raw = params.get(WEB_SEARCH_EXCLUDE_PARAM)
    if not raw:
        return ()
    try:
        return normalize_excluded_domains(raw.split(":"))
    except ValueError as exc:
        raise RunnerRequestError(
            "web_search_exclude must be a colon-separated list of bare domains",
            code="web_retrieval_invalid",
            permanent=True,
        ) from exc


ANSWER_SEED_PARAM = "seed"
"""The wire name of the sampling seed — the same param the draco judge already stamps per pass,
and a standard aigateway parameter (OME-585), so discovery/preflight admit it unchanged."""


def apply_answer_seed(params: Mapping[str, str], answer_seed: str | None) -> Mapping[str, str]:
    """Stamp the run's declared answer seed onto one model call's params, if it declared one.

    FEATURE: answer seeds (OME-1038) — N seeded runs are N labelled samples, so a score can
    be published as mean ± CI and any sitting replayed.

    INVARIANT: ``None`` is a NO-OP that returns ``params`` itself, not a copy — a run that
    declared nothing must produce byte-identical egress to today's, which is what keeps every
    request-keyed replay fixture valid.

    INVARIANT: a call that states its own ``seed`` always wins. The draco judge pins one
    stable seed per pass for independent cache slots; an ambient seed overwriting those would
    silently re-key the judge cache and change grading identity.
    """
    if answer_seed is None or ANSWER_SEED_PARAM in params:
        return params
    return {**params, ANSWER_SEED_PARAM: answer_seed}


def model_params(params: Mapping[str, str]) -> dict[str, object]:
    """Project URL4 parameters into the model request without Runner-owned fields."""
    selected = {key: value for key, value in params.items() if key not in _INTERPRETED_PARAMS}
    owned = sorted(set(selected) & _RUNNER_OWNED_FIELDS)
    if owned:
        raise RunnerRequestError(
            f"expression may not set {', '.join(owned)} — owned by the Runner's declared world",
            code="model_parameter_invalid",
            permanent=True,
        )
    return {key: _coerce_param(value) for key, value in selected.items()}


def _coerce_param(value: str) -> object:
    try:
        return json.loads(value)
    except ValueError:
        return value
