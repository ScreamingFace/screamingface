# Spec — Ollama refuses file parts instead of dropping them

## Problem

`OME-1541` made Gemini, Antigravity and Codex refuse any content part they cannot carry. Ollama
was out of scope because it passes messages to LiteLLM unchanged. A live run on 2026-10-16
(`qwen2.5vl:3b`) showed the PDF case answering **200** with the file gone: prompt tokens rose by 7
(the longer question only) and the answer was unrelated.

Cause (LiteLLM 1.102.1, `llms/ollama/chat/transformation.py`): each message becomes
`{role, content: <text only>, images: extract_images_from_message(m)}`. Only `image_url` parts
survive (as base64, from any role); `file` parts are discarded. A remote `http(s)` image URL is
passed on as if it were base64, which the model cannot read.

## Behaviour

`OllamaProviderPlugin.prepare_chat_body` runs `check_messages` before dispatch with:
- `media_roles`: every role (`system`, `user`, `assistant`, `tool`) — LiteLLM carries images from any role;
- `allow_remote_images=False` → a remote image URL gets 422 `reason: remote_url`;
- `allow_files=False` (new flag, default `True`) → any `file` part gets 422
  `{code: unsupported_content_part, provider: ollama, part_type: file, reason: files_unsupported}`.

Data-URI images and text-only requests are unchanged. The three `OME-1541` plugins keep the default
`allow_files=True`, so their behaviour is unchanged.

## Out of scope

Converting PDFs to text for Ollama (that is `OME-1550`, office/PDF to text at run time).
