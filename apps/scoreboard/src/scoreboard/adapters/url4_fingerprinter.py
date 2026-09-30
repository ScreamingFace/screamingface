"""SystemFingerprinter over the pure url4.fingerprint helper (C11: the one url4 import site).

FEATURE: OME-1307 (E14) — D3: the system identity is
`system_fingerprint(linked, binding="candidate", exclude_bindings=frozenset({"_sf_recipe"}))`.
"""

from __future__ import annotations

import hashlib

import url4
from url4.fingerprint import CANDIDATE_BINDING, canonical_system_url4

from scoreboard.core.registry import InvalidUrl4, SystemIdentity

SDK_METADATA_BINDINGS: frozenset[str] = frozenset({"_sf_recipe"})
"""Root-level Candidate bindings that are SDK metadata, not part of the system (D3).

Mirrors `_SOURCE_NAME` in packages/screamingface/src/screamingface/_evaluation/topology.py:14.
C11 forbids the SDK import, so the value is mirrored. SR-5-SB pins it against the
`exclude_bindings` list of packages/url4/tests/fixtures/fingerprint_vectors.json.
"""


class Url4Fingerprinter:
    """SystemFingerprinter over the pure url4.fingerprint helper.

    INVARIANT: every call passes `exclude_bindings=SDK_METADATA_BINDINGS`. With the default empty
    set the SDK recipe display name would change the fingerprint, and a rename would dodge
    clustering (SR-H3, SR-D1 risk).
    """

    def identify(self, linked_url4: str) -> SystemIdentity:
        # WHY `canonical_system_url4` plus a local sha256, not two calls: one parse, and url4
        # guarantees sha256(candidate_url4) == system_fingerprint(...) for equal arguments.
        try:
            candidate = canonical_system_url4(
                linked_url4, CANDIDATE_BINDING, exclude_bindings=SDK_METADATA_BINDINGS
            )
        except url4.Url4Error as exc:
            # WHY one `except`: `ExcludedBindingError` is a `Url4Error`. A client that names a
            # working member `_sf_recipe` sends a url4 that cannot be fingerprinted safely: a bad
            # url4 (SR-E6, 422 invalid_url4), not a server fault.
            raise InvalidUrl4(str(exc)) from exc
        except RecursionError as exc:
            # WHY: url4 parses and renders recursively, so a short, deeply nested text escapes as
            # `RecursionError`, far under the 32,000 character cap. The port contract is
            # `InvalidUrl4` (422, and a `backfill_systems` row instead of an aborted run). The
            # input is never echoed.
            raise InvalidUrl4("url4 expression is nested too deeply") from exc
        return SystemIdentity(
            fingerprint=hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
            candidate_url4=candidate,
        )
