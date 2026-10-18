"""The credential vocabulary lives outside the legacy Profile module (OME-1209, Stage E, E2a).

# FEATURE: Stage E plan §3 E2a — `AuthType`, `AuthMode`, `credential_name_for` and
# `profile_id_for` are used by every provider plugin, the chat parameter algebra and the Connection
# store. Keeping them in `profile_models.py` tied all of those to the module E4/E5 deletes.
# INVARIANT: `profile_models` defines only the Profile row; the four names have one home each.
"""

from __future__ import annotations

from typing import get_args

import pytest

from aigateway.core import auth_types, credential_names, profile_models


def test_the_profile_module_keeps_only_the_profile_row() -> None:
    defined = {
        name
        for name, value in vars(profile_models).items()
        if getattr(value, "__module__", None) == profile_models.__name__
    }

    assert defined == {"ProfileState", "ProfileDefaults", "Profile", "ProfileIndex"}


@pytest.mark.parametrize("name", ["AuthType", "AuthMode", "credential_name_for", "profile_id_for"])
def test_the_profile_module_exposes_no_neutral_vocabulary(name: str) -> None:
    # WHY `hasattr`, not `__module__`: an imported name is still importable from this module, and
    # a reachable legacy spelling is exactly what would keep E4/E5 from deleting it.
    assert not hasattr(profile_models, name)


def test_the_auth_literals_keep_their_exact_values() -> None:
    # WHY: `none` must stay unforgeable — absent from the persisted type, present in the mode.
    assert get_args(auth_types.AuthType) == ("oauth", "api_key")
    assert get_args(auth_types.AuthMode) == ("oauth", "api_key", "none")


def test_the_locators_keep_their_exact_shapes() -> None:
    # WHY: both strings address stored blobs and documents; a change would orphan existing rows.
    assert credential_names.credential_name_for("acct", "default") == "acct:default"
    assert credential_names.profile_id_for("acct", "anthropic", "default") == (
        "acct:anthropic:default"
    )
