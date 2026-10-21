"""The Profile index's API-key-era shape (SF-244).

The tenant Profile API-key route tests (set, replace, rollback, refusals, delete, refresh,
pending-OAuth cancellation, OAuth flip-back, patch) retired at OME-1209 Stage E3: those routes
answer 410 `legacy_profile_api_retired` since then (`test_legacy_profile_routes_retired.py`).
Their successors are the native API-key Connection tests —
`test_oauth_connection_api_key_routes.py`, `test_api_key_connection_validation.py` and
`test_api_key_connection_races.py` — plus
`test_profile_retirement_successor_coverage.py` for the native Gemini key.
"""

from __future__ import annotations

import json

from aigateway.core.profile_index import ProfileIndexStore


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def test_legacy_profile_index_defaults_to_oauth_auth_type(
    authenticated_client, credential_blobs
) -> None:
    """Index blobs written before the auth_type field deserialize with the
    'oauth' default — the no-migration-friction constraint."""
    account_id = _account_id(authenticated_client)
    credential_blobs.write(
        "aigateway:index",
        "default",
        json.dumps(
            {
                "version": 1,
                "profiles": [
                    {
                        "id": f"{account_id}:anthropic:legacy",
                        "account_id": account_id,
                        "provider": "anthropic",
                        "name": "legacy",
                        "state": "authenticated",
                    }
                ],
            }
        ),
    )

    # WHY the store: the Profile listing route answers 410 since OME-1209 Stage E3; the index
    # read is the deserialisation under test.
    index = ProfileIndexStore(credential_store=authenticated_client.app.state.credential_store)
    listed = authenticated_client.portal.call(index.list, account_id, "anthropic")

    (profile,) = [p for p in listed if p.name == "legacy"]
    assert profile.auth_type == "oauth"
