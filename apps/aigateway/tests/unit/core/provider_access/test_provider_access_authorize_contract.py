"""Port contract — `authorize` and `record_dispatch_failure` (OME-1200, spec §3.3 ops 4–5).

# INVARIANT: the two mutating operations of the read interface are exactly the writes the read
# path performs today — error marking, strategy-cache eviction, session invalidation — named so
# consumers stop touching rows. Codes are NOT decided here (edge table).
"""

from __future__ import annotations

from typing import Any

import pytest
from provider_access_harness import (
    ANTHROPIC,
    PROVIDER,
    FakeHarness,
    Harness,
    ProfileBackedHarness,
)

from aigateway.core.provider_access import (
    Authorization,
    CredentialTarget,
    ResolvePolicy,
    Selector,
    TargetReauthRequired,
    apply_authorization,
)

DEFAULT = Selector.from_header(None)


class _NoCredentialPlugin:
    custom_llm_provider = "local"

    def available_auth_modes(self) -> tuple[str, ...]:
        return ("none",)

    def allows_chatless_profile(self) -> bool:
        return True

    def profileless_auth_mode(self) -> str | None:
        return None

    def invalidate_profile_session(self, _name: str) -> None:
        return None


@pytest.fixture(params=["fake", "profile_backed"])
def harness(request: pytest.FixtureRequest) -> Harness:
    if request.param == "fake":
        return FakeHarness()
    return ProfileBackedHarness(
        request.getfixturevalue("authenticated_client"),
        request.getfixturevalue("credential_blobs"),
        request.getfixturevalue("monkeypatch"),
    )


def _resolve(harness: Harness, *, plugin: Any = ANTHROPIC, policy=ResolvePolicy.DISPATCH):
    return harness.call(
        harness.access.resolve, harness.account_id, PROVIDER, DEFAULT, plugin=plugin, policy=policy
    )


def _authorize(harness: Harness, target: CredentialTarget, *, plugin: Any = ANTHROPIC):
    return harness.call(harness.access.authorize, target, plugin=plugin, provider=PROVIDER)


def _record(
    harness: Harness,
    target: CredentialTarget,
    detail: Any,
    *,
    plugin: Any = ANTHROPIC,
    status: int = 401,
):
    return harness.call(
        harness.access.record_dispatch_failure, target, status, detail, plugin=plugin
    )


# --- authorize ------------------------------------------------------------------------------


def test_authorize_yields_a_bearer_header_for_a_stored_oauth_profile(harness: Harness) -> None:
    harness.seed_profile(credential="tok")
    target = _resolve(harness)

    authorization = _authorize(harness, target)
    body: dict[str, Any] = {"model": "x"}
    apply_authorization(body, authorization.headers)

    assert isinstance(authorization, Authorization)
    assert authorization.credential_name == target.credential_name
    assert authorization.auth_type == "oauth"
    assert body["api_key"] == "tok"
    assert "Authorization" not in body.get("extra_headers", {})


def test_authorize_without_a_stored_credential_is_a_reauth_refusal_that_marks_nothing(
    harness: Harness,
) -> None:
    """A MISSING credential (`CredentialNotFoundError`) never flips the profile: the index row
    is fine, only the blob is absent — today's `_inject_credentials` first branch."""
    harness.seed_profile(credential=None)
    target = _resolve(harness)

    with pytest.raises(TargetReauthRequired) as info:
        _authorize(harness, target)

    assert info.value.message
    assert info.value.reauth_url == f"/v1/auth/{PROVIDER}/profiles/default"
    assert harness.profile_state() == "authenticated"


def test_authorize_with_a_rejected_credential_marks_the_profile_errored(harness: Harness) -> None:
    harness.seed_profile(credential="tok")
    target = _resolve(harness)
    harness.break_credential(str(target.credential_name))

    with pytest.raises(TargetReauthRequired) as info:
        _authorize(harness, target)

    assert info.value.message
    assert harness.profile_state() == "error"


def test_authorize_with_a_rejected_connection_credential_marks_the_connection(
    harness: Harness,
) -> None:
    connection_id = harness.seed_connection(label="work", credential="ctok")
    target = _resolve(harness)
    harness.break_credential(str(target.credential_name))

    with pytest.raises(TargetReauthRequired):
        _authorize(harness, target)

    assert harness.connection_status(connection_id) == "error"


def test_authorize_for_a_credential_free_target_is_empty(harness: Harness) -> None:
    target = _resolve(harness, plugin=_NoCredentialPlugin())

    authorization = _authorize(harness, target, plugin=_NoCredentialPlugin())
    body: dict[str, Any] = {}
    apply_authorization(body, authorization.headers)

    assert authorization == Authorization(headers={}, credential_name=None, auth_type="oauth")
    assert body == {}


# --- the side effects spec op 4 names: eviction, invalidation, the last-used touch -----------


def test_a_missing_profile_credential_evicts_but_marks_and_invalidates_nothing(
    harness: Harness,
) -> None:
    """Today's first `except` branch for a PROFILE: evict, refuse — the index row is fine and
    only the blob is absent, so the Profile stays authenticated and its session stands."""
    harness.seed_profile(credential=None)
    target = _resolve(harness)

    with pytest.raises(TargetReauthRequired):
        _authorize(harness, target)

    assert harness.evicted() == [target.credential_name]
    assert harness.invalidated() == []
    assert harness.profile_state() == "authenticated"


