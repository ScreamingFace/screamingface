"""grammar._PATH_RE (expression path) vs grammar._DATA_PATH_RE (relative-uri data path).
Run: fm equiv thisfile.py"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from z3 import String, InRe, Length
from re_common import EXPR_PATH, DATA_PATH
NAME = "_PATH_RE (relative-expr path) vs _DATA_PATH_RE (relative-uri path)"
def state(k):
    return {"p": String(f"p{k}")}
def ASSUME(s):
    return Length(s["p"]) <= 12
def OLD(s):
    return InRe(s["p"], EXPR_PATH)
def NEW(s):
    return InRe(s["p"], DATA_PATH)
