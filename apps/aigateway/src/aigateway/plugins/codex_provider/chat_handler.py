from __future__ import annotations

import json
import time
from collections.abc import AsyncIterable, Awaitable, Iterable
from inspect import isawaitable
from typing import Any, cast

import httpx
import litellm
from litellm.llms.chatgpt.common_utils import get_chatgpt_default_headers
from litellm.llms.custom_llm import CustomLLM, CustomLLMError
from litellm.types.utils import ModelResponse

from aigateway.core.content_parts import (
    ContentPart,
    RemoteImagePart,
    TextPart,
    has_media,
    parse_content,
    text_of,
    text_only,
)

CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
_PROVIDER = "codex"
_HANDLER: CodexCustomLLM | None = None
_DEFAULT_INSTRUCTIONS = "You are a helpful assistant."


def _strip_provider_prefix(model: str) -> str:
    return model.split("/", 1)[1] if model.startswith(f"{_PROVIDER}/") else model


def _input_content(message: dict[str, Any]) -> str | list[dict[str, Any]]:
    """One message's Responses-API ``content``.

    # INVARIANT: a text-only message keeps the plain-string content it always had, so its
    # payload is byte-identical to before OME-1541. Media switches that user message to typed
    # ``input_text`` / ``input_image`` / ``input_file`` parts, in content order.
    """
    role = str(message.get("role") or "user")
    parts = parse_content(message.get("content"), provider=_PROVIDER)
    if not has_media(parts):
        return text_of(parts)
    if role != "user":
        return text_only(message.get("content"), provider=_PROVIDER, role=role)
    return [_input_part(part) for part in parts]


def _input_part(part: ContentPart) -> dict[str, Any]:
    if isinstance(part, TextPart):
        return {"type": "input_text", "text": part.text}
    if isinstance(part, RemoteImagePart):
        # WHY: OpenAI fetches https image URLs itself, so the gateway passes them through.
        return _input_image(part.url, part.detail)
    if part.kind == "image":
        return _input_image(part.data_uri, part.detail)
    # WHY: the Responses API requires a filename alongside inline `file_data`.
    filename = part.filename or f"attachment.{part.mime.rsplit('/', 1)[-1]}"
    return {"type": "input_file", "filename": filename, "file_data": part.data_uri}


def _input_image(url: str, detail: str | None) -> dict[str, Any]:
    # WHY: `detail` is Required on a Responses `input_image`; an omitted Chat Completions detail
    # means "auto" there, so the default is explicit rather than left to the backend.
    return {"type": "input_image", "image_url": url, "detail": detail or "auto"}


def _build_payload(model: str, messages: list[dict[str, Any]], optional_params: dict) -> dict:
    system_messages: list[str] = []
    input_messages: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role == "system":
            text = text_only(message.get("content"), provider=_PROVIDER, role="system")
            if text:
                system_messages.append(text)
            continue
        input_messages.append({"role": role, "content": _input_content(message)})

    payload: dict[str, Any] = {
        "model": _strip_provider_prefix(model),
        "input": input_messages,
        "stream": True,
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    payload["instructions"] = (
        "\n\n".join(system_messages) if system_messages else _DEFAULT_INSTRUCTIONS
    )

    for key in ("tools", "tool_choice", "reasoning", "previous_response_id", "truncation"):
        if key in optional_params:
            payload[key] = optional_params[key]
    if "include" in optional_params and isinstance(optional_params["include"], list):
        payload["include"] = list(dict.fromkeys([*payload["include"], *optional_params["include"]]))
    return payload


def _iter_sse_data(lines: Iterable[str]):
    event_data: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            if event_data:
                data = "\n".join(event_data).strip()
                event_data = []
                if data and data != "[DONE]":
                    yield data
            continue
        if line.startswith("data:"):
            event_data.append(line.removeprefix("data:").strip())
    if event_data:
        data = "\n".join(event_data).strip()
        if data and data != "[DONE]":
            yield data


async def _aiter_sse_data(lines: AsyncIterable[str]):
    event_data: list[str] = []
    async for line in lines:
        line = line.strip()
        if not line:
            if event_data:
                data = "\n".join(event_data).strip()
                event_data = []
                if data and data != "[DONE]":
                    yield data
            continue
        if line.startswith("data:"):
            event_data.append(line.removeprefix("data:").strip())
    if event_data:
        data = "\n".join(event_data).strip()
        if data and data != "[DONE]":
            yield data


def _extract_text_from_response(response: dict[str, Any]) -> str:
    output = response.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _usage_from_response(response: dict[str, Any]) -> dict[str, int] | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    completion = usage.get("output_tokens", usage.get("completion_tokens", 0))
    try:
        prompt_tokens = int(prompt or 0)
        completion_tokens = int(completion or 0)
    except (TypeError, ValueError):
        return None
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


_TERMINAL_EVENTS = frozenset({"response.completed", "response.incomplete"})

# WHY: the Responses API reports truncation/filtering as `incomplete_details.reason`, whose
# vocabulary (`max_output_tokens` | `content_filter`, per the OpenAI SDK's `IncompleteDetails`)
# is not the OpenAI chat-completions `finish_reason` vocabulary the gateway speaks. Anything
# unrecognized degrades to "stop" rather than leaking upstream's wording into a closed field.
_INCOMPLETE_REASONS = {"max_output_tokens": "length", "content_filter": "content_filter"}


def _finish_reason(response: dict[str, Any]) -> str:
    """The chat-completions `finish_reason` for one Responses-API `Response`.

    FEATURE: OME-679 — a provider refusal must be distinguishable from a bad answer, which is
    only possible if this value is derived rather than fabricated.
    """
    details = response.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, dict) else None
    if not isinstance(reason, str):
        return "stop"
    return _INCOMPLETE_REASONS.get(reason, "stop")


