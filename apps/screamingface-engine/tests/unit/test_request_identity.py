"""The model request key: text requests keep today's key, pictures key by their bytes (OME-1271).

The rule is the request-identity section of the file-input spec on #1450: a v2 Case whose messages
carry a picture or file is keyed by its canonical part list (the digest of each picture's DECODED
bytes, plus where and how it sits), never by the base64 spelling of its envelope. A request with no
picture or file keeps the key `main` gave it, byte for byte, so no stored grading join moves.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from typing import Any

import pytest

from screamingface_engine.benchmarks.candidate_input import parse_candidate_input
from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_V2_SCHEMA
from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    accounting_for_grading_evidence,
    capture_grading_requests,
    register_grading_request,
)
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    OperationCache,
    OperationUsage,
)
from screamingface_engine.operation_calls import (
    capture_request_accounting,
    current_model_request_key,
    operation_call_identity,
    record_operation_call,
)
from screamingface_engine.request_identity import canonical_request_parts, model_request_key

# WHY 11 bytes: base64 of a length that is not a multiple of 3 ends in `=` padding, so the
# padding variants below have something to drop.
_PICTURE_BYTES = b"\x89PNG\r\n\x1a\nabc"
_PICTURE_B64 = base64.b64encode(_PICTURE_BYTES).decode()
_PICTURE_DIGEST = f"sha256:{hashlib.sha256(_PICTURE_BYTES).hexdigest()}"
_PDF_BYTES = b"%PDF-1.4"
_PDF_B64 = base64.b64encode(_PDF_BYTES).decode()
_QUESTION = {"type": "text", "text": "What is the height of the tallest bar?"}
_ROUTE = "openai/gpt-4o-mini"


def _image(b64: str = _PICTURE_B64, mime: str = "image/png", **extra: str) -> dict[str, Any]:
    """One inline picture part; ``extra`` adds ``detail``."""

    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", **extra}}


def _envelope(*messages: dict[str, Any], **dumps: Any) -> str:
    """Seal messages into a v2 envelope; ``dumps`` varies only the JSON spelling."""

    return json.dumps({"schema": CANDIDATE_INPUT_V2_SCHEMA, "messages": list(messages)}, **dumps)


def _user(*parts: dict[str, Any]) -> dict[str, Any]:
    """One user message holding a part list."""

    return {"role": "user", "content": list(parts)}


def _key(context: str | None, intent: str | None = None) -> str:
    """The key of one call on a fixed route and params, so only the context varies."""

    return model_request_key(
        path=_ROUTE, params={"temperature": "0"}, context=context, intent=intent
    )


# The literal keys `upstream/main` (e33ff8d62) gives these calls, computed before this change.
_V1 = (
    '{"schema": "screamingface.candidate-input.v1", "messages": [{"role": "system", "content": '
    '"Be brief."}, {"role": "user", "content": "What is 6 times 7?"}]}'
)
_FUSION = '{"input": "What is 6 times 7?", "outputs": ["42", "41"]}'


@pytest.mark.parametrize(
    ("path", "params", "context", "intent", "main_key"),
    [
        (
            _ROUTE,
            {"temperature": "0"},
            "What is 6 times 7?",
            "Answer with a number.",
            "29f9ffcce013d2a6cb7878f834413541ced3f712f315f9ce57123426e278cb18",
        ),
        (
            _ROUTE,
            {"temperature": "0"},
            _V1,
            None,
            "8ae1bcde6d779ad07ee62f89c6ef7ddf8d8eabcad68a084e0060dfb012664251",
        ),
        (
            "anthropic/claude-sonnet",
            {},
            _FUSION,
            "Pick the best answer.",
            "6b252044e132f80b74271894b16cd6f6d6a10ece97b9bf04f206f884712894b1",
        ),
        (
            _ROUTE,
            {},
            None,
            None,
            "0f4096370a788e05e7ef0214f8207a12e8a34218035607bae81a055e5bc4097d",
        ),
    ],
    ids=["plain-prompt", "v1-envelope", "fusion-shaped-json", "no-context"],
)
def test_a_request_without_pictures_keeps_the_key_main_gave_it(
    path: str, params: dict[str, str], context: str | None, intent: str | None, main_key: str
) -> None:
    # INVARIANT: grading joins and goldens recorded before pictures existed must still match, so a
    # text request is hashed exactly as before; the picture rule may never touch it.
    assert model_request_key(path=path, params=params, context=context, intent=intent) == main_key


def test_canonical_parts_name_each_part_by_place_and_bytes() -> None:
    # WHY pinned field by field: OME-1679 keys Fusion synthesizer contexts through this same list,
    # so its shape is a contract, not an implementation detail. Every part kind appears once.
    pdf: dict[str, Any] = {
        "type": "file",
        "file": {"file_data": f"data:application/pdf;base64,{_PDF_B64}", "filename": "chart.pdf"},
    }
    messages = parse_candidate_input(
        _envelope(
            {"role": "system", "content": "Be brief."},
            _user(_QUESTION, _image(detail="low"), pdf),
        )
    )
    assert messages is not None

    assert canonical_request_parts(messages) == [
        {"kind": "text", "role": "system", "message": 0, "position": 0, "text": "Be brief."},
        {"kind": "text", "role": "user", "message": 1, "position": 0, "text": _QUESTION["text"]},
        {
            "kind": "image",
            "role": "user",
            "message": 1,
            "position": 1,
            "digest": _PICTURE_DIGEST,
            "media_type": "image/png",
            "detail": "low",
        },
        {
            "kind": "file",
            "role": "user",
            "message": 1,
            "position": 2,
            "digest": f"sha256:{hashlib.sha256(_PDF_BYTES).hexdigest()}",
            "media_type": "application/pdf",
            "filename": "chart.pdf",
        },
    ]


def test_one_picture_spelled_differently_keeps_one_key() -> None:
    # INVARIANT: the key follows the bytes the model sees, so base64 line breaks, dropped padding,
    # envelope key order and JSON whitespace cannot split one call into two request identities.
    canonical = _key(_envelope(_user(_QUESTION, _image())))
    wrapped_b64 = "\n".join(_PICTURE_B64[i : i + 4] for i in range(0, len(_PICTURE_B64), 4))
    # WHY a hand-built dict: messages before schema, content before role, type after image_url.
    reordered = json.dumps(
        {
            "messages": [
                {
                    "content": [
                        _QUESTION,
                        {"image_url": {"url": _image()["image_url"]["url"]}, "type": "image_url"},
                    ],
                    "role": "user",
                }
            ],
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
        }
    )

    assert _key(_envelope(_user(_QUESTION, _image(wrapped_b64)))) == canonical
    assert _key(_envelope(_user(_QUESTION, _image(_PICTURE_B64.rstrip("="))))) == canonical
    assert _key(reordered) == canonical
    assert _key(_envelope(_user(_QUESTION, _image()), indent=2)) == canonical


_ONE_PICTURE = _envelope(_user(_QUESTION, _image()))
_SYSTEM_THEN_PICTURE = _envelope(
    {"role": "system", "content": "Be brief."}, _user(_QUESTION, _image())
)


@pytest.mark.parametrize(
    ("base", "variant"),
    [
        (_ONE_PICTURE, _envelope(_user(_QUESTION, _image(base64.b64encode(b"other").decode())))),
        (_ONE_PICTURE, _envelope(_user(_QUESTION, _image(mime="image/jpeg")))),
        (_ONE_PICTURE, _envelope(_user(_QUESTION, _image(detail="high")))),
        (_ONE_PICTURE, _envelope(_user(_image(), _QUESTION))),
        (
            _SYSTEM_THEN_PICTURE,
            _envelope({"role": "developer", "content": "Be brief."}, _user(_QUESTION, _image())),
        ),
        (_ONE_PICTURE, _envelope({"role": "user", "content": _QUESTION["text"]}, _user(_image()))),
    ],
    ids=["other-bytes", "media-type", "detail", "position", "role", "message-index"],
)
def test_a_change_the_model_can_see_changes_the_key(base: str, variant: str) -> None:
    # WHY: two requests a model may answer differently must never share one request identity.
    assert _key(variant) != _key(base)


def test_a_file_name_is_part_of_the_key() -> None:
    # WHY: a PDF's file name reaches the model beside its bytes, so it is part of the request.
    def with_file(**extra: str) -> str:
        return _envelope(
            _user(
                _QUESTION,
                {
                    "type": "file",
                    "file": {"file_data": f"data:application/pdf;base64,{_PDF_B64}", **extra},
                },
            )
        )

    assert _key(with_file(filename="a.pdf")) != _key(with_file(filename="b.pdf"))
    assert _key(with_file(filename="a.pdf")) != _key(with_file())


def test_the_adapter_revision_moves_picture_keys_and_leaves_text_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT: the revision versions how picture parts are BUILT; a text request has none, so a
    # bump must re-key every picture call and no text call.
    picture = _envelope(_user(_QUESTION, _image()))
    before = (_key(picture), _key("What is 6 times 7?"), _key(_V1))

    monkeypatch.setattr("screamingface_engine.request_identity.NON_TEXT_PART_ADAPTER_REVISION", 999)

    assert _key(picture) != before[0]
    assert (_key("What is 6 times 7?"), _key(_V1)) == before[1:]


@pytest.mark.parametrize(
    "refused",
    [
        _envelope(_user(_QUESTION, _image("not*base64"))),
        _envelope({"role": "user", "content": "text only, so v1"}),
    ],
    ids=["undecodable-base64", "parser-refuses"],
)
def test_an_envelope_the_connector_refuses_keys_as_written(refused: str) -> None:
    # WHY: the parser-refused envelope is refused by the connector by name; the undecodable one is
    # decoded by nobody on our side before the provider. Either way the key must not raise first,
    # so it falls back to hashing the text as main would.
    as_written = json.dumps(
        {"path": _ROUTE, "params": [["temperature", "0"]], "context": refused, "intent": None},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    assert _key(refused) == hashlib.sha256(as_written).hexdigest()


def test_the_call_and_the_grading_ledger_agree_on_a_picture_key() -> None:
    # INVARIANT: grading accounting finds a call's cost by joining the key the connector binds to
    # the key the judge registered; if the two sites hashed a picture differently the join breaks.
    context = _envelope(_user(_QUESTION, _image(detail="low")))
    owner = GradingEvidenceOwner(benchmark_id="mmmu", case_id=7, check_id="match", sequence=1)
    # WHY any exact accounting stands in: the test asks only whether the join finds the call.
    accounting = OperationAccounting(
        provider="openrouter",
        request_model=_ROUTE,
        response_model=_ROUTE,
        usage=OperationUsage(
            input_tokens=10,
            output_tokens=2,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            reasoning_tokens=0,
            cost_usd="0.01",
        ),
        provider_latency_ms=20,
        provider_attempts=1,
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )

    with capture_request_accounting(), capture_grading_requests():
        register_grading_request(
            owner, path=_ROUTE, params={"temperature": "0"}, context=context, intent=None
        )
        with operation_call_identity(_ROUTE, {"temperature": "0"}, context=context):
            assert current_model_request_key() == _key(context)
            record_operation_call("42", "stop", accounting)

        assert accounting_for_grading_evidence(owner) is not None


def test_importing_the_key_does_not_load_the_envelope_module() -> None:
    # INVARIANT (review finding, 2026-10-23): the envelope module loads the `benchmarks` package
    # and url4 with it; every importer of the key would pay that at start-up (~18 ms → ~100 ms), so
    # it loads only when a context opens a JSON object. A fresh interpreter, since this test
    # module has already imported it.
    probe = (
        "import sys, screamingface_engine.request_identity as r;"
        "r.model_request_key(path='p', params={}, context='What is 6 times 7?', intent=None);"
        "print('screamingface_engine.benchmarks' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
