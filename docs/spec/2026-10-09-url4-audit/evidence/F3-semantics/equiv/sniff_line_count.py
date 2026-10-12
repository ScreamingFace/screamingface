"""Q: where does 'N text lines -> N items' (the reader's expectation for plain
multi-line text) differ from what the code does?"""
from _sniff_common import VARS, ASSUME, cls
NAME = "one item per line: code vs reader expectation"
def OLD(v):   # the code: classes that yield exactly one item per non-blank line
    return cls(v) in ("JSONL", "LINES")
def NEW(v):   # expectation: any multi-line body that is not HTML / one JSON value
    return v["m"] and not (v["h"] or v["o"] or v["a"])