def _consume_sse_event(data: str, state: dict[str, Any]) -> bool:
    try:
        event = json.loads(data)
    except json.JSONDecodeError:
        return False
    if not isinstance(event, dict):
        return False
    event_type = event.get("type")
    if event_type in {"response.failed", "error"}:
        state["error"] = event.get("error") or (event.get("response") or {}).get("error")
    if event_type == "response.output_text.delta":
        delta = event.get("delta")
        if isinstance(delta, str):
            state.setdefault("text_deltas", []).append(delta)
    if event_type == "response.output_item.done" and isinstance(event.get("item"), dict):
        state.setdefault("output_items", []).append(event["item"])
    # INVARIANT: BOTH terminal events end the stream. `response.incomplete` is how the
    # Responses API delivers a length-truncated or content-filtered generation — treating
    # only `response.completed` as terminal drained the stream and then raised a 502,
    # discarding a partial answer the caller could have used (OME-746).
    if event_type in _TERMINAL_EVENTS and isinstance(event.get("response"), dict):
        state["final"] = event["response"]
        return True
    return False


def _model_response_from_sse_events(events: Iterable[str], fallback_model: str) -> ModelResponse:
    state: dict[str, Any] = {}
    for data in events:
        if _consume_sse_event(data, state):
            break
    return _model_response_from_state(state, fallback_model)


async def _model_response_from_sse_stream(
    lines: AsyncIterable[str], fallback_model: str
) -> ModelResponse:
    state: dict[str, Any] = {}
    async for data in _aiter_sse_data(lines):
        if _consume_sse_event(data, state):
            break
    return _model_response_from_state(state, fallback_model)


def _model_response_from_state(state: dict[str, Any], fallback_model: str) -> ModelResponse:
    final = state.get("final")
    error = state.get("error")
    if error is not None:
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise CustomLLMError(status_code=502, message=message or "Codex upstream failed")
    if not isinstance(final, dict):
        raise CustomLLMError(status_code=502, message="Codex upstream did not complete response")

    text_deltas = state.get("text_deltas")
    if isinstance(text_deltas, list) and all(isinstance(item, str) for item in text_deltas):
        content = "".join(text_deltas)
    else:
        content = ""
    if not content:
        output_items = state.get("output_items")
        if isinstance(output_items, list):
            content = _extract_text_from_response({"output": output_items})
    if not content:
        content = _extract_text_from_response(final)
    return ModelResponse(
        id=final.get("id"),
        created=int(final.get("created_at") or time.time()),
        model=final.get("model") or fallback_model,
        choices=[
            {
                "index": 0,
                "finish_reason": _finish_reason(final),
                "message": {"role": "assistant", "content": content},
            }
        ],
        usage=_usage_from_response(final),
    )


def _model_response_from_sse(body: str, fallback_model: str) -> ModelResponse:
    return _model_response_from_sse_events(_iter_sse_data(body.splitlines()), fallback_model)


