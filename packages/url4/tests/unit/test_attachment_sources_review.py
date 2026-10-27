"""Round-7 review findings: collection admission under its own policy, and slot preorder.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; #1450 F1b round 7).
STORY: as an ensemble author my ``;accept=image/png`` picture reaches every model call even
when the collection gating it needs a retry, and it sits in ``attachments[]`` where its first
reachable occurrence is — never where an unreachable one was written.

INVARIANT (F1b): non-model collection inputs are resolved "with their normal source semantics"
(``;retry=`` / ``;t=`` / ``;optional``) before the first model call, and execution reuses that
outcome; ``x.source_not_static`` is never raised for a literal URL after a model call. One
attachment per identity, at its first occurrence in the manifest's (reachable) preorder.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-review"
JPG = b"\xff\xd8\xff\xe0review-jpeg"
IMG_URL = "https://img.example/photo.png"
JPG_URL = "https://img.example/photo.jpg"
ROWS_URL = "https://rows.example/rows.json"


def _att(body: bytes, media_type: str) -> Attachment:
    return Attachment(f"sha256:{hashlib.sha256(body).hexdigest()}", media_type, body)


IMG = _att(PNG, "image/png")
JPEG = _att(JPG, "image/jpeg")


class _Web(StaticIOLayer):
    """A fake web logging every text / bytes fetch; ``flaky[url]`` transient failures first."""

    def __init__(self, rows: str = '["a", "b"]', events: list[str] | None = None) -> None:
        super().__init__(
            {IMG_URL: PNG, JPG_URL: JPG, ROWS_URL: rows, "/rows": rows},
            media_types={
                IMG_URL: "image/png",
                JPG_URL: "image/jpeg",
                ROWS_URL: "application/json",
            },
        )
        self.events = events if events is not None else []
        self.flaky: dict[str, int] = {}
        self.requests: list[FetchRequest] = []

    def text_fetches(self, target: str) -> int:
        return self.events.count(f"text:{target}")

    def byte_fetches(self, target: str | None = None) -> int:
        if target is None:
            return sum(1 for event in self.events if event.startswith("bytes:"))
        return self.events.count(f"bytes:{target}")

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.events.append(f"text:{request.target}")
        self.requests.append(request)
        self._maybe_flaky(request.target)
        return await super().fetch_ex(request)

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.events.append(f"bytes:{request.target}")
        self._maybe_flaky(request.target)
        got = await super().fetch_bytes(request)
        self.events.append(f"done:{request.target}")
        return got

    def _maybe_flaky(self, target: str) -> None:
        left = self.flaky.get(target, 0)
        if left:
            self.flaky[target] = left - 1
            raise ResolutionError(f"flaky {target!r}", code=ErrorCode.TIMEOUT, permanent=False)


class _Model:
    """A ``process`` hook recording payloads, attachments and its place in the event log."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.payloads: list[str] = []
        self.seen: list[tuple[Attachment, ...]] = []

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.events.append("model")
        self.payloads.append(sources)
        self.seen.append(current_attachments())
        return "ok"


def _pair(rows: str = '["a", "b"]') -> tuple[_Web, _Model]:
    events: list[str] = []
    return _Web(rows, events), _Model(events)


def _before_first_model(events: list[str]) -> list[str]:
    return events[: events.index("model")] if "model" in events else list(events)


# -- finding 1: a collection is admitted under its own descriptor guard policy -------------


@pytest.mark.asyncio
async def test_transient_collection_failure_with_retry_still_attaches_before_the_first_call() -> (
    None
):
    io, model = _pair()
    io.flaky[ROWS_URL] = 1  # the first collection fetch fails transiently; ;retry=2 recovers
    text = f"(rows:src={ROWS_URL};retry=2, $rows*(src={IMG_URL};accept=image/png)!'d')!'r'"
    assert await run(text, io, process=model) == "ok"
    assert io.byte_fetches(IMG_URL) == 1
    assert f"done:{IMG_URL}" in _before_first_model(io.events)
    assert len(model.seen) == 3  # two rows and the reduce
    assert all(seen == (IMG,) for seen in model.seen)
    assert not any(ErrorCode.SOURCE_NOT_STATIC in payload for payload in model.payloads)
    # Resolved once, at admission (one failed attempt + one success); execution reuses it.
    assert io.text_fetches(ROWS_URL) == 2


