"""One collection-shape resolver decides reachability for the scan and for admission alike.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review finding 2,
owner decision Sergey 2026-11-04).
STORY: as an ensemble author, an attachment source under a collection that a model produces —
however the collection is reached (``$xs.rows``, ``$zs -> $ys -> $xs``) — is refused
``x.source_not_static`` before any I/O and before any model runs; and a picture under a collection
that is known (before any model call) to be empty is never fetched or sent, a verified blob
collection holding ``[]`` included.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.core.grammar import parse
from url4.core.nodes import Binding, Expression, Iteration, Node
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer

IMG = "https://img.example/a.png"
PNG = b"\x89PNG\r\n\x1a\n-reachability"
BODY = f"src={IMG};accept=image/png"
EMPTY = b"[]"
EMPTY_HEX = hashlib.sha256(EMPTY).hexdigest()
ONE = b'["r"]'
ONE_HEX = hashlib.sha256(ONE).hexdigest()


class _Io(StaticIOLayer):
    """Records every fetch of any kind; ``/m`` is a model-ish relative route."""

    def __init__(self, extra: dict[str, str] | None = None) -> None:
        bodies: dict[str, str | bytes] = {
            IMG: PNG,
            f"/blob/sha256/{EMPTY_HEX}": EMPTY,
            f"/blob/sha256/{ONE_HEX}": ONE,
            **(extra or {}),
        }
        media = {
            IMG: "image/png",
            f"/blob/sha256/{EMPTY_HEX}": "application/json",
            f"/blob/sha256/{ONE_HEX}": "application/json",
            "https://data.example/x.json": "application/json",
        }
        super().__init__(bodies, routes={"/m": self._route}, media_types=media)
        self.calls: list[str] = []

    def _route(self, context: str, intent: str) -> str:
        self.calls.append("route /m")
        return '{"rows": ["a", "b"]}'

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(f"fetch {target}")
        return await super().fetch(target, relative=relative)

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(f"fetch_bytes {request.target}")
        return await super().fetch_bytes(request)

    @property
    def image_fetches(self) -> int:
        return sum(call.endswith(IMG) for call in self.calls)


class _Model:
    def __init__(self) -> None:
        self.seen: list[tuple[Attachment, ...]] = []

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.seen.append(current_attachments())
        return "ok"


# -- model-derived collections: refused before any I/O ------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"(xs=/m(q)!'list', $xs.rows*({BODY})!'d')!'r'",  # a field path into a model result
        f"(xs=/m(q)!'list', ys=$xs, zs=$ys, $zs*({BODY})!'d')!'r'",  # a multi-alias chain
        f"(xs=/m(q)!'list', ys=$xs.rows, $ys[0]*({BODY})!'d')!'r'",  # paths on every hop
        f"(xs=/m(q)!'list';optional, ys=$xs, $ys*({BODY})!'d')!'r'",  # a guarded model hop
        f"(xs=(a, b)!'pick', ys=$xs, $ys*({BODY})!'d')!'r'",  # a processed group
    ],
)
@pytest.mark.asyncio
async def test_a_model_derived_collection_is_not_static_before_any_io(text: str) -> None:
    io, model = _Io(), _Model()
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=model)
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert caught.value.permanent is True
    assert io.calls == []  # no image, no collection fetch, no /m route
    assert model.seen == []


# -- model-free collections: resolved before reachability and order -------------------------


@pytest.mark.parametrize(
    ("text", "fetched"),
    [
        (f"(/blob/sha256/{EMPTY_HEX}*({BODY})!'d')!'r'", 0),
        (f"(src=blob:sha256/{EMPTY_HEX}*({BODY})!'d')!'r'", 0),
        (f"(e=blob:sha256/{EMPTY_HEX}, $e*({BODY})!'d')!'r'", 0),
        (f"(src=blob:sha256/{ONE_HEX}*({BODY})!'d')!'r'", 1),
        (f"(/blob/sha256/{ONE_HEX}*({BODY})!'d')!'r'", 1),
        (f"(e=blob:sha256/{ONE_HEX}, $e*({BODY})!'d')!'r'", 1),
    ],
)
@pytest.mark.asyncio
async def test_a_verified_blob_collection_decides_reachability(text: str, fetched: int) -> None:
    io, model = _Io(), _Model()
    assert await run(text, io, process=model) == "ok"
    assert io.image_fetches == fetched
    # INVARIANT: an unreachable picture is never sent, not even to the reducer. (A blob BOUND
    # in scalar position, ``e=blob:…``, is itself attached — F2 — so only the image is checked.)
    sent = {a.media_type for seen in model.seen for a in seen}
    assert ("image/png" in sent) == bool(fetched)


@pytest.mark.parametrize(
    ("text", "fetched"),
    [
        (f"""(xs='{{"rows": []}}', $xs.rows*({BODY})!'d')!'r'""", 0),
        (f"""(xs='{{"rows": ["a"]}}', $xs.rows*({BODY})!'d')!'r'""", 1),
        (f"""(xs='["a"]', ys=$xs, zs=$ys, $zs*({BODY})!'d')!'r'""", 1),
        (f"""(xs='[]', ys=$xs, zs=$ys, $zs*({BODY})!'d')!'r'""", 0),
        (f"""(xs='{{"a": {{"rows": []}}}}', ys=$xs.a, $ys.rows*({BODY})!'d')!'r'""", 0),
    ],
)
@pytest.mark.asyncio
async def test_a_model_free_chain_or_path_is_followed_to_its_rows(text: str, fetched: int) -> None:
    io, model = _Io(), _Model()
    assert await run(text, io, process=model) == "ok"
    assert io.image_fetches == fetched


@pytest.mark.parametrize(("rows", "fetched"), [("[]", 0), ('["a"]', 1)])
@pytest.mark.asyncio
async def test_a_fetched_binding_with_a_path_is_resolved_once(rows: str, fetched: int) -> None:
    data = "https://data.example/x.json"
    io, model = _Io({data: f'{{"rows": {rows}}}'}), _Model()
    assert await run(f"(xs={data}, $xs.rows*({BODY})!'d')!'r'", io, process=model) == "ok"
    assert io.image_fetches == fetched
    assert sum(call.endswith(data) for call in io.calls) == 1  # admission's fetch is replayed


@pytest.mark.asyncio
async def test_an_alias_of_a_blob_binding_is_its_ref_text_so_the_body_never_runs() -> None:
    # WHY: only a DIRECT ``$e*`` reads a bound blob's body (plan §2.9); through an alias the
    # value is the ref TEXT (F2), a scalar, so execution fails the collection and the body
    # never runs. Admission must agree: the picture is unreachable and never fetched.
    from url4.core.errors import CollectionError

    io, model = _Io(), _Model()
    text = f"(e=blob:sha256/{ONE_HEX}, f=$e, $f*({BODY})!'d')!'r'"
    with pytest.raises(CollectionError):
        await run(text, io, process=model)
    assert io.image_fetches == 0


# -- the resolver itself --------------------------------------------------------------------


def _bound(text: str) -> tuple[Node, dict[str, Node]]:
    ast = parse(text)
    assert isinstance(ast, Expression)
    *bindings, iteration = ast.sources
    assert isinstance(iteration, Iteration)
    return iteration.collection, {b.name: b.value for b in bindings if isinstance(b, Binding)}


def test_a_binding_cycle_terminates_as_unknown() -> None:
    from url4.dag._collection_shape import UNKNOWN, resolve_collection

    items, bound = _bound("(xs=$ys, ys=$xs, $xs*($item)!'d')!'r'")
    assert resolve_collection(items, bound).kind == UNKNOWN


def test_a_row_reference_is_unknown_and_a_model_hop_anywhere_is_model() -> None:
    from url4.dag._collection_shape import MODEL, UNKNOWN, resolve_collection

    items, bound = _bound("(a=/m(q)!'x', b=$a.k, c=$b, $c[1]*($item)!'d')!'r'")
    assert resolve_collection(items, bound).kind == MODEL
    items, bound = _bound("(c=$item, $c*($item)!'d')!'r'")
    assert resolve_collection(items, bound).kind == UNKNOWN
