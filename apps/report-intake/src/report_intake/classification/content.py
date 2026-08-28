"""Spec §4 — the server decides what a report carries, and content is refused rather than stored.

**Pattern:** `apps/scoreboard/src/scoreboard/classification/openness.py`, the repo's one
fail-closed classifier: curated markers, substring match, and every verdict logged rather than
silently absorbed. Fail-closed here means the same thing it means there — the safe answer is the
default, and a caller's own declaration never buys the other one. This service does not consult
`client`-declared intent at all; undeclared content is still content.

It does **not** mean "reject anything large". Only the total body cap and structural violations
reject a report (§2.4): an oversized `client.version` is truncated and kept, because a truncated
report is worth more than no report, and a classifier that turned a 300-byte version string into
a 422 would contradict the caps table it is supposed to complement. That is why the
:func:`_oversized_leaf` detector is scoped to two pointers rather than to a size.

**Why reject rather than store** (spec §4): v1 has no bundle store, so there is nowhere safe to
put content — Linear is third-party SaaS, and prompt-bearing bodies are permitted only in the
Access-gated SigNoz sink. A responder who needs the prompt asks the reporter, which is what
`reply_to` is for. **No redact-and-accept**: partial redaction of free text is unreliable and
creates false confidence.

Two entry points, and the split is load-bearing (plan §2.7):

- :func:`classify_report` walks a report mapping and returns the verdict the response echoes.
- :func:`scan_text` runs the string-level detectors only. `OME-1009` calls it — never
  :func:`classify_report` — to re-check an already-rendered ticket body, because that body is one
  string and the structural detectors are scoped by JSON pointer, which a bare string has none of.

INVARIANT: nothing this module returns quotes the text it matched. A reason is a detector's own
words and a pointer is a path, so both are safe in a 422 and in a log line; the matched span is
exactly the material that must not travel. This is the same rule `binding.py` holds for
pydantic's error objects, for the same reason — the response is unauthenticated.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from ..core.pointers import escape_pointer
from ..reports.caps import ERROR_DETAILS_BYTES

logger = logging.getLogger(__name__)

Classification = Literal["envelope", "content"]
ENVELOPE: Classification = "envelope"
CONTENT: Classification = "content"

OVERSIZED_LEAF_BYTES = ERROR_DETAILS_BYTES
"""When a single string under `/error/details` or `/error/cause` is a captured body rather than a
diagnostic field. Those two nodes are machine-built server JSON — a close reason, a status, an
upstream code — and a leaf this big is a response body, a log tail, or a model completion that a
client dropped in wholesale.

