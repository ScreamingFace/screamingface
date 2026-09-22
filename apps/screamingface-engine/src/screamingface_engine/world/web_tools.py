"""Bounded Tavily-backed web tools for model routes that declare them.

INVARIANT: exclusions are sent to Tavily and enforced again on returned search rows and direct
fetch URLs; provider-side filtering is never the sole privacy guard.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from screamingface_engine.retrieval_policy import RetrievalPolicy
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.request_parameters import WEB_SEARCH_PARAM, caller_exclusions

WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current or real-time information. Use when the answer "
                "needs up-to-date data not in your training."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and extract the main content of a web page from a known URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The absolute URL to fetch."}
                },
                "required": ["url"],
            },
        },
    },
]


class WebToolConfig(Protocol):
    """Configuration fields consumed by the tool runtime."""

    @property
    def tavily_search_depth(self) -> str: ...

    @property
    def tavily_base_url(self) -> str: ...

    @property
    def tavily_timeout_s(self) -> float: ...

    @property
    def tavily_max_results(self) -> int: ...

    @property
    def web_tool_max_calls_per_turn(self) -> int: ...

    @property
    def web_tool_max_result_bytes(self) -> int: ...


@dataclass(frozen=True, slots=True)
class WebToolRuntime:
    client: httpx.AsyncClient
    config: WebToolConfig
    api_key: str
    excluded_domains: tuple[str, ...]


def build_client(
    config: WebToolConfig,
    api_key: str | None,
    client: httpx.AsyncClient | None,
) -> tuple[httpx.AsyncClient | None, bool]:
    """Resolve the optional Tavily client and whether the world owns it."""
    if api_key is None:
        return None, False
    owns_client = client is None
    resolved = client or httpx.AsyncClient(
        base_url=config.tavily_base_url,
        timeout=config.tavily_timeout_s,
    )
    return resolved, owns_client


def build_runtime(
    *,
    spec: ModelSpec,
    wants_search: bool,
    tavily_http: httpx.AsyncClient | None,
    tavily_api_key: str | None,
    config: WebToolConfig,
    policy: RetrievalPolicy | None,
    params: Mapping[str, str],
) -> WebToolRuntime | None:
    """Resolve tool availability before the first paid model request."""
    if not wants_search or not spec.uses_web_tools:
        return None
    required = params.get(WEB_SEARCH_PARAM) == "true"
    if not required and policy is None:
        # A route whose mechanism resolves to `uses_web_tools` searches by default, so the caller
        # reaches here without writing `web_search=true`. Their exclusions still bind: an ignored
        # exclusion list is the worst failure mode for a privacy control, because it looks like
        # it was honoured.
        return (
            WebToolRuntime(tavily_http, config, tavily_api_key, caller_exclusions(params))
            if tavily_http is not None and tavily_api_key is not None
            else None
        )
    if tavily_http is None or tavily_api_key is None:
        raise RunnerRequestError(
            f"web_search=true on /{spec.id} requires a configured Tavily connection",
            code=(
                "benchmark_retrieval_unavailable"
                if policy is not None
                else "web_retrieval_unavailable"
            ),
            permanent=True,
        )
    return WebToolRuntime(tavily_http, config, tavily_api_key, caller_exclusions(params))


async def append_tool_results(
    messages: list[dict],
    tool_calls: list[dict],
    runtime: WebToolRuntime | None,
    config: WebToolConfig,
) -> None:
    """Execute a bounded tool fan-out and append one reply for every requested call."""
    served = tool_calls[: config.web_tool_max_calls_per_turn]
    dropped = tool_calls[config.web_tool_max_calls_per_turn :]
    results = await asyncio.gather(*(_execute_tool(call, runtime) for call in served))
    for call, result in zip(served, results, strict=True):
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call["function"]["name"],
                "content": truncate_tool_result(result, config.web_tool_max_result_bytes),
            }
        )
    for call in dropped:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call.get("function", {}).get("name", ""),
                "content": (
                    f"error: not executed — at most {config.web_tool_max_calls_per_turn} tool "
                    "calls are served per turn; request fewer"
                ),
            }
        )


_TOOL_TRUNCATION_MARKER = "\n…[truncated]"


def truncate_tool_result(result: str, cap: int) -> str:
    """Bound one tool result to `cap` UTF-8 bytes and mark truncation."""
    encoded = result.encode("utf-8")
    if len(encoded) <= cap:
        return result
    marker = _TOOL_TRUNCATION_MARKER.encode("utf-8")
    if len(marker) >= cap:
        return marker[:cap].decode("utf-8", errors="ignore")
    kept = encoded[: cap - len(marker)]
    return kept.decode("utf-8", errors="ignore") + _TOOL_TRUNCATION_MARKER


def _tool_args(tool_call: dict) -> tuple[str, dict | None]:
    name = tool_call.get("function", {}).get("name", "")
    raw = tool_call.get("function", {}).get("arguments")
    try:
        args = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, json.JSONDecodeError):
        return name, None
    return (name, args) if isinstance(args, dict) else (name, None)


async def _dispatch_tool(
    name: str,
    args: dict,
    runtime: WebToolRuntime | None,
) -> str:
    if name not in ("web_search", "web_fetch"):
        return f"unknown tool: {name}"
    if runtime is None:
        raise RuntimeError(f"{name} requested but Tavily is not configured")
    if name == "web_search":
        return await _tavily_search(runtime, args)
    return await _tavily_extract(runtime, args)


async def _execute_tool(tool_call: dict, runtime: WebToolRuntime | None) -> str:
    name, args = _tool_args(tool_call)
    if args is None:
        return f"invalid arguments for {name}"
    try:
        return await _dispatch_tool(name, args, runtime)
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        return f"{name} failed: {exc}"


async def _tavily_search(runtime: WebToolRuntime, args: dict) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query:
        raise ValueError("web_search requires a non-empty 'query'")
    payload: dict[str, object] = {
        "query": query,
        "search_depth": runtime.config.tavily_search_depth,
        "max_results": runtime.config.tavily_max_results,
    }
    if runtime.excluded_domains:
        payload["exclude_domains"] = list(runtime.excluded_domains)
    response = await runtime.client.post(
        "/search",
        headers=_tavily_headers(runtime.api_key),
        json=payload,
    )
    response.raise_for_status()
    data = response.json()
    results = [
        result
        for result in (data.get("results") or [])
        if isinstance(result, dict) and _search_result_allowed(result, runtime.excluded_domains)
    ]
    if not results:
        return "no results"
    return "\n\n".join(
        f"Title: {r.get('title', '')}\nURL: {r.get('url', '')}\nContent: {r.get('content', '')}"
        for r in results
        if isinstance(r, dict)
    )


async def _tavily_extract(runtime: WebToolRuntime, args: dict) -> str:
    url = args.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("web_fetch requires a non-empty 'url'")
    if _is_blocked(url, runtime.excluded_domains):
        raise ValueError("web_fetch URL is blocked by Benchmark retrieval policy")
    response = await runtime.client.post(
        "/extract",
        headers=_tavily_headers(runtime.api_key),
        json={"urls": url, "format": "markdown", "extract_depth": "advanced"},
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results") or []
    if results and isinstance(results[0], dict) and results[0].get("raw_content"):
        return str(results[0]["raw_content"])
    failed = data.get("failed_results") or []
    if failed and isinstance(failed[0], dict):
        failed_url = failed[0].get("url", url)
        failed_error = failed[0].get("error", "unknown")
        return f"{failed_url} could not be extracted: {failed_error}"
    return "no content extracted"


def _search_result_allowed(result: Mapping[str, object], exclusions: Sequence[str]) -> bool:
    if not exclusions:
        return True
    url = result.get("url")
    return isinstance(url, str) and not _is_blocked(url, exclusions)


def _is_blocked(url: str, exclusions: Sequence[str]) -> bool:
    """Match a bare-domain exclusion against its host and every subdomain."""
    if not exclusions:
        return False
    normalized_host: str | None = None
    try:
        parsed = httpx.URL(url if "://" in url else f"https://{url}")
        normalized_host = parsed.raw_host.decode("ascii").lower().rstrip(".")
    except (httpx.InvalidURL, UnicodeDecodeError):
        pass
    # Fail closed on a host this comparison cannot decide. An unparsed host is the obvious case;
    # a percent-encoded one is the subtle one — httpx leaves the authority encoded, so `ev%69l.com`
    # would not match `evil.com` here and would then be handed to a fetcher that decodes it. A
    # real host never carries a literal `%`, so refusing one costs nothing.
    if not normalized_host or "%" in normalized_host:
        return True
    return any(
        normalized_host == domain or normalized_host.endswith(f".{domain}") for domain in exclusions
    )


def _tavily_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}
