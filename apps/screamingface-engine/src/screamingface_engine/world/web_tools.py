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

from screamingface_engine.capture_outcomes import (
    REPLAY_MISS,
    REPLAY_UNAVAILABLE,
    CaptureOutcome,
    current_capture_tally,
    record_capture_outcome,
    replay_refusal_code,
    request_digest,
)
from screamingface_engine.retrieval_policy import RetrievalPolicy
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.request_parameters import WEB_SEARCH_PARAM, caller_exclusions
from screamingface_engine.world.tavily_retrieval_cache import (
    TavilyLookup,
    TavilyRetrievalCache,
    fetch_description,
    search_description,
)

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


# WHY its own timeout (like the Tavily cache's): the frozen copy is a side lane, so a slow gateway
# must cost seconds, not a Tavily call's 30 s.
_COPY_TIMEOUT = httpx.Timeout(5.0)


@dataclass(frozen=True, slots=True)
class FrozenToolResults:
    """The frozen copy's tool-result routes on the connector's gateway client (design §4.3).

    FEATURE: OME-1307 — capture mode posts every result string the model reads; replay mode reads
    it back and never calls Tavily. ``headers`` are the chat calls' identity headers.
    """

    client: httpx.AsyncClient
    headers: Mapping[str, str]
    copy_id: str
    replay: bool

    async def store(self, description: Mapping[str, object], result: str) -> str:
        """Post one result to the copy. Returns ``stored`` or ``failed``; never raises."""
        try:
            response = await self.client.post(
                f"/v1/frozen-copies/{self.copy_id}/tool-results",
                headers=self.headers,
                json={"description": description, "result": result},
                timeout=_COPY_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
            outcome = body.get("outcome") if isinstance(body, dict) else None
            return "stored" if outcome == "stored" else "failed"
        except (httpx.HTTPError, ValueError):
            return "failed"

    async def lookup(self, description: Mapping[str, object]) -> str:
        """Read the result the original run's model read, in capture order for repeated requests.

        INVARIANT: raises a `RunnerRequestError`, which `_execute_tool` lets through. Any other
        failure would become a "… failed: …" string the model reads and carries on from, and a
        replay that carried on from a made-up tool result would be exact in name only.
        """
        digest = request_digest(description)
        tally = current_capture_tally()
        occurrence = 0 if tally is None else tally.occurrence("tool", digest)
        try:
            response = await self.client.post(
                f"/v1/frozen-copies/{self.copy_id}/tool-results/lookup",
                headers={**self.headers, "X-AIGW-Replay-Occurrence": str(occurrence)},
                json={"description": description},
                timeout=_COPY_TIMEOUT,
            )
            payload = response.json() if response.content else None
            result = payload.get("result") if isinstance(payload, dict) else None
            if response.status_code == 200 and isinstance(result, str):
                if tally is not None:
                    tally.answered("tool", digest)
                return result
            # A 404 is the copy saying it cannot answer; any other failure is a gateway that did
            # not answer at all, which a retry may fix.
            code = (
                (replay_refusal_code(404, payload) or REPLAY_MISS)
                if response.status_code == 404
                else None
            )
        except (httpx.HTTPError, ValueError):
            code = None
        if code == REPLAY_MISS:
            raise RunnerRequestError(
                "the frozen copy holds no result for a web tool call of this replay",
                code=REPLAY_MISS,
                permanent=True,
            )
        raise RunnerRequestError(
            "the frozen copy cannot serve a web tool call of this replay",
            code=REPLAY_UNAVAILABLE,
            permanent=code is not None,
        )


@dataclass(frozen=True, slots=True)
class WebToolRuntime:
    # `None` only in a replay, which never calls Tavily and so needs neither (OME-1307).
    client: httpx.AsyncClient | None
    config: WebToolConfig
    api_key: str | None
    excluded_domains: tuple[str, ...]
    # FEATURE: OME-1045 — the gateway retrieval cache. `None` leaves every Tavily call as it was.
    cache: TavilyRetrievalCache | None = None
    # FEATURE: OME-1307 — the run's frozen copy: set in capture mode and in replay mode.
    frozen: FrozenToolResults | None = None


def tavily_key(raw: str | None) -> str | None:
    """The Tavily key a world uses, or ``None`` when web tools are off.

    INVARIANT (FX-68): the ONE normalization of the key — a blank value is no key. The connector
    builds its Tavily client from this, and the run's world line derives ``web_tools`` from it,
    so the line can never say "enabled" for a world that has no client.
    """
    return (raw or "").strip() or None


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
    cache: TavilyRetrievalCache | None = None,
    frozen: FrozenToolResults | None = None,
) -> WebToolRuntime | None:
    """Resolve tool availability before the first paid model request."""
    if not wants_search or not spec.uses_web_tools:
        return None
    runtime = WebToolRuntime(
        tavily_http, config, tavily_api_key, caller_exclusions(params), cache, frozen
    )
    # A replay never calls Tavily, so it needs no credential — but the model must be offered the
    # same tools the original run was, or its request would key differently and miss.
    configured = (frozen is not None and frozen.replay) or (
        tavily_http is not None and tavily_api_key is not None
    )
    required = params.get(WEB_SEARCH_PARAM) == "true"
    if not required and policy is None:
        # A route whose mechanism resolves to `uses_web_tools` searches by default, so the caller
        # reaches here without writing `web_search=true`. Their exclusions still bind: an ignored
        # exclusion list is the worst failure mode for a privacy control, because it looks like
        # it was honoured.
        return runtime if configured else None
    if not configured:
        raise RunnerRequestError(
            f"web_search=true on /{spec.id} requires a configured Tavily connection",
            code=(
                "benchmark_retrieval_unavailable"
                if policy is not None
                else "web_retrieval_unavailable"
            ),
            permanent=True,
        )
    return runtime


