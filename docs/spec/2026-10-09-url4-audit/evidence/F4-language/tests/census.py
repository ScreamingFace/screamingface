"""Failure census: sample many examples, bucket each law's failures, keep the shortest witness.

Hypothesis stops at the first counterexample per test; the census shows every distinct
failure class. Usage: python census.py [N]
"""

from __future__ import annotations

import sys
import traceback
import warnings

from gen import asts, grammar_text, mutated_text
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from url4 import build, render
from url4.core.errors import ParseError, RenderError
from url4.core.grammar import intent_atom, parse, parse_value
from url4.core.nodes import Expression, Iteration

warnings.simplefilter("ignore")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
buckets: dict[str, dict[str, tuple]] = {"L3_silent": {}, "L3_loud": {}, "L2prime": {}, "F_crash": {}, "L2_fix": {}}


def keep(law, key, witness, size):
    cur = buckets[law].get(key)
    if cur is None or size < cur[0]:
        buckets[law][key] = (size, witness)


def wrap(n):
    return n if isinstance(n, (Expression, Iteration)) else Expression(sources=(n,))


def _diffkey(a, b, path="root"):
    """First differing field path between two trees (a crude classifier)."""
    if type(a) is not type(b):
        return f"{path}: {type(b).__name__}->{type(a).__name__}"
    if hasattr(a, "__dataclass_fields__"):
        for f in a.__dataclass_fields__:
            x, y = getattr(a, f), getattr(b, f)
            if x != y:
                return _diffkey(x, y, f"{path}.{f}")
        return path
    if isinstance(a, tuple) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _diffkey(x, y, f"{path}[{i}]".replace("[0]", "[i]").replace("[1]", "[i]").replace("[2]", "[i]"))
    return path


@settings(max_examples=N, deadline=None, suppress_health_check=list(HealthCheck), database=None)
@given(asts)
def ast_laws(n):
    try:
        s = render(n, check=False)
    except (RenderError, TypeError):
        return
    try:
        t = build(s)
    except ParseError as e:
        keep("L3_loud", str(e)[:60], (n, s), len(s))
        return
    except Exception as e:  # noqa: BLE001
        keep("F_crash", f"{type(e).__name__} via render", s, len(s))
        return
    if t != wrap(n):
        keep("L3_silent", _diffkey(t, wrap(n)), (n, s, t), len(s))
    else:
        try:
            r = render(t)
            if r != s:
                keep("L2_fix", "render(build(s)) != s", (s, r), len(s))
        except RenderError as e:
            keep("L2_fix", "render(build(s)) raises: " + str(e)[:50], s, len(s))


@settings(max_examples=N, deadline=None, suppress_health_check=list(HealthCheck), database=None)
@given(st.one_of(grammar_text, mutated_text(), st.text(max_size=12)))
def text_laws(s):
    for f in (build, parse, parse_value, intent_atom):
        try:
            f(s)
        except ParseError:
            pass
        except Exception as e:  # noqa: BLE001
            tb = traceback.extract_tb(e.__traceback__)[-1]
            keep("F_crash", f"{f.__name__}: {type(e).__name__} at {tb.name}:{tb.lineno}", s, len(s))
    try:
        t = build(s)
    except Exception:  # noqa: BLE001
        return
    try:
        render(t)
    except RenderError as e:
        msg = str(e)
        key = msg.split(" — ")[0][:70] if "does not reparse" not in msg else "reparse: " + msg.split(": ", 1)[-1][-60:]
        keep("L2prime", key, s, len(s))


if __name__ == "__main__":
    ast_laws()
    text_laws()
    for law, b in buckets.items():
        print(f"\n=== {law}: {len(b)} classes")
        for key, (size, w) in sorted(b.items(), key=lambda kv: kv[1][0]):
            print(f"- [{key}]\n    {w!r}"[:600])
