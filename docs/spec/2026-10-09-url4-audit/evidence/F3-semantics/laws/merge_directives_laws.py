"""fm laws over the REAL url4.core.parser._merge_directives (parser.py:353).

SHOULD hold: idempotent (re-applying the same directives is a no-op), associative
(nesting depth must not change the outcome), identity = IterationDirectives()
(an absent directive set changes nothing). NOT expected: commutative (the inner
set is documented to win).
"""
import sys
sys.path.insert(0, "")
from url4.core.parser import _merge_directives
from url4.core.nodes import IterationDirectives as D

NAME = "_merge_directives (inner wins field-wise over outer)"
SAMPLES = [
    D(),
    D(on_error="collect"),          # explicit default — indistinguishable from unset
    D(on_error="skip"),
    D(on_error="fail"),
    D(concurrency=0),               # falsy, but not None
    D(concurrency=2),
    D(concurrency=5, on_error="fail"),
    D(slice=(0, 0)),                # empty range — truthy tuple
    D(slice=(1, 3), fmt_result="json"),
    D(fmt_result=""),               # falsy string
]
IDENTITY = D()

def merge(x, y):
    return _merge_directives(x, y)
