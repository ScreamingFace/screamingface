"""z3 regex encodings of the url4 path character classes (shared by the equiv models)."""
from z3 import Concat, Plus, Range, Re, Star, Union


def cls(spec: str):
    """A z3 char class from a regex-like spec: ranges 'A-Z' and literal chars."""
    parts, i = [], 0
    while i < len(spec):
        if i + 2 < len(spec) and spec[i + 1] == "-":
            parts.append(Range(spec[i], spec[i + 2])); i += 3
        else:
            parts.append(Re(spec[i])); i += 1
    return Union(*parts) if len(parts) > 1 else parts[0]


NARROW = cls("A-Za-z0-9") if False else Union(Range("A", "Z"), Range("a", "z"), Range("0", "9"), Re("-"), Re("_"), Re("."), Re("~"))
WIDE = Union(NARROW, Re(":"), Re("@"), Re("!"), Re("$"), Re("&"), Re("+"), Re("="))
# parser.py:55   _CALL_PATH_RE = (?:/[A-Za-z0-9\-_.~]*)+
CALL_PATH = Plus(Concat(Re("/"), Star(NARROW)))
# grammar.py:100 _PATH_RE      = (?:/[A-Za-z0-9\-_.~]*)+   (render._check_path imports this object)
EXPR_PATH = Plus(Concat(Re("/"), Star(NARROW)))
# grammar.py:106 _DATA_PATH_RE = (?:/[A-Za-z0-9\-_.~:@!$&+=]+)+
DATA_PATH = Plus(Concat(Re("/"), Plus(WIDE)))
