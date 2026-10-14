"""The pre-spend check of a regex@1 pattern (OME-1289 gap, RX#11, RE2 decision 2026-10-02).

STORY: as a researcher, a pattern the Engine would refuse fails when I build the recipe, before
any model call is paid for. The Engine's RE2 compile stays authoritative.
"""

from __future__ import annotations

from typing import Any

import pytest

import screamingface as sf
from screamingface import _regex_rule

pytestmark = pytest.mark.filterwarnings("error::FutureWarning")  # no Python warning may escape

_LONG = "a" * 257

# (pattern, extra args, expected error type, expected message part)
_REFUSED: list[tuple[Any, dict[str, Any], type[Exception], str]] = [
    ("(zq", {}, ValueError, "does not compile"),
    ("", {}, ValueError, "1 to 256"),
    (_LONG, {}, ValueError, "1 to 256"),
    (3, {}, TypeError, "pattern must be text"),
    ("zqx", {"ignore_case": "yes"}, TypeError, "ignore_case must be a bool"),
    ("zqx", {"occurrence": "middle"}, ValueError, "occurrence must be"),
    ("(a)", {"group": 2}, ValueError, "group must name a group"),
    ("(?P<ans>a)", {"group": "missing"}, ValueError, "group must name a group"),
    (r"(a)\1", {}, ValueError, "a backreference"),
    ("a(?=b)", {}, ValueError, "a lookaround"),
    ("(a)?(?(1)b|c)", {}, ValueError, "a conditional group"),
    ("(?>a+)", {}, ValueError, "an atomic group"),
    ("a++", {}, ValueError, "a possessive repeat"),
    ("a{1001}", {}, ValueError, "a repeat count over 1000"),
    ("[[:alpha:]]", {}, ValueError, "POSIX"),
    (r"\Q.\E", {}, ValueError, "does not compile"),
    (r"(?a)\w", {}, ValueError, "ASCII, LOCALE or VERBOSE"),
]

_ACCEPTED: list[tuple[str, dict[str, Any]]] = [
    (r"Final: (\w+)", {"group": 1}),
    (r"(?P<ans>[A-D])\)", {"group": "ans"}),
    ("a{1000}", {}),
    (r"\p{L}+", {}),
    (r"[\p{N}x]", {}),
    (r"\\p", {}),
    (r"a\z", {}),
    (r"a\\z", {}),
    (r"\[[:alpha]", {}),
    (r"\P{L}\pL", {}),
    ("(a)", {"group": 0, "occurrence": "first", "ignore_case": True}),
]


# sf.matches takes only a pattern and ignore_case
_MATCHES_REFUSED: list[tuple[Any, dict[str, Any], type[Exception], str]] = [
    ("(zq", {}, ValueError, "does not compile"),
    ("a++", {}, ValueError, "a possessive repeat"),
]
_MATCHES_ACCEPTED: list[tuple[str, dict[str, Any]]] = [("a{1000}", {}), (r"\p{L}+", {})]


def _assert_refused(call: Any, pattern: Any, error: type[Exception], message: str) -> None:
    with pytest.raises(error, match=message) as caught:
        call()
    if isinstance(pattern, str) and pattern:
        assert pattern not in str(caught.value)


@pytest.mark.parametrize(
    ("pattern", "extra", "error", "message"), _REFUSED, ids=[str(i) for i in range(len(_REFUSED))]
)
def test_sdk_extract_regex_validates_before_spend(
    pattern: Any, extra: dict[str, Any], error: type[Exception], message: str
) -> None:
    _assert_refused(lambda: sf.Extract("regex", pattern=pattern, **extra), pattern, error, message)


@pytest.mark.parametrize(("pattern", "extra"), _ACCEPTED)
def test_sdk_extract_regex_accepts_engine_patterns(pattern: str, extra: dict[str, Any]) -> None:
    assert sf.Extract("regex", pattern=pattern, **extra).args["pattern"] == pattern


@pytest.mark.parametrize(
    ("pattern", "extra", "error", "message"),
    _MATCHES_REFUSED,
    ids=["0", "10"],
)
def test_sdk_matches_validates_before_spend(
    pattern: Any, extra: dict[str, Any], error: type[Exception], message: str
) -> None:
    _assert_refused(lambda: sf.matches(pattern, **extra), pattern, error, message)


@pytest.mark.parametrize(("pattern", "extra"), _MATCHES_ACCEPTED)
def test_sdk_matches_accepts_engine_patterns(pattern: str, extra: dict[str, Any]) -> None:
    assert sf.matches(pattern, **extra).pattern == pattern


def test_regex_args_other_than_the_four_are_refused() -> None:
    with pytest.raises(ValueError, match="takes only pattern, group, occurrence and ignore_case"):
        _regex_rule.check_regex({"pattern": "a", "flags": 2}, "sf.Extract('regex')")
    with pytest.raises(ValueError, match="needs a pattern"):
        _regex_rule.check_regex({"group": 1}, "sf.Extract('regex')")


def test_unsupported_construct_names_the_first_hit_and_none_for_supported_syntax() -> None:
    assert _regex_rule.unsupported_construct(r"(a)\1") == "a backreference"
    assert _regex_rule.unsupported_construct(r"x(?=a)(a)\1") == "a lookaround"
    assert _regex_rule.unsupported_construct(r"(?:a|(?>b))") == "an atomic group"
    assert _regex_rule.unsupported_construct(r"(?:a|b+?){0,2}\d") is None
    assert _regex_rule.unsupported_construct(r"\p{L}+(?i:x)") is None