async def append_tool_results(
    messages: list[dict],
    tool_calls: list[dict],
    runtime: WebToolRuntime | None,
    config: WebToolConfig,
) -> None:
    """Execute a bounded tool fan-out and append one reply for every requested call."""
    served = tool_calls[: config.web_tool_max_calls_per_turn]
    dropped = tool_calls[config.web_tool_max_calls_per_turn :]
    results = await asyncio.gather(*(_executed(call, runtime) for call in served))
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


async def _executed(tool_call: dict, runtime: WebToolRuntime | None) -> str:
    """One tool call's result string, as the model reads it, in the run's frozen-copy mode.

    Replay reads EVERY result from the copy, failure strings included: they came from Tavily or
    from the run's own checks, and the copy holds what the model saw. Capture posts the result
    BEFORE truncation (the caller truncates), so the copy holds exactly what the tool returned —
    success, "no results" and failure strings alike (design §5.2).
    """
    if runtime is None or runtime.frozen is None:
        return await _execute_tool(tool_call, runtime)
    name, args = _tool_args(tool_call)
    description = _tool_description(name, args, runtime)
    if runtime.frozen.replay:
        return await runtime.frozen.lookup(description)
    result = await _execute_tool(tool_call, runtime)
    await _capture_result(runtime.frozen, description, result)
    return result


