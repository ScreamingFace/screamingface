"""Candidate Invocation adapter installed into the shared Runner URL4 world."""

from __future__ import annotations

from collections.abc import Mapping

from screamingface_engine.benchmarks.case_execution import install_case_execution
from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.benchmarks.run_logs import record_candidate_failure
from screamingface_engine.retrieval_policy import (
    RetrievalPolicy,
    RetrievalPolicyError,
    normalize_excluded_domains,
    retrieval_scope,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

_POLICY_PARAMS = frozenset({"web_search", "web_search_exclude"})


class _CandidateInvocation:
    """Evaluate linked Candidate URL4 in the same world under a narrower ambient policy."""

    __slots__ = ("_node",)

    def __init__(self, node: Url4Node) -> None:
        self._node = node

    async def __call__(self, request: Request) -> str:
        if not request.intent.strip():
            raise ResolutionError(
                "Candidate Invocation expression must be non-empty",
                code="candidate_contract_error",
                permanent=True,
            )
        policy = _candidate_policy(request.params)
        try:
            with retrieval_scope(policy):
                return await evaluate_candidate_recipe(
                    self._node,
                    request.intent,
                    request.context or "",
                )
        except RetrievalPolicyError as exc:
            record_candidate_failure()
            raise ResolutionError(
                str(exc),
                code="candidate_policy_escalation",
                permanent=True,
            ) from exc
        except Exception:
            record_candidate_failure()
            raise


def install_candidate_invocation(node: Url4Node) -> None:
    """Install the one Engine-owned Candidate adapter on ``node``."""

    node.endpoint(CANDIDATE_ROUTE)(_CandidateInvocation(node))
    install_case_execution(node)


def _candidate_policy(params: Mapping[str, str]) -> RetrievalPolicy:
    unknown = sorted(set(params) - _POLICY_PARAMS)
    if unknown:
        raise ResolutionError(
            f"unsupported Candidate policy parameter(s) {unknown}",
            code="candidate_policy_invalid",
            permanent=True,
        )
    raw_search = params.get("web_search")
    if raw_search not in {"true", "false"}:
        raise ResolutionError(
            "Candidate policy requires web_search=true or web_search=false",
            code="candidate_policy_invalid",
            permanent=True,
        )
    excluded = _excluded_domains(params.get("web_search_exclude"))
    if raw_search == "false" and excluded:
        raise ResolutionError(
            "web_search_exclude requires web_search=true",
            code="candidate_policy_invalid",
            permanent=True,
        )
    return RetrievalPolicy(web_search=raw_search == "true", excluded_domains=excluded)


def _excluded_domains(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, str):
        raise ResolutionError(
            "web_search_exclude must be a colon-separated list of bare domains",
            code="candidate_policy_invalid",
            permanent=True,
        )
    try:
        return normalize_excluded_domains(value.split(":"))
    except ValueError as exc:
        raise ResolutionError(
            "web_search_exclude must be a colon-separated list of bare domains",
            code="candidate_policy_invalid",
            permanent=True,
        ) from exc


__all__ = ["install_candidate_invocation"]
