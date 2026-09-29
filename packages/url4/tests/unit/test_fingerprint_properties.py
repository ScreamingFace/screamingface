"""SR-2: normalizable spellings of one Candidate give one fingerprint (a Hypothesis property).

STORY: as a user I write my url4 in the spelling I like (`:0:` or `:0.0:`, `(ctx)` or `?q=(ctx)`,
`;k=v` or `?k=v&q=`, any space after a comma) and I still land on one leaderboard row.

# AIDEV-NOTE: the settings make the run repeatable in CI: fixed examples (`derandomize`), and no
# `.hypothesis/` directory (`database=None`; the directory is not gitignored).
# WHY: the strategy draws only valid url4, from `sampled_from` and small text. A canonical form
# that is not canonical is a defect of the strategy, so the property asserts it loudly and does
# not use `assume()`.
"""

from __future__ import annotations

import hashlib

from hypothesis import given, settings
from hypothesis import strategies as st

from url4 import build, expr, render, src, text
from url4.fingerprint import system_fingerprint

SF = frozenset({"_sf_recipe"})
_B1 = build("(answer:0.0:/candidate(question)!'$candidate')!'$answer'")

Params = list[tuple[str, str]]
Member = tuple[str, str, Params]

_PATHS = [
    "/openrouter/model",
    "/provider/a",
    "/provider/b",
    "/openai/gpt-5",
    "/anthropic/claude-opus",
]
_PARAMS = [("temperature", "0.2"), ("max_tokens", "64"), ("top_p", "0.9")]

_member = st.tuples(
    st.sampled_from(_PATHS),
    st.text(alphabet=st.sampled_from(list("abcXYZ 019.,?-'")), min_size=1, max_size=40),
    st.lists(st.sampled_from(_PARAMS), unique_by=lambda p: p[0], max_size=2),
)


def _spell_member(
    i: int,
    member: Member,
    *,
    weight_int: bool = False,
    sugar: bool = False,
    trailing_params: bool = False,
) -> str:
    """One `model_i` source, canonical by default, and a variant per flag."""
    path, prompt, params = member
    q = render(text(prompt))
    weight = "0" if weight_int else "0.0"
    if params and trailing_params:
        call = f"{path}($input)!{q}" + "".join(f";{k}={v}" for k, v in params)
    elif params:
        call = f"{path}?{'&'.join(f'{k}={v}' for k, v in params)}&q=($input)!{q}"
    elif sugar:
        call = f"{path}?q=($input)!{q}"
    else:
        call = f"{path}($input)!{q}"
    return f"model_{i}:{weight}:{call}"


def _spell(members: list[Member], final: int, separator: str, **flags: bool) -> str:
    joined = separator.join(_spell_member(i, m, **flags) for i, m in enumerate(members, 1))
    return f"({joined})!'$model_{final}'"


def _link(candidate: str) -> str:
    return render(expr(src(text(candidate), name="candidate", weight=0.0), _B1, intent=text("")))


def test_strategy_canonical_form_is_canonical() -> None:
    # A guard on the test helper, proven without Hypothesis.
    members: list[Member] = [
        ("/provider/a", "It's a test", [("temperature", "0.2"), ("top_p", "0.9")]),
        ("/provider/b", "Answer.", []),
    ]
    canonical = _spell(members, 2, ", ")
    assert canonical == (
        "(model_1:0.0:/provider/a?temperature=0.2&top_p=0.9&q=($input)!'It\\'s a test', "
        "model_2:0.0:/provider/b($input)!'Answer.')!'$model_2'"
    )
    assert render(build(canonical)) == canonical


@settings(max_examples=200, deadline=None, derandomize=True, database=None)
@given(
    members=st.lists(_member, min_size=1, max_size=3),
    data=st.data(),
    weight_int=st.booleans(),
    sugar=st.booleans(),
    trailing_params=st.booleans(),
    separator=st.sampled_from([",", ", ", ",   "]),
)
def test_fingerprint_equal_for_normalizable_spellings(
    members: list[Member],
    data: st.DataObject,
    weight_int: bool,
    sugar: bool,
    trailing_params: bool,
    separator: str,
) -> None:
    final = data.draw(st.integers(min_value=1, max_value=len(members)))
    canonical = _spell(members, final, ", ")
    assert render(build(canonical)) == canonical  # a strategy defect must be loud
    variant = _spell(
        members,
        final,
        separator,
        weight_int=weight_int,
        sugar=sugar,
        trailing_params=trailing_params,
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert system_fingerprint(_link(variant), exclude_bindings=SF) == expected
    assert system_fingerprint(_link(canonical), exclude_bindings=SF) == expected
