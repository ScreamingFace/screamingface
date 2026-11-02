"""The credential vocabulary lives outside the legacy Profile module (OME-1209, Stage E, E2a).

# FEATURE: Stage E plan §3 E2a — `AuthType` and `AuthMode` are used by every provider plugin, the
# chat parameter algebra and the Connection store. Keeping them in `profile_models.py` tied all of
# those to the module E5c deletes.
# INVARIANT: each name has one home outside the retired Profile module. `credential_name_for`
# moved to the test helper `tests/credential_names.py` in the OME-1138 close-out (L4b): production
# never builds a blob address from a name, only from a Connection id (`credential_key_for`) or a
# Connection's stored locator, so only tests spell one from a name.

Retired at OME-1138 Stage E, E5c: `test_the_profile_module_keeps_only_the_profile_row` and
`test_the_profile_module_exposes_no_neutral_vocabulary` — the Profile module is deleted, so there is
no row left to keep and no legacy spelling left to reach; successor:
`test_profile_index_offline_only.py::test_the_profile_vocabulary_and_its_offline_tools_are_gone`.
`profile_id_for` went with it: `test_profile_index_offline_only.py::`
`test_only_the_neutral_credential_name_remains` (itself retired at L4b; see there).
"""

from __future__ import annotations

from typing import get_args

from aigateway.core import auth_types
from aigateway.core.oauth.store import credential_locator_for
from tests.credential_names import credential_name_for


def test_the_auth_literals_keep_their_exact_values() -> None:
    # WHY: `none` must stay unforgeable — absent from the persisted type, present in the mode.
    assert get_args(auth_types.AuthType) == ("oauth", "api_key")
    assert get_args(auth_types.AuthMode) == ("oauth", "api_key", "none")


def test_the_locators_keep_their_exact_shapes() -> None:
    assert credential_name_for("acct", "default") == "acct:default"
    # INVARIANT: the helper spells the address production stores in a Connection's locator, so a
    # test that seeds a blob by name seeds it where the Connection reads it.
    assert credential_locator_for("anthropic", "acct", "default") == {
        "service": f"aigateway:anthropic:{credential_name_for('acct', 'default')}",
        "account": "default",
    }
