"""Hypothesis strategies for the url4 language layer (F4 audit lane).

Two generators:
- ``asts``          — AST trees built from the real node dataclasses (and the
                      public builders), including shapes the grammar cannot carry,
                      so render's acceptance boundary is exercised.
- ``grammar_text``  — grammar-shaped surface strings (mostly valid url4), plus
                      ``mutated_text`` (random structural edits) for crash fuzzing.
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

# ---------------------------------------------------------------- shared atoms
NAMES = st.sampled_from(["a", "b", "x1", "_n", "topic", "item", "src", "weight", "é"])
SAFE_NAMES = st.sampled_from(["a", "b", "x1", "_n", "topic"])
# Characters chosen to hit every structural class of the grammar.
TEXT_ALPHA = list("ab ,;!()*'\\$:=/@{}.?&-_0") + ["\n", "\t", "é"]
texts = st.text(alphabet=st.sampled_from(TEXT_ALPHA), max_size=7)
URI_ALPHA = list("ab/._-$?=&()!,;'*:")
uris = st.builds(lambda p: "https://h.io/" + p, st.text(alphabet=st.sampled_from(URI_ALPHA), max_size=6))
relurls = st.builds(lambda p: "/" + p, st.text(alphabet=st.sampled_from(URI_ALPHA), max_size=6))
paths = st.sampled_from(["/claude", "/p", "/a/b", "/", "//", "/a-b.c~", "/x$y", "/a b"])
weights = st.one_of(
    st.none(),
    st.sampled_from([0.0, 0.5, 1.0, 2.0, 1e-7, 1e20, -1.0, float("inf"), 0.1 + 0.2]),
    st.just({"science": 0.85, "_default": 0.4}),
    st.just({"s": {"d": 1}}),
)
annotation_keys = st.sampled_from(
    ["mode", "t", "retry", "required", "optional", "accept", "expand", "x.y", "t2", "iteration.concurrency", "quorum"]
)
annotation_vals = st.one_of(st.none(), st.sampled_from(["agent", "30", "1", "a b", "x!y", "app/json", "2"]))
annotations = st.lists(st.tuples(annotation_keys, annotation_vals), max_size=2).map(tuple)
param_keys = st.sampled_from(["quorum", "k", "t", "mode", "q", "iteration.slice", "broadcast", "x2"])
param_vals = st.one_of(st.none(), st.sampled_from(["1", "all", "a,b", "x!y", "'q x'", "a b", "1:3"]))
params = st.lists(st.tuples(param_keys, param_vals), max_size=2).map(tuple)


def _leaf():
    return st.one_of(
        st.builds(Text, texts),
        st.builds(Url, uris),
        st.builds(RelUrl, relurls),
        st.builds(
            VarRef,
            st.sampled_from(["a", "1", "item", "_x", "\u0661"]),
            st.lists(st.one_of(st.sampled_from(["f", "g1", "a b"]), st.integers(-1, 3)), max_size=2).map(tuple),
        ),
        st.just(SelfRef()),
        st.builds(IdentityRef, st.sampled_from(["emily", "9", "9x"]), st.sampled_from([None, "notes", "a/b", "x#y", ""])),
        st.builds(StructObject, st.sampled_from(["{k: 'v'}", "{a: 1, b: {c: 2}}", "{x", "{a}}"])),
    )


def _intent(children):
    return st.one_of(
        st.builds(Text, texts),
        st.builds(Url, uris),
        st.builds(RelUrl, relurls),
        children.filter(lambda n: isinstance(n, (Expression, Iteration, SelfRef, IdentityRef, StructObject))),
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
            st.lists(st.tuples(st.sampled_from(["tokens", "usd", "t1"]), st.sampled_from(["100", "1.5", "a b"])), max_size=1).map(tuple),
            annotations,
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


# ---------------------------------------------------------------- surface text
def _q(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


QTEXT = st.text(alphabet=st.sampled_from(list("ab ,;!()*$:=/@") + ["'", "\\"]), max_size=6).map(_q)
WORD = st.sampled_from(["hello", "go", "sum", "x", "data", "run fast", "a\tb"])
URL_T = st.sampled_from(
    ["https://a.io", "https://b.io/x", "https://w.org/Fish_(animal)", "s3://bk/d", "https://a.io/$topic"]
)
REL_T = st.sampled_from(["/data", "/data/$topic", "/api/x?a=1"])
VAR_T = st.sampled_from(["$a", "$1", "$a.f[0]", "$item"])
REF_T = st.sampled_from(["@", "@emily", "@emily/notes"])
STRUCT_T = st.sampled_from(["{k: 'v'}", "{a: 1, b: $a}"])
leaf_text = st.one_of(QTEXT, WORD, URL_T, REL_T, VAR_T, REF_T, STRUCT_T)


def _intent_text(inner):
    return st.one_of(QTEXT, WORD, URL_T, st.just("/reduce"), inner, st.just("@"))


def _expr_text(inner):
    srcs = st.lists(_source_text(inner), min_size=0, max_size=3).map(", ".join)
    tail = st.sampled_from(["", ";quorum=1", ";k=v", ";broadcast", ";note='a b'"])
    return st.builds(
        lambda s, op, i, t: f"({s}){op}{i}{t}", srcs, st.sampled_from(["!", "!*"]), _intent_text(inner), tail
    )


def _call_text(inner):
    ctx = st.one_of(st.just(""), leaf_text, st.just("a=https://a.io, $a"))
    return st.one_of(
        st.builds(lambda p, c, i: f"{p}({c})!{i}", st.sampled_from(["/claude", "/p"]), ctx, _intent_text(inner)),
        st.builds(lambda c, i: f"/p?t=90&q=({c})!{i}", ctx, _intent_text(inner)),
        st.builds(lambda c, i: f"url4://node.ai/v1({c})!{i}", ctx, _intent_text(inner)),
    )


def _iter_text(inner):
    coll = st.one_of(URL_T, st.just("(a, b)"), st.just("$a"), REL_T)
    body = st.sampled_from(["$item", "x=$item, $a", "'$item'", "/p($item)!go"])
    dirs = st.sampled_from(["", ";iteration.concurrency=2", ";iteration.on_error=skip"])
    return st.builds(lambda c, b, i, d: f"{c}*({b})!{i}{d}", coll, body, st.sampled_from(["go", "'p'", "/r"]), dirs)


def _value_text(inner):
    return st.one_of(leaf_text, inner, _call_text(inner))


def _source_text(inner):
    v = _value_text(inner)
    return st.one_of(
        v,
        st.builds(lambda n, x: f"{n}={x}", SAFE_NAMES, v),
        st.builds(lambda n, x: f"{n}:{x}", SAFE_NAMES, v),
        st.builds(lambda n, w, x: f"{n}:{w}:{x}", SAFE_NAMES, st.sampled_from(["0", "0.5", "(science:0.8)"]), v),
        st.builds(lambda n, x: f"{n}:0.5:tokens=100:{x}", SAFE_NAMES, v),
        st.builds(lambda x: f"*{x}", v),
        st.builds(lambda x, a: f"{x}{a}", v, st.sampled_from([";mode=agent", ";t=30", ";optional", ";mode=agent;k=1"])),
    )


_inner = st.deferred(lambda: st.one_of(_expr_text(_inner), _iter_text(_inner)).filter(lambda s: len(s) < 160))

grammar_text = st.one_of(
    _expr_text(_inner),
    _iter_text(_inner),
    st.builds(lambda it, r: f"({it})!{r}", _iter_text(_inner), st.sampled_from(["'merge'", "go"])),
    _call_text(_inner),
    _source_text(_inner),
)

STRUCT_CHARS = list("()[]{}!*;,:=@$'\\/ ?&.") + ["\n"]


@st.composite
def mutated_text(draw):
    s = draw(grammar_text)
    for _ in range(draw(st.integers(1, 3))):
        op = draw(st.sampled_from(["ins", "del", "rep"]))
        i = draw(st.integers(0, len(s)))
        c = draw(st.sampled_from(STRUCT_CHARS))
        if op == "ins":
            s = s[:i] + c + s[i:]
        elif op == "del" and s:
            s = s[: max(i - 1, 0)] + s[i:]
        elif s:
            s = s[: max(i - 1, 0)] + c + s[i:]
    return s
