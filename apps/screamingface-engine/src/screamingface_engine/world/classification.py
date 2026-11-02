"""The `/classify` world endpoint: classification inference through the Gateway (OME-1795).

FEATURE: hosted BYOM, Unit 3 (spec section 3.3, E3-E9). A caller names a classifier model ID and
a text; the worker sends only those two values to the Gateway's `POST /v1/classifications` under
the trusted request scope, and returns the Gateway's labels and scores once they pass the result
contract. Adding a classifier needs no Engine route and no world config entry: the Gateway decides
which IDs the caller may use.

WHY no url4 import: `tests/unit/test_url4_executor.py` pins which modules may import the url4
engine. The handler raises `RunnerRequestError` with a stable code, and `world.factory`, already
on that list, registers it and turns the error into url4's `ResolutionError`, as
`connector._ModelEndpoint` does.

WHY the connector's Gateway helpers and not the chat loop: classification shares the client, the
identity headers, the transport retry and the refusal decoding with chat, and nothing else. No
message building, choice parsing or cache field applies to it, and its usage is one record whose
cost is unknown (E8 as amended).

INVARIANT: the context supplies only the model ID and the input. The origin, the path, every
header and every credential come from the Engine's own world and request scope.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote_to_bytes

import httpx

from screamingface_engine.request_scope import RequestScope, current_scope
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _GatewayRefusal,
    _headers,
    _json_or_raise,
    _post_completion,
    _raise_for_status,
    _report_unpriced_call,
)
from screamingface_engine.world.errors import RunnerRequestError

CLASSIFY_ROUTE = "/classify"
CLASSIFY_INTENT = "classify"
CLASSIFICATIONS_PATH = "/v1/classifications"
RESULT_CONTRACT = "classification-scores-v1"

CLASSIFICATION_UNSUPPORTED = "classification_unsupported"
"""A seeded, capture or replay run asked for a classification (E4); a mount answers `400`."""

CLASSIFIER_NOT_FOUND = "classifier_not_found"
"""The caller may not use this model ID as a classifier (E6); a mount answers `404`.

