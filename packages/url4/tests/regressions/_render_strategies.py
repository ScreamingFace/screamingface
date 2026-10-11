"""Hypothesis strategies for AST trees, including shapes the grammar cannot carry.

Ported from the 2026-10-09 audit (evidence/F4-language/tests/gen.py, ``asts``):
the atoms are chosen to hit every structural character class of the grammar, so
render's acceptance boundary is exercised from both sides.
"""

from __future__ import annotations

from hypothesis import strategies as st

from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
    IterationDirectives,
    RelExpr,
    RelUrl,
    RemoteExpr,
    SelfRef,
    Source,
    StructObject,
    Text,
    Url,
    VarRef,
)

NAMES = st.sampled_from(["a", "b", "x1", "_n", "topic", "item", "src", "weight", "é"])
TEXT_ALPHA = [*"ab ,;!()*'\\$:=/@{}.?&-_0", "\n", "\t", "é"]
texts = st.text(alphabet=st.sampled_from(TEXT_ALPHA), max_size=7)
URI_ALPHA = list("ab/._-$?=&()!,;'*:")
uris = st.builds(
    lambda p: "https://h.io/" + p, st.text(alphabet=st.sampled_from(URI_ALPHA), max_size=6)
)
relurls = st.builds(lambda p: "/" + p, st.text(alphabet=st.sampled_from(URI_ALPHA), max_size=6))
paths = st.sampled_from(["/claude", "/p", "/a/b", "/", "//", "/a-b.c~", "/x$y", "/a b"])
weights = st.one_of(
    st.none(),
    st.sampled_from([0.0, 0.5, 1.0, 2.0, 1e-7, 1e20, -1.0, float("inf"), 0.1 + 0.2]),
    st.just({"science": 0.85, "_default": 0.4}),
    st.just({"s": {"d": 1}}),
)
annotation_keys = st.sampled_from(
    ["mode", "t", "retry", "required", "optional", "accept", "expand", "x.y", "t2"]
    + ["iteration.concurrency", "quorum"]
)
annotation_vals = st.one_of(
    st.none(), st.sampled_from(["agent", "30", "1", "a b", "x!y", "app/json", "2"])
)
annotation_pairs = st.lists(st.tuples(annotation_keys, annotation_vals), max_size=2).map(tuple)
param_keys = st.sampled_from(
    ["quorum", "k", "t", "mode", "q", "iteration.slice", "broadcast", "x2"]
)
param_vals = st.one_of(
    st.none(), st.sampled_from(["1", "all", "a,b", "x!y", "'q x'", "a b", "1:3"])
)
params = st.lists(st.tuples(param_keys, param_vals), max_size=2).map(tuple)


def _leaf():
    return st.one_of(
        st.builds(Text, texts),
        st.builds(Url, uris),
        st.builds(RelUrl, relurls),
        st.builds(
            VarRef,
            st.sampled_from(["a", "1", "item", "_x", "\u0661"]),
            st.lists(
                st.one_of(st.sampled_from(["f", "g1", "a b"]), st.integers(-1, 3)), max_size=2
            ).map(tuple),
        ),
        st.just(SelfRef()),
        st.builds(
            IdentityRef,
            st.sampled_from(["emily", "9", "9x"]),
            st.sampled_from([None, "notes", "a/b", "x#y", ""]),
        ),
        st.builds(StructObject, st.sampled_from(["{k: 'v'}", "{a: 1, b: {c: 2}}", "{x", "{a}}"])),
    )


def _intent(children):
    return st.one_of(
        st.builds(Text, texts),
        st.builds(Url, uris),
        st.builds(RelUrl, relurls),
        children.filter(
            lambda n: isinstance(n, (Expression, Iteration, SelfRef, IdentityRef, StructObject))
        ),
    )


def _directives():
    return st.builds(
        IterationDirectives,
        concurrency=st.one_of(st.none(), st.integers(0, 3)),
        on_error=st.sampled_from(["collect", "skip", "fail"]),
        slice=st.one_of(st.none(), st.just((0, 2)), st.just((2, 1))),
        fmt_result=st.one_of(st.none(), st.sampled_from(["json", "a b"])),
    )


def _composite(children):
    tmpl = st.sampled_from(["go", "'go'", " go", "a!b", "x;k=v", "x*(y)", "/r(x)", "$a"])
    budgets = st.lists(
        st.tuples(st.sampled_from(["tokens", "usd", "t1"]), st.sampled_from(["100", "1.5", "a b"])),
        max_size=1,
    ).map(tuple)
    return st.one_of(
        st.builds(
            Expression,
            st.lists(children, max_size=3).map(tuple),
            st.one_of(st.none(), _intent(children)),
            st.booleans(),
            params,
        ),
        st.builds(
            Source,
            children,
            st.one_of(st.none(), NAMES),
            weights,
            budgets,
            annotation_pairs,
            st.booleans(),
        ),
        st.builds(Binding, NAMES, children, st.sampled_from(["=", ":"])),
        st.builds(
            RelExpr,
            paths,
            st.one_of(st.none(), st.sampled_from(["https://x", "a, b", " x", "(", "q=1"])),
            st.one_of(st.none(), _intent(children)),
            params,
        ),
        st.builds(
            RemoteExpr,
            st.sampled_from(["node.ai", "node.ai:80", "h:x", ""]),
            paths,
            st.one_of(st.none(), st.sampled_from(["https://x", "a"])),
            st.one_of(st.none(), _intent(children)),
            params,
        ),
        st.builds(
            Iteration,
            children,
            st.sampled_from(["x=$item", " $item ", "(", "a, b", "$a"]),
            st.one_of(st.none(), tmpl),
            st.one_of(st.none(), tmpl),
            _directives(),
        ),
    )


asts = st.recursive(_leaf(), _composite, max_leaves=6)
