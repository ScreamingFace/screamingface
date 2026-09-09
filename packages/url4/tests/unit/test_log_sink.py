"""Structured emission is optional evidence with immutable flat snapshots."""

from collections.abc import Mapping
from operator import setitem
from typing import Any, cast

import pytest

from url4.dag import run
from url4.io.static import StaticIOLayer
from url4.observe import Log, current_log_sink


class Recorder:
    def __init__(self):
        self.events = []

    def on_event(self, event):
        self.events.append(event)

    @property
    def logs(self):
        return [e for e in self.events if isinstance(e, Log)]


class EmitNode:
    deps: dict = {}

    def __init__(self, action):
        self.action = action

    async def resolve(self, inputs, ctx):
        self.action(ctx)
        return "result"


def emit(body: Any = "record", attributes: Any = None, severity: Any = "INFO") -> None:
    sink = current_log_sink()
    assert sink is not None
    sink(body, attributes, severity=severity)


def test_log_preserves_old_construction_and_immutable_attributes():
    assert Log("span", "custom", "body").attributes == {}
    attrs = {"count": 1}
    record = Log("span", "INFO", "body", attrs)
    attrs["count"] = 2
    assert record.attributes == {"count": 1}
    with pytest.raises(TypeError):
        setitem(cast(Any, record.attributes), "count", 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("severity", ["DEBUG", "INFO", "WARN", "ERROR"])
async def test_scalar_snapshot_and_severity_normalization(severity):
    attrs = {"text": "v", "count": 1, "duration": 1.5, "ok": True, "unknown": None}
    rec = Recorder()

    def action(ctx):
        emit(attributes=attrs, severity=f" {severity.lower()} ")
        attrs["count"] = 99

    assert await run(EmitNode(action), StaticIOLayer(), observer=rec) == "result"
    assert len(rec.logs) == 1
    assert rec.logs[0].severity == severity
    assert rec.logs[0].attributes["count"] == 1
    assert rec.logs[0].attributes["unknown"] is None


class CustomString(str):
    pass


class CustomInt(int):
    pass


class BrokenMapping(Mapping):
    def __iter__(self):
        raise RuntimeError("private payload")

    def __len__(self):
        return 1

    def __getitem__(self, key):
        raise RuntimeError("private payload")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body, attrs, severity",
    [
        ("", {}, "INFO"),
        (None, {}, "INFO"),
        (b"secret", {}, "INFO"),
        (CustomString("secret"), {}, "INFO"),
        ("body", {1: "bad key"}, "INFO"),
        ("body", {CustomString("key"): 1}, "INFO"),
        ("body", {"valid": 1, "invalid": []}, "INFO"),
        ("body", {"invalid": {}}, "INFO"),
        ("body", {"invalid": b"secret"}, "INFO"),
        ("body", {"invalid": CustomInt(1)}, "INFO"),
        ("body", {"invalid": float("nan")}, "INFO"),
        ("body", {"invalid": float("inf")}, "INFO"),
        ("body", {"invalid": float("-inf")}, "INFO"),
        ("body", [("key", 1)], "INFO"),
        ("body", BrokenMapping(), "INFO"),
        ("body", {}, "WARNING"),
        ("body", {}, "TRACE"),
        ("body", {}, "FATAL"),
        ("body", {}, ""),
        ("body", {}, "unknown"),
        ("body", {}, 9),
        ("body", {}, None),
        ("body", {}, CustomString("INFO")),
    ],
)
async def test_invalid_record_drops_whole_without_affecting_result(body, attrs, severity, caplog):
    rec = Recorder()
    node = EmitNode(lambda ctx: emit(body, attrs, severity))
    assert await run(node, StaticIOLayer(), observer=rec) == "result"
    assert rec.logs == []
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_direct_log_preserves_custom_severity_and_copies_attributes():
    rec = Recorder()
    attrs = {"count": 1}

    def action(ctx):
        ctx.log("custom", "body", attributes=attrs)
        attrs["count"] = 2

    await run(EmitNode(action), StaticIOLayer(), observer=rec)
    assert rec.logs[0].severity == "custom"
    assert rec.logs[0].attributes == {"count": 1}


class RaisingObserver:
    def __init__(self, error):
        self.error = error
        self.attempts = 0

    def on_event(self, event):
        if isinstance(event, Log):
            self.attempts += 1
            raise self.error


@pytest.mark.asyncio
async def test_safe_sink_contains_observer_failures_without_diagnostics(caplog):
    observer = RaisingObserver(RuntimeError("private payload"))
    node = EmitNode(lambda ctx: [emit() for _ in range(20)])
    assert await run(node, StaticIOLayer(), observer=observer) == "result"
    assert observer.attempts == 20
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_direct_log_still_propagates_original_observer_error():
    observer = RaisingObserver(RuntimeError("original"))
    with pytest.raises(RuntimeError) as caught:
        await run(EmitNode(lambda ctx: ctx.log("INFO", "body")), StaticIOLayer(), observer=observer)
    assert caught.value is observer.error


@pytest.mark.asyncio
async def test_process_control_is_not_swallowed():
    # WHY: catch inside resolve so SystemExit cannot escape the test's asyncio runner.
    for error in (KeyboardInterrupt(), SystemExit()):
        observer = RaisingObserver(error)

        def action(ctx):
            with pytest.raises(type(error)) as caught:
                emit()
            assert caught.value is error

        await run(EmitNode(action), StaticIOLayer(), observer=observer)