WHY not url4's `endpoint_not_found`: that code means the route itself is absent, and `/classify`
is present; what is missing is the caller's classifier.
"""

_NOT_FOUND_MESSAGE = "no classifier with this model ID is available to the caller"
MALFORMED_MESSAGE = (
    'a classification takes q=({"model": <string>, "input": <string>})!classify and no parameters'
)
_BAD_RESULT_MESSAGE = "aigateway returned a classification result outside its contract"
# WHY url4's code spelled here: the caller's request is malformed, which url4 answers `400` with
# `malformed_source`; importing url4's `ErrorCode` would put this module on the url4 allowlist.
MALFORMED_SOURCE = "malformed_source"
_BAD_RESPONSE = "aigateway_bad_response"
_INVALID_MODEL = "invalid_model"


class ClassificationEndpoint:
    """One handler for every classifier: the model ID travels in the request, not in the route.

    Built once per world, on the world's own Gateway client (the one `open_frozen_copy` and the
    chat calls use), so a classification carries the same identity and trace as every other
    Gateway request of the run.
    """

    __slots__ = ("_cfg", "_http_client")

    def __init__(self, http_client: httpx.AsyncClient, cfg: AigatewayConfig) -> None:
        self._http_client = http_client
        self._cfg = cfg

    async def __call__(self, context: str, intent: str, params: Mapping[str, str]) -> str:
        """Classify the context's input with its model and return the result document.

        Raises:
            RunnerRequestError: `classification_unsupported`, `malformed_source`,
                `classifier_not_found` or `aigateway_bad_response`, all permanent, each before
                or instead of a result.
            ResolutionError: the connector's own transport and refusal codes, unchanged.
        """
        scope = current_scope()
        # INVARIANT (E4): the mode refusal comes first, so a seeded, capture or replay run never
        # reaches the Gateway, whatever its envelope holds.
        _refuse_mode(scope)
        model, text = _envelope(context, intent, params)
        provider, _, alias = model.partition("/")
        if not (provider and alias):
            # WHY no Gateway call: an ID without a provider prefix or an alias can name no
            # classifier, and the Gateway's own answer for it would be a plain-text 400.
            raise _not_found()
        headers = {
            **_headers(scope),
            "x-aigw-execution-timeout-s": str(self._cfg.timeout_s),
            "x-aigw-queue-timeout-s": str(self._cfg.admission_timeout_s),
        }
        try:
            # WHY the `possibly_billed` mark is dropped: it is recorded for a priced answer, and
            # this call's cost is reported unknown whatever happened to it.
            response, _ = await _post_completion(
                self._http_client,
                headers=headers,
                body={"model": model, "input": text},
                path=CLASSIFICATIONS_PATH,
            )
            try:
                _raise_for_status(response)
            except _GatewayRefusal as exc:
                # INVARIANT (E6): an absent, ungranted or chat model ID is one answer with one
                # message, so a caller cannot tell them apart; the Gateway's text is not relayed.
                if exc.status == 400 and (
                    exc.code == _INVALID_MODEL or exc.refuses_provider(provider)
                ):
                    raise _not_found() from None
                raise
            return _result(_json_or_raise(response), model)
        finally:
            # INVARIANT (E8 as amended): once the request is handed over, the classifier may
            # have run and billed, whatever came back, so exactly one unknown-cost record is
            # reported and the run total cannot claim a price. Every refusal above stays silent.
            _report_unpriced_call(provider, model)


def _refuse_mode(scope: RequestScope) -> None:
    # WHY `is not None`: a seed of 0 is a seed.
    if scope.answer_seed is not None:
        raise _unsupported("a classification takes no answer seed; send it without X-Answer-Seed")
    if scope.capture:
        raise _unsupported("a classification cannot run in a capture run; it stores no answer")
    if scope.replay_frozen_copy is not None:
        raise _unsupported("a classification cannot run in a replay run; no copy holds one")


def _envelope(context: str, intent: str, params: Mapping[str, str]) -> tuple[str, str]:
    """The model ID and the input, from the exact two-field context (E3).

    WHY a parameter is refused and not ignored: a dropped `seed=` would run a seeded call
    unseeded and still answer as if it had applied.
    """
    if intent != CLASSIFY_INTENT or params:
        raise _malformed()
    try:
        document = json.loads(context, object_pairs_hook=_unique_pairs)
    except (ValueError, RecursionError):
        # WHY RecursionError: an 8 KiB context of nested brackets exhausts the decoder's
        # recursion limit before it reaches a syntax error.
        raise _malformed() from None
    if not isinstance(document, dict) or set(document) != {"model", "input"}:
        raise _malformed()
    model, text = document["model"], document["input"]
    if not (isinstance(model, str) and isinstance(text, str)):
        raise _malformed()
    try:
        model.encode("utf-8")
        text.encode("utf-8")
    except UnicodeEncodeError:
        # WHY refused, not repaired: JSON can spell a lone surrogate, which no UTF-8 body can
        # carry. Replacing it would classify a text the caller did not send, and the encoding
        # error would quote it, so neither reaches the caller.
        raise _malformed() from None
    return model, text


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document = dict(pairs)
    if len(document) != len(pairs):
        raise ValueError("a classification context repeats a key")
    return document


def _result(document: object, model: str) -> str:
    """The Gateway's result as the contract states it, or `aigateway_bad_response` (E7).

    Only the four contract fields are passed on, labels and scores in upstream order: a field
    outside the contract is not the caller's to read.
    """
    if not (
        isinstance(document, dict)
        and document.get("object") == "classification"
        and document.get("model") == model
        and document.get("contract") == RESULT_CONTRACT
    ):
        raise _bad_result()
    scores = document.get("scores")
    if not isinstance(scores, list) or not scores:
        raise _bad_result()
    pairs = [_label_score(item) for item in scores]
    if len({label for label, _ in pairs}) != len(pairs):
        raise _bad_result()
    return json.dumps(
        {
            "object": "classification",
            "model": model,
            "contract": RESULT_CONTRACT,
            "scores": [{"label": label, "score": score} for label, score in pairs],
        },
        ensure_ascii=False,
        allow_nan=False,
    )


def _label_score(item: object) -> tuple[str, int | float]:
    if not isinstance(item, dict):
        raise _bad_result()
    label, score = item.get("label"), item.get("score")
    if not isinstance(label, str) or not label:
        raise _bad_result()
    # WHY the range test alone: NaN and both infinities fail `0 <= score <= 1`, and an integer
    # too large for a float is compared exactly instead of overflowing a finiteness check.
    if isinstance(score, bool) or not isinstance(score, int | float) or not 0 <= score <= 1:
        raise _bad_result()
    return label, score


def refuses_query(path: str, raw: bytes) -> bool:
    """Whether a call to ``path`` with the raw query ``raw`` is a `/classify` call whose
    percent-escapes do not decode as UTF-8, refused as `malformed_source` before any run.

    WHY on the raw bytes, at the App (decision 10): url4 decodes such an escape to U+FFFD, so the
    run would read, and the classifier bill, a text the caller never sent. No later step can tell
    a replaced character from one the caller sent.
    """
    if path != CLASSIFY_ROUTE:
        return False
    try:
        unquote_to_bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _unsupported(message: str) -> RunnerRequestError:
    return RunnerRequestError(message, code=CLASSIFICATION_UNSUPPORTED, permanent=True)


def _malformed() -> RunnerRequestError:
    return RunnerRequestError(MALFORMED_MESSAGE, code=MALFORMED_SOURCE, permanent=True)


def _not_found() -> RunnerRequestError:
    return RunnerRequestError(_NOT_FOUND_MESSAGE, code=CLASSIFIER_NOT_FOUND, permanent=True)


def _bad_result() -> RunnerRequestError:
    return RunnerRequestError(_BAD_RESULT_MESSAGE, code=_BAD_RESPONSE, permanent=True)


__all__ = [
    "CLASSIFICATIONS_PATH",
    "CLASSIFICATION_UNSUPPORTED",
    "CLASSIFIER_NOT_FOUND",
    "CLASSIFY_INTENT",
    "CLASSIFY_ROUTE",
    "MALFORMED_MESSAGE",
    "MALFORMED_SOURCE",
    "RESULT_CONTRACT",
    "ClassificationEndpoint",
    "refuses_query",
]
