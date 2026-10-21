"""``sf.Fanout``: the map step of a block (E4b surface unit 2, surface §3, O6).

FEATURE: ``sf.Fanout(members, *, signals=None, quorum="all", name=None, prompt=None)`` sends the
input to every member and declares the signals. ``prompt=`` sets the prompt of each member that is
a route or a ``sf.Model`` with no prompt (FA-1). ``signals=`` needs a step that reads them (FA-2).
STORY: as a researcher, I give one prompt to the whole panel in one place.
"""

from __future__ import annotations

import pytest
from _nodes import FusionNode, VoteNode, fusion_node

import screamingface as sf
from screamingface._surface.lowering import lower

_PAIR = ["provider/a", "provider/b"]
_PROMPT = "Answer with one number."


def test_members_are_normalized_and_named_as_a_fusion() -> None:
    fanout = sf.Fanout(["provider/a", sf.Model("provider/b", optional=True)])

    assert fanout.members == (sf.Model("provider/a"), sf.Model("provider/b", optional=True))
    assert fanout.name == "a+b"
    assert fanout.quorum == "all"
    assert fanout.signals is None
    assert fanout.prompt is None


def test_name_quorum_and_signals_go_to_the_fusion_node() -> None:
    signals = {"conf": sf.Verbalized("C: ([0-9]+)")}
    chain = sf.Fanout(_PAIR, name="panel", quorum=1, signals=signals) >> sf.Vote(weights="conf")

    assert lower(chain) == fusion_node(
        _PAIR,
        name="panel",
        quorum=1,
        signals=signals,
        reducer=VoteNode(weights=sf.signal("conf")),
    )


@pytest.mark.parametrize(
    ("members", "error", "message"),
    [
        ("provider/a", TypeError, "Fanout members must be an ordered sequence"),
        ([], ValueError, "a Fanout requires at least one member"),
    ],
    ids=["string", "empty"],
)
def test_members_must_be_a_non_empty_sequence(
    members: object, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        sf.Fanout(members)  # type: ignore[arg-type]


def test_quorum_is_checked_against_the_member_count() -> None:
    with pytest.raises(ValueError, match="quorum must be between zero and the member count"):
        sf.Fanout(_PAIR, quorum=3)


def test_signals_are_checked_when_the_fanout_is_built() -> None:
    with pytest.raises(ValueError, match="is an E4a signal key"):
        sf.Fanout(_PAIR, signals={"cost_usd": sf.Verbalized("C: ([0-9]+)")})


def test_prompt_sets_each_route_member_and_each_model_with_no_prompt() -> None:
    chain = sf.Fanout(
        ["provider/a", sf.Model("provider/b", name="bee", params={"temperature": 0.2})],
        prompt=_PROMPT,
    ) >> sf.Synthesize("provider/w")

    assert lower(chain) == fusion_node(
        [
            sf.Model("provider/a", prompt=_PROMPT),
            sf.Model("provider/b", name="bee", prompt=_PROMPT, params={"temperature": 0.2}),
        ],
        "provider/w",
    )


def test_prompt_keeps_an_optional_member_optional() -> None:
    chain = (
        sf.Fanout(["provider/a", sf.Model("provider/b", optional=True)], prompt=_PROMPT)
        >> sf.Vote()
    )

    node = lower(chain)
    assert isinstance(node, FusionNode)
    assert node.members[1] == sf.Model("provider/b", prompt=_PROMPT, optional=True)


def test_fa1_a_member_with_its_own_prompt_is_refused() -> None:
    message = r"^Fanout prompt= sets the member prompts: member 2 already has one$"
    with pytest.raises(ValueError, match=message):
        sf.Fanout(["provider/a", sf.Model("provider/b", prompt="Mine.")], prompt=_PROMPT)


@pytest.mark.parametrize(
    "member",
    [
        sf.Fanout(_PAIR) >> sf.Vote(),
        sf.Pipeline(["provider/x", "provider/y"]),
        fusion_node(_PAIR, "provider/s"),
    ],
    ids=["chain", "pipeline", "fusion"],
)
def test_fa1_a_member_that_is_not_a_model_is_refused(member: sf.Recipe) -> None:
    message = r"^Fanout prompt= sets the member prompts: member 1 is not a model$"
    with pytest.raises(ValueError, match=message):
        sf.Fanout([member, "provider/c"], prompt=_PROMPT)


def test_fa1_a_blank_prompt_is_refused() -> None:
    with pytest.raises(ValueError, match="fanout prompt must not be empty"):
        sf.Fanout(_PAIR, prompt="  ")


def test_fa2_signals_with_a_bare_synthesize_are_refused() -> None:
    fanout = sf.Fanout(_PAIR, signals={"conf": sf.Verbalized("C: ([0-9]+)")})

    with pytest.raises(
        ValueError, match=r"^sf\.Fanout signals= needs a reducer: sf\.Synthesize reads no signal$"
    ):
        _ = fanout >> sf.Synthesize("provider/w")


def test_a_closed_chain_member_lowers_to_its_node() -> None:
    inner = sf.Fanout(_PAIR) >> sf.Synthesize("provider/s")
    chain = sf.Fanout([inner, "provider/c"], name="nested") >> sf.Synthesize("provider/w")

    assert lower(chain) == fusion_node(
        [fusion_node(_PAIR, "provider/s"), "provider/c"],
        name="nested",
        reducer="provider/w",
    )


def test_an_optional_closed_chain_member_lowers_to_an_optional_node() -> None:
    inner = sf.Pipeline([sf.Fanout(_PAIR), sf.Vote()], optional=True)
    chain = sf.Fanout([inner, "provider/c"]) >> sf.Synthesize("provider/w")

    assert lower(chain) == fusion_node(
        [fusion_node(_PAIR, VoteNode(), optional=True), "provider/c"],
        "provider/w",
    )