@pytest.mark.asyncio
async def test_inline_annotated_collection_is_admitted_under_its_retry_policy() -> None:
    io, model = _pair()
    io.flaky[ROWS_URL] = 1
    text = f"((src={ROWS_URL};retry=1)*(src={IMG_URL};accept=image/png)!'d')!'r'"
    await run(text, io, process=model)
    assert io.byte_fetches(IMG_URL) == 1
    assert model.seen and all(seen == (IMG,) for seen in model.seen)
    assert io.text_fetches(ROWS_URL) == 2


@pytest.mark.asyncio
async def test_exhausted_retries_fail_the_run_as_today_without_attachment_io() -> None:
    io, model = _pair()
    io.flaky[ROWS_URL] = 5  # more failures than ;retry=1 allows
    text = f"(rows:src={ROWS_URL};retry=1, $rows*(src={IMG_URL};accept=image/png)!'d')!'r'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=model)
    assert caught.value.code == ErrorCode.TIMEOUT
    assert io.byte_fetches() == 0
    assert model.seen == []
    # The policy ran once, at admission; execution replays its outcome instead of retrying.
    assert io.text_fetches(ROWS_URL) == 2


@pytest.mark.asyncio
async def test_failed_optional_collection_makes_no_attachment_io_and_is_never_not_static() -> None:
    io, model = _pair()
    io.flaky[ROWS_URL] = 1
    text = f"(rows:src={ROWS_URL};optional, $rows*(src={IMG_URL};accept=image/png)!'d')!'r'"
    # Today an omitted optional binding leaves ``$rows`` unbound, so the iteration fails with
    # its collection error; whatever the run does, it is never the attachment's not-static code.
    with pytest.raises(Exception) as caught:
        await run(text, io, process=model)
    assert getattr(caught.value, "code", None) != ErrorCode.SOURCE_NOT_STATIC
    assert io.byte_fetches() == 0
    assert io.text_fetches(ROWS_URL) == 1  # execution reuses admission's failure
    assert not any(ErrorCode.SOURCE_NOT_STATIC in payload for payload in model.payloads)


@pytest.mark.asyncio
async def test_collection_with_an_accept_is_fetched_once_with_that_accept() -> None:
    io, model = _pair()
    text = (
        f"(rows:src={ROWS_URL};accept=application/json, "
        f"$rows*(src={IMG_URL};accept=image/png)!'d')!'r'"
    )
    await run(text, io, process=model)
    assert io.text_fetches(ROWS_URL) == 1
    rows_requests = [request for request in io.requests if request.target == ROWS_URL]
    assert [request.accept for request in rows_requests] == ["application/json"]
    assert io.byte_fetches(IMG_URL) == 1


@pytest.mark.asyncio
async def test_relative_collection_is_admitted_under_its_retry_and_accept() -> None:
    events: list[str] = []
    io, model = _Web(events=events), _Model(events)
    io.flaky["/rows"] = 1
    text = f"((src=/rows;retry=1;accept=application/json)*(src={IMG_URL};accept=image/png)!'d')!'r'"
    await run(text, io, process=model)
    assert io.byte_fetches(IMG_URL) == 1
    assert model.seen and all(seen == (IMG,) for seen in model.seen)
    rows_requests = [request for request in io.requests if request.target == "/rows"]
    assert [request.accept for request in rows_requests] == ["application/json"] * 2


# -- finding 2: an identity's slot is its first REACHABLE occurrence ------------------------

_ORDER = (
    f"({ROWS_URL}*(src={IMG_URL};accept=image/png)!'d', "
    f"src={JPG_URL};accept=image/jpeg, src={IMG_URL};accept=image/png)!'r'"
)


@pytest.mark.asyncio
async def test_unreachable_first_occurrence_does_not_fix_the_identity_slot() -> None:
    io, model = _pair(rows="[]")
    await run(_ORDER, io, process=model)
    assert model.seen == [(JPEG, IMG)]  # manifest preorder: JPG, then IMG's reachable one


@pytest.mark.asyncio
async def test_reachable_first_occurrence_keeps_the_identity_slot() -> None:
    io, model = _pair(rows='["a"]')
    await run(_ORDER, io, process=model)
    assert model.seen and all(seen == (IMG, JPEG) for seen in model.seen)
    assert io.byte_fetches(IMG_URL) == 1


@pytest.mark.asyncio
async def test_unreachable_identity_takes_no_slot_and_case_attachments_lead() -> None:
    io, model = _pair(rows="[]")
    case = _att(b"case-bytes", "application/pdf")
    text = f"({ROWS_URL}*(src={IMG_URL};accept=image/png)!'d', src={JPG_URL};accept=image/jpeg)!'r'"
    await run(text, io, process=model, attachments=[case])
    assert model.seen == [(case, JPEG)]
    assert io.byte_fetches(IMG_URL) == 0