async def _capture_result(
    frozen: FrozenToolResults, description: Mapping[str, object], result: str
) -> None:
    """Post one result to the copy and record the outcome. Only a cancellation escapes (D1)."""
    digest = request_digest(description)
    try:
        status = await frozen.store(description, result)
    except BaseException:
        # A cancelled store left no entry the replay could read (D1).
        record_capture_outcome(CaptureOutcome("tool", "error", digest))
        raise
    record_capture_outcome(
        CaptureOutcome("tool", "stored" if status == "stored" else "failed", digest)
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


def _tool_description(name: str, args: dict | None, runtime: WebToolRuntime) -> dict[str, object]:
    """The tool call as the frozen copy keys it: the description the Tavily cache uses.

    A call with no description builder (an unknown tool, arguments that are not an object, or a
    search without a text query) is described by its name and arguments.
    """
    query = args.get("query") if args is not None else None
    url = args.get("url") if args is not None else None
    if name == "web_search" and isinstance(query, str):
        return search_description(
            query,
            runtime.config.tavily_search_depth,
            runtime.config.tavily_max_results,
            runtime.excluded_domains,
        )
    if name == "web_fetch" and isinstance(url, str):
        return fetch_description(url, runtime.excluded_domains)
    return {"tool": name, "arguments": args}


async def _tavily_search(runtime: WebToolRuntime, args: dict) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query:
        raise ValueError("web_search requires a non-empty 'query'")
    description = search_description(
        query,
        runtime.config.tavily_search_depth,
        runtime.config.tavily_max_results,
        runtime.excluded_domains,
    )
    lookup = await _cache_lookup(runtime, description)
    if lookup.status == "hit" and lookup.result is not None:
        return lookup.result
    payload: dict[str, object] = {
        "query": query,
        "search_depth": runtime.config.tavily_search_depth,
        "max_results": runtime.config.tavily_max_results,
    }
    if runtime.excluded_domains:
        payload["exclude_domains"] = list(runtime.excluded_domains)
    client, api_key = _tavily_access(runtime)
    response = await client.post("/search", headers=_tavily_headers(api_key), json=payload)
    response.raise_for_status()
    data = response.json()
    results = [
        result
        for result in (data.get("results") or [])
        if isinstance(result, dict) and _search_result_allowed(result, runtime.excluded_domains)
    ]
    if not results:
        return "no results"
    text = "\n\n".join(
        f"Title: {r.get('title', '')}\nURL: {r.get('url', '')}\nContent: {r.get('content', '')}"
        for r in results
        if isinstance(r, dict)
    )
    await _cache_fill(runtime, lookup, description, text)
    return text


async def _tavily_extract(runtime: WebToolRuntime, args: dict) -> str:
    url = args.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("web_fetch requires a non-empty 'url'")
    if _is_blocked(url, runtime.excluded_domains):
        raise ValueError("web_fetch URL is blocked by Benchmark retrieval policy")
    description = fetch_description(url, runtime.excluded_domains)
    lookup = await _cache_lookup(runtime, description)
    if lookup.status == "hit" and lookup.result is not None:
        return lookup.result
    client, api_key = _tavily_access(runtime)
    response = await client.post(
        "/extract",
        headers=_tavily_headers(api_key),
        json={"urls": url, "format": "markdown", "extract_depth": "advanced"},
    )
    response.raise_for_status()
    text, extracted = _extraction(response.json(), url)
    if extracted:
        await _cache_fill(runtime, lookup, description, text)
    return text


def _tavily_access(runtime: WebToolRuntime) -> tuple[httpx.AsyncClient, str]:
    """The Tavily client and key. A replay may have neither, and never gets this far."""
    if runtime.client is None or runtime.api_key is None:
        raise RuntimeError("Tavily is not configured")
    return runtime.client, runtime.api_key


def _extraction(data: dict, url: str) -> tuple[str, bool]:
    """The tool result for one extract response, and whether it is a success worth caching."""
    results = data.get("results") or []
    if results and isinstance(results[0], dict) and results[0].get("raw_content"):
        return str(results[0]["raw_content"]), True
    failed = data.get("failed_results") or []
    if failed and isinstance(failed[0], dict):
        failed_url = failed[0].get("url", url)
        failed_error = failed[0].get("error", "unknown")
        return f"{failed_url} could not be extracted: {failed_error}", False
    return "no content extracted", False


async def _cache_lookup(runtime: WebToolRuntime, description: Mapping[str, object]) -> TavilyLookup:
    """Ask the gateway cache first. With no cache configured the answer is a `bypass`, so the
    caller calls Tavily and never fills — byte-identical to a world without the cache."""
    if runtime.cache is None:
        return TavilyLookup("bypass", None, {})
    return await runtime.cache.lookup(description)


async def _cache_fill(
    runtime: WebToolRuntime,
    lookup: TavilyLookup,
    description: Mapping[str, object],
    result: str,
) -> str | None:
    """Store a result just paid for. Returns the gateway outcome, or `None` when no fill was made
    or it failed.

    INVARIANT: only a `miss` is followed by a fill. A `bypass` means the gateway store failed to
    read (or the lookup itself failed), and a write would go to the store that just failed.
    """
    if runtime.cache is not None and lookup.status == "miss":
        return await runtime.cache.fill(description, result)
    return None


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
