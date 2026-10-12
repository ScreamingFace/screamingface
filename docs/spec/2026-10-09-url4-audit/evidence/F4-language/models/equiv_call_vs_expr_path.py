"""parser._CALL_PATH_RE (parser.py:55) vs grammar._PATH_RE (grammar.py:100; render._check_path).
Run: fm equiv thisfile.py"""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from z3 import String, InRe, Length
from re_common import CALL_PATH, EXPR_PATH
NAME = "_CALL_PATH_RE (call-tail classifier) vs _PATH_RE (expression path, parse+render)"
def state(k):
    return {"p": String(f"p{k}")}
def ASSUME(s):
    return Length(s["p"]) <= 12
def OLD(s):
    return InRe(s["p"], CALL_PATH)
def NEW(s):
    return InRe(s["p"], EXPR_PATH)