TIED TO §2.4'S CAP, not chosen independently, and the two rules have to agree at the boundary or
one of them is wrong. §2.4 caps `error.details` at 8 KiB and says *truncate, mark* — so a value
UNDER that number is one the spec has already decided to keep, and rejecting it is this module
undercutting the caps table it exists to complement. At the old kilobyte threshold that was not
hypothetical: spec §2.1's own documented `cause` shape, `{"type": "ws", "rcvd": {"code": 1011,
"reason": ...}}`, was a `422` as soon as the close reason ran to 1500 bytes — a report refused for
a verbose upstream error, with advice ("remove the content and resend the envelope") pointing at a
machine-built field the reporter never wrote. Above the cap the detector's claim is much stronger:
a single leaf larger than the whole node is allowed to be is not a diagnostic field."""

_MAX_POINTER_CHARS = 120
"""Bound on the pointer that reaches a 422 or a log line. Unknown keys inside `client` and
`context` are preserved verbatim and §2.4 caps *values*, not key names, so without this a client
chooses how many bytes of its own text come back to it."""

_CAPTURED_BODY_POINTERS = ("/error/details", "/error/cause")
"""Where :func:`_oversized_leaf` applies, and nowhere else (plan §5, §11 conflict 11). `/client`
and `/context` strings, `/note`, `/error/message` and `/error/traceback` all have a cap in §2.4 —
they get truncated and marked, which is a different answer to the same input, not a weaker one."""

# WHY key names rather than values: the value under a content key may be a list, an object, or a
# string carrying no marker of its own. A `messages` array of {role, content} pairs is a
# transcript whatever the text inside it looks like, and a `stdout` string is a captured log body
# even when the log is boring. Every name below is unambiguous in this ecosystem — `message`
# (singular, the error's own) is deliberately absent, and so is `source` (a provenance field in
# three other repo schemas) where `cell_source` says what is meant.
_CONTENT_KEYS: Mapping[str, str] = MappingProxyType(
    {
        "messages": "carries a chat transcript",
        "conversation": "carries a chat transcript",
        "transcript": "carries a chat transcript",
        # A `{role, content}` pair captured without its enclosing `messages` array is still a
        # message, and a bare `content` key anywhere else is a captured HTTP body — which is the
        # same verdict by a different route.
        "content": "carries a message or response body",
        "prompt": "carries prompt text",
        "prompts": "carries prompt text",
        "system_prompt": "carries prompt text",
        "user_prompt": "carries prompt text",
        "input_text": "carries prompt text",
        "completion": "carries a model response",
        "completions": "carries a model response",
        "choices": "carries a model response",
        "generated_text": "carries a model response",
        "output_text": "carries a model response",
        "response_text": "carries a model response",
        "cell_source": "carries notebook cell source",
        "cell_input": "carries notebook cell source",
        "source_code": "carries source",
        "stdout": "carries a captured log body",
        "stderr": "carries a captured log body",
        "logs": "carries a captured log body",
        "log_body": "carries a captured log body",
        "request_body": "carries a captured request body",
        "response_body": "carries a captured response body",
        "expression": "carries a url4 expression",
        "url4": "carries a url4 expression",
    }
)

# Matched against a lowercased copy of the text. Each marker is scaffolding no diagnostic field
# produces by accident: control tokens, an instruction template, or — for url4 — a bang-intent
# anchored on the closing paren it always follows (`(…)!'Answer this…'`). The anchor is what keeps
# an exclamation-then-apostrophe inside an ordinary `note` out of this list.
_TEXT_MARKERS: tuple[tuple[str, str], ...] = (
    ("<|im_start|>", "carries ChatML prompt scaffolding"),
    ("<|im_end|>", "carries ChatML prompt scaffolding"),
    ("<|endoftext|>", "carries model prompt scaffolding"),
    ("[inst]", "carries an instruction-tuned prompt template"),
    ("[/inst]", "carries an instruction-tuned prompt template"),
    ("<<sys>>", "carries an instruction-tuned prompt template"),
    ("### instruction:", "carries an instruction/response prompt template"),
    ("### response:", "carries an instruction/response prompt template"),
    ("\n\nhuman:", "carries a Human/Assistant transcript"),
    ("\n\nassistant:", "carries a Human/Assistant transcript"),
    (")!'", "carries a url4 intent expression"),
    (")!*'", "carries a url4 broadcast intent expression"),
)

# Matched against the same text with whitespace removed, which is how a chat payload captured
# into a string survives whatever indentation the client serialized it with.
_JSON_MARKERS: tuple[tuple[str, str], ...] = (
    ('"role":"user"', "carries a chat transcript"),
    ('"role":"assistant"', "carries a chat transcript"),
    ('"role":"system"', "carries a chat transcript"),
    ('"messages":[', "carries a chat request payload"),
    ('"choices":[', "carries a model completion payload"),
)

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Verdict:
    """The server's verdict on one report, echoed to the client as `classification` (spec §2.2).

    `detail` is present exactly when the verdict rejects, and is the 422's `detail`. Reading it
    for `None` is therefore the rejection test — there is no second way to reach `content`, and a
    verdict that rejected without saying why would be a 422 a client cannot act on.
    """

    classification: Classification
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class _Finding:
    pointer: str
    reason: str


def classify_report(document: Mapping[str, Any]) -> Verdict:
    """Classify a report, scanning for the material spec §4 lists: prompt text, model responses,
    cell source, log bodies, url4 expressions.

    ``document`` is `BoundedReport.scanned` — control-stripped and **pre-truncation**. Passing
    `payload` instead would make truncation a way to smuggle content past this check: a prompt
    pushed past a field's cap survives in the report a human reads while the classifier sees only
    the marker that replaced it.
    """
    finding = _first_finding(document)
    if finding is None:
        return Verdict(ENVELOPE)
    # WHY log it: the 422 goes to the client and to nobody on this side, and a client that starts
    # sending content is an operational fact worth seeing. Reason and pointer only — never the
    # match. `%r` because tab and newline survive §2.4's control-character strip, so a preserved
    # key inside `client` or `context` can still carry one into what would otherwise be a second
    # log line.
    logger.info("report rejected as content at %r: %s", _shortened(finding.pointer), finding.reason)
    return Verdict(CONTENT, _detail(finding))


def scan_text(text: str) -> str | None:
    """The string-level detectors alone: the reason ``text`` is content, or None.

    This is the entry point `OME-1009` re-checks a rendered ticket body with (plan §2.7). The
    reason reads as a predicate — "carries a chat transcript" — so it composes into a sink's own
    message as easily as into this service's 422.
    """
    lowered = text.lower()
    literal = next((reason for marker, reason in _TEXT_MARKERS if marker in lowered), None)
    if literal is not None:
        return literal
    squeezed = _WHITESPACE.sub("", lowered)
    return next((reason for marker, reason in _JSON_MARKERS if marker in squeezed), None)


def _first_finding(document: Mapping[str, Any]) -> _Finding | None:
    for pointer, node in _walk(document):
        finding = _finding(pointer, node)
        if finding is not None:
            return finding
    return None


def _walk(document: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    """Every node of ``document`` with its RFC 6901 pointer, shallowest first.

    Breadth-first so the reported node is the shallowest offending one — the one a client can most
    easily remove — and iterative because this runs on input a client controls: a recursive walk
    over a deep body raises `RecursionError`, which is a 500 where a 422 belongs.
    """
    pending: deque[tuple[str, Any]] = deque([("", document)])
    while pending:
        pointer, node = pending.popleft()
        yield pointer, node
        if isinstance(node, Mapping):
            pending.extend(
                (f"{pointer}/{escape_pointer(str(key))}", value) for key, value in node.items()
            )
        elif isinstance(node, list):
            pending.extend((f"{pointer}/{index}", item) for index, item in enumerate(node))


def _finding(pointer: str, node: Any) -> _Finding | None:
    if isinstance(node, Mapping):
        return _content_key(pointer, node)
    if isinstance(node, str):
        return _text_finding(pointer, node)
    return None


def _content_key(pointer: str, node: Mapping[str, Any]) -> _Finding | None:
    for key in node:
        reason = _CONTENT_KEYS.get(str(key).lower())
        if reason is not None:
            return _Finding(f"{pointer}/{escape_pointer(str(key))}", reason)
    return None


def _text_finding(pointer: str, value: str) -> _Finding | None:
    reason = scan_text(value)
    if reason is not None:
        return _Finding(pointer, reason)
    return _oversized_leaf(pointer, value)


def _oversized_leaf(pointer: str, value: str) -> _Finding | None:
    """A string under `/error/details` or `/error/cause` big enough to be a captured body.

    `error` is a closed model, so no sibling key can share those two prefixes — the check is a
    `startswith` rather than a segment comparison because the leaf may sit at any depth under
    either node.
    """
    if not pointer.startswith(_CAPTURED_BODY_POINTERS):
        return None
    size = len(value.encode("utf-8"))
    if size <= OVERSIZED_LEAF_BYTES:
        return None
    return _Finding(
        pointer,
        f"holds {size} bytes in one string, over the {OVERSIZED_LEAF_BYTES}-byte limit for a "
        "diagnostic field, which this service reads as a captured body",
    )


def _detail(finding: _Finding) -> str:
    """The 422's `detail`: what was found, where, and what the client should do about it.

    Spec §8's client rule is that a report is never lost, so the detail says what the client's
    next move is — drop the content and resend the envelope — rather than only that it failed.
    """
    return (
        f"this service does not accept prompt-bearing content, and {_shortened(finding.pointer)} "
        f"{finding.reason}. Nothing was stored: remove the content and resend the envelope, or "
        "quote a trace id and keep the content yourself."
    )


def _shortened(pointer: str) -> str:
    if len(pointer) <= _MAX_POINTER_CHARS:
        return pointer
    return pointer[:_MAX_POINTER_CHARS] + "…"
