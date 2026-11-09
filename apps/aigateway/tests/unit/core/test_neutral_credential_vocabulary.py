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

import ast
import importlib.util
import inspect
from collections.abc import Iterator
from pathlib import Path
from typing import get_args

import pytest

import aigateway
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


_SRC = Path(inspect.getfile(aigateway)).resolve().parent


# WHY these fields: they are every place the AST keeps an identifier — a name read or bound, an
# attribute, a parameter or keyword, a def, class, `except … as` or match capture, an import, its
# module or its alias, and a `global`/`nonlocal` name. A dotted import path is split into its parts.
_IDENTIFIER_FIELDS = ("id", "attr", "arg", "name", "asname", "module", "names", "rest", "kwd_attrs")


def _spellings(value: object) -> list[str]:
    # WHY a list too: `global`/`nonlocal` names and a class pattern's keywords are lists of strings.
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, str)]


def _identifiers(tree: ast.AST) -> Iterator[tuple[str, int]]:
    """Every identifier a module spells, with its line; strings and comments are not identifiers."""
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        for field in _IDENTIFIER_FIELDS:
            for spelled in _spellings(getattr(node, field, None)):
                yield from ((part, line) for part in spelled.split("."))


def _profile_name_lines(source: str) -> list[int]:
    return [line for name, line in _identifiers(ast.parse(source)) if name == "profile_name"]


@pytest.mark.parametrize(
    "source",
    [
        "profile_name",
        "profile_name = value",
        "value.profile_name",
        "def f(profile_name): ...",
        "f(profile_name=value)",
        "def profile_name(): ...",
        "async def profile_name(): ...",
        "class profile_name: ...",
        "import profile_name",
        "import module.profile_name",
        "from profile_name import value",
        "from module import value as profile_name",
        "global profile_name",
        "try:\n    pass\nexcept E as profile_name:\n    pass",
        "match value:\n    case profile_name:\n        pass",
        "match value:\n    case [*profile_name]:\n        pass",
        "match value:\n    case {**profile_name}:\n        pass",
        "match value:\n    case C(profile_name=x):\n        pass",
    ],
)
def test_the_identifier_scan_sees_every_spelling(source: str) -> None:
    # WHY: a positive control per form, so the src guard below cannot pass because the scan misses
    # a way of naming `profile_name`.
    assert _profile_name_lines(source)


def test_the_identifier_scan_ignores_text() -> None:
    # WHY: a string or a comment is not an identifier; the dropped `profile=` log fields are
    # pinned by the dispatch log tests, not by this scan.
    assert _profile_name_lines('label = "profile_name"  # profile_name\n') == []


def test_no_src_module_names_a_profile_name() -> None:
    # WHY (OME-1138 close-out, L5): a credential's address is a credential name and the chat
    # selector is always `default`, so `profile_name` names nothing a reader can find.
    # WHY `migrations/` is exempt: an applied migration is history and keeps the column names of
    # its time.
    sites = {
        f"{path.relative_to(_SRC)}:{line}"
        for path in _SRC.rglob("*.py")
        if path.relative_to(_SRC).parts[0] != "migrations"
        for name, line in _identifiers(ast.parse(path.read_text(encoding="utf-8")))
        if name == "profile_name"
    }

    assert sites == set()


def test_the_authorize_module_carries_the_connection_name() -> None:
    assert importlib.util.find_spec("aigateway.core.provider_access.profile_authorize") is None
    assert importlib.util.find_spec("aigateway.core.provider_access.connection_authorize")