async def _status_error_from_response(response: Any) -> CustomLLMError | None:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code == 401:
        return CustomLLMError(status_code=401, message="Codex upstream rejected OAuth token")
    if status_code < 400:
        return None

    preview = ""
    aread = getattr(response, "aread", None)
    if callable(aread):
        try:
            raw_result = aread()
            raw = (
                await cast(Awaitable[bytes], raw_result)
                if isawaitable(raw_result)
                else cast(bytes, raw_result)
            )
            preview = raw.decode("utf-8", errors="replace")[:500]
        except Exception:
            preview = ""
    elif isinstance(getattr(response, "text", None), str):
        preview = response.text[:500]
    suffix = f": {preview}" if preview else ""
    return CustomLLMError(
        status_code=status_code,
        message=f"Codex upstream request failed with status {status_code}{suffix}",
    )


async def _close_response(response: Any) -> None:
    aclose = getattr(response, "aclose", None)
    if callable(aclose):
        close_result = aclose()
        if isawaitable(close_result):
            await cast(Awaitable[None], close_result)


async def _model_response_from_response(response: Any, fallback_model: str) -> ModelResponse:
    error = await _status_error_from_response(response)
    if error is not None:
        raise error
    return await _model_response_from_sse_stream(response.aiter_lines(), fallback_model)


def _request_kwargs(
    payload: dict[str, Any], headers: dict[str, str], timeout: Any
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"json": payload, "headers": headers}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return kwargs


def _status_error_from_exception(exc: httpx.HTTPStatusError) -> CustomLLMError:
    status_code = exc.response.status_code
    if status_code == 401:
        return CustomLLMError(status_code=401, message="Codex upstream rejected OAuth token")
    message = f"Codex upstream request failed with status {status_code}"
    text = getattr(exc, "text", None) or getattr(exc, "message", None)
    if isinstance(text, str) and text:
        message = f"{message}: {text[:500]}"
    return CustomLLMError(status_code=status_code, message=message)


class CodexCustomLLM(CustomLLM):
    def __init__(self, http_client_factory=None) -> None:
        super().__init__()
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        )

    async def acompletion(
        self,
        model: str,
        messages: list,
        api_base: str | None,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers=None,
        timeout=None,
        client=None,
    ) -> ModelResponse:
        if not api_key:
            raise CustomLLMError(
                status_code=401,
                message="Codex requires gateway-owned OAuth credentials",
            )
        if isinstance(api_key, str) and api_key.startswith(("sk-", "sk-proj-")):
            raise CustomLLMError(
                status_code=400,
                message="Codex subscription models are not available via OpenAI API key fallback",
            )

        extra_headers = headers or {}
        account_id = extra_headers.get("ChatGPT-Account-Id") or extra_headers.get(
            "chatgpt-account-id"
        )
        request_headers = get_chatgpt_default_headers(str(api_key), account_id)
        payload = _build_payload(model, messages, optional_params or {})

        fallback_model = _strip_provider_prefix(model)
        kwargs = _request_kwargs(payload, request_headers, timeout)
        if client is not None:
            try:
                response = await client.post(CODEX_RESPONSES_URL, **kwargs, stream=True)
            except httpx.HTTPStatusError as exc:
                raise _status_error_from_exception(exc) from exc
            try:
                return await _model_response_from_response(response, fallback_model)
            finally:
                await _close_response(response)

        async with self._http_client_factory() as http_client:
            async with http_client.stream("POST", CODEX_RESPONSES_URL, **kwargs) as response:
                return await _model_response_from_response(response, fallback_model)


def ensure_litellm_codex_provider_registered(handler: CodexCustomLLM | None = None) -> None:
    global _HANDLER
    if handler is not None:
        _HANDLER = handler
    if _HANDLER is None:
        _HANDLER = CodexCustomLLM()
    for entry in litellm.custom_provider_map:
        if entry.get("provider") == _PROVIDER:
            entry["custom_handler"] = _HANDLER
            litellm.utils.custom_llm_setup()
            return
    litellm.custom_provider_map.append({"provider": _PROVIDER, "custom_handler": _HANDLER})
    litellm.utils.custom_llm_setup()


def get_litellm_codex_handler() -> CodexCustomLLM:
    ensure_litellm_codex_provider_registered()
    assert _HANDLER is not None
    return _HANDLER
