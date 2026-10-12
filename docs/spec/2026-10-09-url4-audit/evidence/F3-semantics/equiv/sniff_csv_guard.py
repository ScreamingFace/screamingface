"""Q: is the `"," not in lines[0]` conjunct (collection.py:173) load-bearing?"""
from _sniff_common import VARS, ASSUME, cls
NAME = "CSV branch guard: with vs without the comma pre-check"
def OLD(v):
    return cls(v) == "CSV"
def NEW(v):  # same chain, `c` removed from the CSV guard
    if v["h"] or v["o"] or v["a"] or (v["m"] and v["j"]):
        return False
    return v["m"] and v["t"] and v["r"]
