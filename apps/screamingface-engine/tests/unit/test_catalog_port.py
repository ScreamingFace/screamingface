from __future__ import annotations

import pytest

from screamingface_engine.catalog.port import (
    CatalogBadResponse,
    CatalogError,
    CatalogRejected,
    CatalogSource,
    CatalogUnavailable,
    Credential,
    ModelCatalog,
    compute_etag,
)

BODY = {"object": "list", "data": [{"id": "claude-haiku-4-5", "object": "model"}]}


class _StubSource:
    async def fetch(self, credential: Credential) -> ModelCatalog:
        return ModelCatalog(body=BODY, etag=compute_etag(BODY))


def test_stub_satisfies_the_catalog_source_port() -> None:
    assert isinstance(_StubSource(), CatalogSource)


def test_etag_is_stable_across_key_ordering() -> None:
    reordered = {"data": BODY["data"], "object": "list"}
    assert compute_etag(BODY) == compute_etag(reordered)


def test_etag_differs_for_different_bodies() -> None:
    other = {"object": "list", "data": []}
    assert compute_etag(BODY) != compute_etag(other)


def test_etag_is_a_short_hex_digest() -> None:
    etag = compute_etag(BODY)
    assert len(etag) == 16
    assert all(char in "0123456789abcdef" for char in etag)


_ALICE = {"X-User-Email": "alice@example.com"}
_BOB = {"X-User-Email": "bob@example.com"}


def test_same_identity_derives_the_same_key() -> None:
    assert Credential.derive(_ALICE).key == Credential.derive(_ALICE).key


def test_distinct_identities_derive_distinct_keys() -> None:
    assert Credential.derive(_ALICE).key != Credential.derive(_BOB).key


def test_identity_components_are_not_confusable() -> None:
    assert (
        Credential.derive({"X-User-Email": "ab", "X-Other": "c"}).key
        != Credential.derive({"X-User-Email": "a", "X-Other": "bc"}).key
    )


# INVARIANT: an anonymous caller (local mode, aigateway auth disabled) must not share a cache
# entry with an identified one, or a local dev response could be served to a real principal.
def test_an_absent_identity_gets_its_own_key() -> None:
    assert Credential.derive().key != Credential.derive(_ALICE).key


def test_identity_key_material_is_order_independent() -> None:
    pair = {"X-User-Email": "a@b.c", "X-Other": "z"}
    reversed_pair = dict(reversed(list(pair.items())))
    assert Credential.derive(pair).key == Credential.derive(reversed_pair).key


def test_key_is_fixed_length_regardless_of_identity_length() -> None:
    short = Credential.derive({"X-User-Email": "x"})
    long = Credential.derive({"X-User-Email": "y" * 10_000})
    assert len(short.key) == len(long.key) == 32


@pytest.mark.parametrize(
    ("error", "status"),
    [(CatalogRejected, 401), (CatalogBadResponse, 502), (CatalogUnavailable, 504)],
)
def test_each_error_carries_the_status_the_route_maps_it_to(
    error: type[CatalogError], status: int
) -> None:
    assert error("boom").status == status
    assert isinstance(error("boom"), CatalogError)