def test_a_missing_connection_credential_evicts_and_marks_the_connection_without_invalidating(
    harness: Harness,
) -> None:
    """Today's first `except` branch for a CONNECTION differs from the Profile one: the row IS
    marked `error` (a Connection has no fresh-version fence to protect), but the provider session
    is not invalidated — only a REJECTED credential does that — and nothing is touched."""
    connection_id = harness.seed_connection(label="work", credential=None)
    target = _resolve(harness)

    with pytest.raises(TargetReauthRequired):
        _authorize(harness, target)

    assert harness.evicted() == [target.credential_name]
    assert harness.connection_status(connection_id) == "error"
    assert harness.invalidated() == []
    assert not harness.last_used(connection_id)


def test_a_malformed_credential_result_never_touches_last_used(harness: Harness) -> None:
    """# INVARIANT (review F5): the touch happens only once the headers are known to be a
    mapping — a strategy handing back garbage must not leave a Connection marked as used."""
    connection_id = harness.seed_connection(label="work", credential="ctok")
    target = _resolve(harness)
    harness.malform_credential(str(target.credential_name))

    with pytest.raises(TypeError):
        _authorize(harness, target)

    assert not harness.last_used(connection_id)
    assert harness.connection_status(connection_id) == "active"


def test_a_rejected_profile_credential_evicts_and_invalidates_its_session(
    harness: Harness,
) -> None:
    harness.seed_profile(credential="tok")
    target = _resolve(harness)
    harness.break_credential(str(target.credential_name))

    with pytest.raises(TargetReauthRequired):
        _authorize(harness, target)

    assert harness.evicted() == [target.credential_name]
    assert harness.invalidated() == [target.credential_name]


def test_a_rejected_connection_credential_evicts_and_invalidates_its_session(
    harness: Harness,
) -> None:
    connection_id = harness.seed_connection(label="work", credential="ctok")
    target = _resolve(harness)
    harness.break_credential(str(target.credential_name))

    with pytest.raises(TargetReauthRequired):
        _authorize(harness, target)

    assert harness.evicted() == [target.credential_name]
    assert harness.invalidated() == [target.credential_name]
    assert not harness.last_used(connection_id)


def test_a_successful_connection_authorize_touches_last_used_and_nothing_else(
    harness: Harness,
) -> None:
    """# WHY the touch is pinned INSIDE `authorize`: spec op 4 places it there and makes body
    sealing a separate pure step, so the touch precedes sealing by construction (review F5 —
    declared, not hidden)."""
    connection_id = harness.seed_connection(label="work", credential="ctok")
    target = _resolve(harness)

    _authorize(harness, target)

    assert harness.last_used(connection_id)
    assert harness.evicted() == []
    assert harness.invalidated() == []
    assert harness.connection_status(connection_id) == "active"


def test_a_successful_profile_authorize_writes_nothing(harness: Harness) -> None:
    harness.seed_profile(credential="tok")
    target = _resolve(harness)

    _authorize(harness, target)

    assert harness.evicted() == []
    assert harness.invalidated() == []
    assert harness.profile_state() == "authenticated"


# --- record_dispatch_failure ----------------------------------------------------------------


def test_recording_a_dispatch_failure_on_a_profile_marks_it_and_rewrites_the_detail(
    harness: Harness,
) -> None:
    harness.seed_profile(credential="tok")
    target = _resolve(harness)

    rewritten = _record(harness, target, {"code": "auth_required", "message": "token expired"})

    assert rewritten == {
        "code": "auth_required",
        "message": "token expired",
        "reauth_url": f"/v1/auth/{PROVIDER}/profiles/default",
    }
    assert harness.profile_state() == "error"


def test_recording_a_dispatch_failure_with_a_bare_message_defaults_the_code(
    harness: Harness,
) -> None:
    harness.seed_profile(credential="tok")
    target = _resolve(harness)

    rewritten = _record(harness, target, "upstream said no")

    assert rewritten == {
        "code": "auth_required",
        "message": "upstream said no",
        "reauth_url": f"/v1/auth/{PROVIDER}/profiles/default",
    }


def test_recording_a_dispatch_failure_on_a_connection_marks_it_without_rewriting(
    harness: Harness,
) -> None:
    connection_id = harness.seed_connection(label="work")
    target = _resolve(harness)

    rewritten = _record(harness, target, {"code": "auth_required", "message": "revoked"})

    assert rewritten is None
    assert harness.connection_status(connection_id) == "error"


def test_recording_a_dispatch_failure_on_a_credential_free_target_is_a_no_op(
    harness: Harness,
) -> None:
    target = _resolve(harness, plugin=_NoCredentialPlugin())

    assert _record(harness, target, {"message": "x"}, plugin=_NoCredentialPlugin()) is None


def test_recording_a_dispatch_failure_evicts_and_invalidates_a_profile_credential(
    harness: Harness,
) -> None:
    harness.seed_profile(credential="tok")
    target = _resolve(harness)

    _record(harness, target, {"message": "token expired"})

    assert harness.evicted() == [target.credential_name]
    assert harness.invalidated() == [target.credential_name]


def test_recording_a_dispatch_failure_evicts_and_invalidates_a_connection_credential(
    harness: Harness,
) -> None:
    harness.seed_connection(label="work")
    target = _resolve(harness)

    _record(harness, target, {"message": "revoked"}, status=403)

    assert harness.evicted() == [target.credential_name]
    assert harness.invalidated() == [target.credential_name]
