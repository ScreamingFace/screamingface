"""The credential vocabulary lives outside the legacy Profile module (OME-1209, Stage E, E2a).

# FEATURE: Stage E plan §3 E2a — `AuthType`, `AuthMode` and `credential_name_for` are used by
# every provider plugin, the chat parameter algebra and the Connection store. Keeping them in
# `profile_models.py` tied all of those to the module E5c deletes.
# INVARIANT: each name has one home outside the retired Profile module.

Retired at OME-1138 Stage E, E5c: `test_the_profile_module_keeps_only_the_profile_row` and
`test_the_profile_module_exposes_no_neutral_vocabulary` — the Profile module is deleted, so there is
no row left to keep and no legacy spelling left to reach; successor:
`test_profile_index_offline_only.py::test_the_profile_vocabulary_and_its_offline_tools_are_gone`.
`profile_id_for` went with it: `test_profile_index_offline_only.py::`
`test_only_the_neutral_credential_name_remains`.
"""

from __future__ import annotations

from typing import get_args

from aigateway.core import auth_types, credential_names


def test_the_auth_literals_keep_their_exact_values() -> None:
    # WHY: `none` must stay unforgeable — absent from the persisted type, present in the mode.
    assert get_args(auth_types.AuthType) == ("oauth", "api_key")
    assert get_args(auth_types.AuthMode) == ("oauth", "api_key", "none")


def test_the_locators_keep_their_exact_shapes() -> None:
    # WHY: the string addresses stored blobs; a change would orphan existing rows.
    assert credential_names.credential_name_for("acct", "default") == "acct:default"
