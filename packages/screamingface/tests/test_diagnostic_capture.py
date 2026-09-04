from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError
from typing import cast

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from screamingface._diagnostics.capture import (
    _client_document,
    _engine_document,
    _error_document,
)
from screamingface._version import SOURCE_TREE_VERSION
from screamingface.errors import ExecutionError


def _captured_execution_error() -> ExecutionError:
    local_api_key = "sk-local-must-never-leak"
    try:
        raise RuntimeError("private provider response must never leak")
    except RuntimeError as cause:
        error = ExecutionError(
            "The Engine disconnected.",
            code="websocket_disconnected",
            status=503,
            permanent=False,
            details={
                "model": "openrouter/anthropic/claude",
                "parameter": "max_tokens",
                "reason": "provider_disabled",
                "prompt": "private prompt must never leak",
                "api_key": local_api_key,
                "nested": {"response": "private response must never leak"},
            },
            hint="Retry the operation.",
        )
        error.__traceback__ = cause.__traceback__
        error.__cause__ = cause
        return error


def test_error_capture_is_structured_and_excludes_unsafe_exception_state() -> None:
    document = _error_document(_captured_execution_error())
    encoded = json.dumps(document)
    chain = cast(list[dict[str, object]], document["chain"])

    assert document["type"] == "ExecutionError"
    assert document["code"] == "websocket_disconnected"
    assert "message" not in document
    assert document["status"] == 503
    assert document["permanent"] is False
    assert document["retryable"] is True
    assert document["hint"] == "Retry the operation."
    assert document["details"] == {
        "model": "openrouter/anthropic/claude",
        "parameter": "max_tokens",
    }
    assert chain[0]["type"] == "ExecutionError"
    assert "message" not in chain[0]
    assert chain[1]["type"] == "RuntimeError"
    assert chain[1].get("message") is None
    frames = cast(list[dict[str, object]], chain[0]["frames"])
    frame = frames[0]
    assert set(frame) == {"package", "module", "function", "line"}

    assert "sk-local-must-never-leak" not in encoded
    assert "private prompt" not in encoded
    assert "private response" not in encoded
    assert "private provider response" not in encoded
    assert __file__ not in encoded
    assert "raise RuntimeError" not in encoded


def test_unknown_error_capture_omits_arbitrary_message_and_attributes() -> None:
    error = RuntimeError("private arbitrary exception message")
    error.__dict__["secret"] = "private arbitrary attribute"

    document = _error_document(error)
    encoded = json.dumps(document)

    assert document["type"] == "RuntimeError"
    assert "message" not in document
    assert "private arbitrary" not in encoded


def test_typed_error_capture_omits_untrusted_server_message() -> None:
    private_detail = "Patient Alice Smith has condition X."

    encoded = json.dumps(
        _error_document(
            ExecutionError(
                private_detail,
                code="engine_problem",
                status=502,
            )
        )
    )

    assert private_detail not in encoded


def test_unsafe_free_text_in_structured_details_is_not_captured() -> None:
    error = ExecutionError(
        "Candidate compilation failed.",
        code="invalid_candidate_parameter",
        details={"reason": "private rejected value must never leak"},
    )

    assert "private rejected value" not in json.dumps(_error_document(error))


def test_preflight_reason_code_is_retained_as_reproduction_evidence() -> None:
    error = ExecutionError(
        "Parameter is unavailable.",
        code="unsupported_model_parameter",
        details={"reason": "provider_disabled"},
    )

    assert _error_document(error)["details"] == {"reason": "provider_disabled"}


def test_default_screamingface_code_is_retained_as_best_effort_evidence() -> None:
    document = _error_document(ExecutionError("Execution failed."))

    assert document["code"] == "execution_failed"


def test_websocket_close_cause_retains_only_the_code() -> None:
    private_reason = "sk-private-must-never-leak"
    cause = ConnectionClosedError(Close(1011, private_reason), None, None)
    error = ExecutionError("The Engine disconnected.", code="websocket_disconnected")
    error.__cause__ = cause

    chain = cast(list[dict[str, object]], _error_document(error)["chain"])

    assert chain[1]["websocket_close"] == {"received": {"code": 1011}}
    assert private_reason not in json.dumps(chain)


def test_engine_capture_retains_only_host_and_locality() -> None:
    assert _engine_document(
        "https://user:password@engine.screamingface.ai/private?token=secret#fragment"
    ) == {"host": "engine.screamingface.ai", "mode": "hosted"}
    assert _engine_document("http://127.0.0.1:9108/private") == {
        "host": "127.0.0.1",
        "mode": "local",
    }


@pytest.mark.parametrize(
    ("engine_url", "host"),
    [
        ("http://0.0.0.0:9108", "0.0.0.0"),
        ("http://127.0.0.42:9108", "127.0.0.42"),
        ("http://[::]:9108", "::"),
    ],
)
def test_engine_capture_treats_local_ip_aliases_as_local(engine_url: str, host: str) -> None:
    # INVARIANT: support receipts use the same IP-aware locality semantics as Client UI surfaces.
    assert _engine_document(engine_url) == {"host": host, "mode": "local"}


def test_client_capture_is_an_allowlist_not_an_environment_dump(monkeypatch) -> None:
    monkeypatch.setenv("SCREAMINGFACE_PRIVATE_TOKEN", "must-never-leak")

    document = _client_document()
    encoded = json.dumps(document)

    assert document["name"] == "screamingface-python"
    assert document["version"]
    assert document["host"] in {"notebook", "cli"}
    assert set(cast(Mapping[str, object], document["runtime"])) == {"name", "version"}
    assert set(document) == {
        "name",
        "version",
        "host",
        "platform",
        "architecture",
        "runtime",
        "dependencies",
    }
    assert "must-never-leak" not in encoded


def test_client_capture_uses_the_canonical_source_tree_version(monkeypatch) -> None:
    def missing_distribution(_: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr("screamingface._diagnostics.capture.version", missing_distribution)
    monkeypatch.setattr("screamingface._version.distribution_version", missing_distribution)

    assert _client_document()["version"] == SOURCE_TREE_VERSION


def _raise_deep_failure(depth: int) -> None:
    if depth == 0:
        raise RuntimeError("private deep failure")
    _raise_deep_failure(depth - 1)


def test_traceback_bound_retains_the_innermost_failure_frame() -> None:
    try:
        _raise_deep_failure(40)
    except RuntimeError as error:
        traceback = error.__traceback__
        assert traceback is not None
        outermost_line = traceback.tb_lineno
        while traceback.tb_next is not None:
            traceback = traceback.tb_next
        innermost = {
            "module": traceback.tb_frame.f_globals["__name__"],
            "function": traceback.tb_frame.f_code.co_name,
            "line": traceback.tb_lineno,
        }
        chain = cast(list[dict[str, object]], _error_document(error)["chain"])
    else:
        raise AssertionError("deep failure must raise")

    frames = cast(list[dict[str, object]], chain[0]["frames"])
    assert len(frames) == 32
    assert frames[-1]["module"] == innermost["module"]
    assert frames[-1]["function"] == innermost["function"]
    assert frames[-1]["line"] == innermost["line"]
    assert frames[0]["line"] != outermost_line
