"""OpenAI <-> Antigravity Code Assist message conversion.

This is the deliberately DUPLICATED converter (findings U5): the inner
contents/generationConfig/tools building shares the Gemini Code Assist shape,
but the Antigravity request envelope diverges (U14) — it uses `userAgent` +
`requestId`, NOT gemini's `user_prompt_id` + `request.session_id`. Keeping a
provider-local copy lets the two payload shapes drift loudly and independently
rather than coupling antigravity to gemini_provider.

`systemInstruction` is an object with `parts` (a bare string 400s); assistant
turns map to role="model" (not "assistant").
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable
from typing import Any

from litellm.llms.custom_llm import CustomLLMError
from litellm.types.utils import ModelResponse

from aigateway.core.content_parts import gemini_parts, parse_content, text_only
from aigateway.core.usage_modalities import (
    IMAGE_AND_FILE_KEY,
    bounded_image_and_file_tokens_from_gemini,
)

PROVIDER = "antigravity"


def strip_provider_prefix(model: str) -> str:
    stripped = model.split("/", 1)[1] if model.startswith(f"{PROVIDER}/") else model
    return stripped.removeprefix("models/")


def build_generate_content_body(
    messages: list[dict[str, Any]], optional_params: dict[str, Any]
) -> dict[str, Any]:
    """Build the inner Code Assist `request` object (contents/config/tools).

    Returned dict is the value placed under the outer envelope's `request` key
    by the chat handler.
    """
    body: dict[str, Any] = {}
    system_chunks: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "system":
            text = text_only(message.get("content"), provider=PROVIDER, role="system")
            if text:
                system_chunks.append(text)
            continue
        converted = _message_to_content(message)
        if converted is not None:
            contents.append(converted)

    if system_chunks:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_chunks)}]}
    body["contents"] = contents

    generation_config: dict[str, Any] = {}
    config_map = {
        "max_tokens": "maxOutputTokens",
        "temperature": "temperature",
        "top_p": "topP",
        "top_k": "topK",
    }
    for source, target in config_map.items():
        value = optional_params.get(source)
        if value is not None:
            generation_config[target] = value
    stop = optional_params.get("stop")
    if isinstance(stop, str):
        generation_config["stopSequences"] = [stop]
    elif isinstance(stop, list):
        generation_config["stopSequences"] = [item for item in stop if isinstance(item, str)]
    if generation_config:
        body["generationConfig"] = generation_config

    tools = optional_params.get("tools")
    if isinstance(tools, list):
        declarations = [_tool_to_gemini(tool) for tool in tools if isinstance(tool, dict)]
        declarations = [declaration for declaration in declarations if declaration is not None]
        if declarations:
            body["tools"] = [{"functionDeclarations": declarations}]

    return body


def model_response_from_antigravity(data: dict[str, Any], fallback_model: str) -> ModelResponse:
    raw_response = data.get("response")
    unwrapped: dict[str, Any] = raw_response if isinstance(raw_response, dict) else data
    candidates = unwrapped.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise CustomLLMError(status_code=502, message="Antigravity response missing candidates")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise CustomLLMError(status_code=502, message="Antigravity candidate is not an object")
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else []
    parts = parts if isinstance(parts, list) else []
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    tool_calls = _tool_calls_from_parts(parts)
    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return ModelResponse(
        id=unwrapped.get("responseId") or data.get("responseId") or f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=unwrapped.get("modelVersion") or fallback_model,
        choices=[
            {
                "index": 0,
                "finish_reason": _finish_reason(candidate.get("finishReason")),
                "message": message,
            }
        ],
        usage=_usage_from_response(unwrapped),
    )


def _finish_reason(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
        "RECITATION": "content_filter",
    }.get(value, value.lower())


def _message_to_content(message: dict[str, Any]) -> dict[str, Any] | None:
    role = str(message.get("role") or "user")
    if role == "system":
        return None
    # Antigravity (Gemini Code Assist) uses role="model" for assistant turns.
    gemini_role = "model" if role == "assistant" else "user"
    parts: list[dict[str, Any]] = []

    if role == "tool":
        parts.append(
            {
                "functionResponse": {
                    "name": str(message.get("name") or message.get("tool_call_id") or "tool"),
                    "response": {
                        "content": text_only(message.get("content"), provider=PROVIDER, role="tool")
                    },
                }
            }
        )
    else:
        # FEATURE (OME-1541): images and PDFs travel as `inlineData`, in content order.
        parts.extend(
            gemini_parts(
                parse_content(message.get("content"), provider=PROVIDER), provider=PROVIDER
            )
        )

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            raw_args = function.get("arguments")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"arguments": raw_args}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            parts.append({"functionCall": {"name": name, "args": args}})

    return {"role": gemini_role, "parts": parts} if parts else None


def _tool_calls_from_parts(parts: Iterable[Any]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        function_call = part.get("functionCall")
        if not isinstance(function_call, dict):
            continue
        name = function_call.get("name")
        if not isinstance(name, str) or not name:
            continue
        args = function_call.get("args")
        tool_calls.append(
            {
                "id": function_call.get("id") or f"call_{uuid.uuid4().hex}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args if isinstance(args, dict) else {}),
                },
            }
        )
    return tool_calls


def _tool_to_gemini(tool: dict[str, Any]) -> dict[str, Any] | None:
    function = tool.get("function") if tool.get("type") == "function" else tool
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    declaration: dict[str, Any] = {"name": name}
    for source, target in (("description", "description"), ("parameters", "parameters")):
        if source in function:
            declaration[target] = function[source]
    return declaration


def _usage_from_response(data: dict[str, Any]) -> dict[str, Any] | None:
    usage = data.get("usageMetadata")
    if not isinstance(usage, dict):
        return None
    try:
        prompt = int(usage.get("promptTokenCount") or 0)
        completion = int(usage.get("candidatesTokenCount") or 0)
        total = int(usage.get("totalTokenCount") or prompt + completion)
    except (TypeError, ValueError):
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        # FEATURE (OME-1546): image/file input tokens from `promptTokensDetails`; `None` when
        # the response carries no per-modality breakdown, or no valid `promptTokenCount` that
        # bounds it. A subset of `prompt_tokens`, which keeps its existing parsing.
        "prompt_tokens_details": {
            IMAGE_AND_FILE_KEY: bounded_image_and_file_tokens_from_gemini(usage),
        },
    }
