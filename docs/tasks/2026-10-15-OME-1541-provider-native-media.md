---
id: OME-1541
linear_url: https://linear.app/openmined/issue/OME-1541/send-images-and-pdfs-to-gemini-antigravity-and-codex-through-one
status: done
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
created: 2026-10-15
closed: 2026-10-16
---

# Send images and PDFs to Gemini, Antigravity and Codex through one shared content-part translator

The three custom adapters flattened OpenAI `content` to a string, so every image was dropped and
the call still answered 200. A new `core/content_parts.py` parses content into text, inline media
and remote-image parts; Gemini and Antigravity send `inlineData`, Codex sends `input_text` /
`input_image` / `input_file`. Anything a provider cannot carry is refused before dispatch with a
typed 422 `unsupported_content_part`. Text-only requests are byte-identical to before. Parent epic
`OME-1529`; unblocks spike `OME-1598`. Ledger: `../work/2026-10-15-provider-native-media.md`.
