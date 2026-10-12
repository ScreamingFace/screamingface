"""Shared boolean abstraction of url4 collection._sniff (collection.py:53-78).

Each VAR is a predicate of the stripped, non-empty body:
  h  body[:512] starts with <!doctype html / <html            (line 63)
  o  body starts '{' and json.loads(body) is a dict           (_reject_json_object, 81-92)
  a  body starts '[' and json.loads(body) is a list           (_try_json_array, 144-151)
  m  >= 2 non-blank lines                                     (_lines; 157, 173, 74)
  j  every non-blank line is valid JSON                       (_try_jsonl, 160-164)
  c  ',' in first line                                        (173)
  t  every comma-field of line 1 is non-empty, no space, no ?!. ending  (_looks_like_header, 189-203)
  r  DictReader(body): >=2 fieldnames, >=1 row, all rows rectangular   (175-186)
"""
VARS = ["h", "o", "a", "m", "j", "c", "t", "r"]

def ASSUME(v):
    # Facts of the input domain, each argued from the code:
    if v["h"] and (v["o"] or v["a"]):        # '<' vs '{' / '[' first char
        return False
    if v["o"] and v["a"]:                     # one JSON value is a dict or a list, not both
        return False
    if v["r"] and not (v["c"] and v["m"]):    # >=2 fields needs a comma; >=1 data row needs >=2 lines
        return False                          # (approximation: ignores a quoted multi-line header)
    if (v["o"] or v["a"]) and v["m"] and v["j"]:
        return False                          # a whole-body JSON value spanning >=2 lines has a line that is not JSON
    return True

def cls(v):
    """The class the code picks, in code order."""
    if v["h"]: return "HTML_REJECT"
    if v["o"]: return "OBJ_REJECT"
    if v["a"]: return "ARRAY"
    if v["m"] and v["j"]: return "JSONL"
    if v["m"] and v["c"] and v["t"] and v["r"]: return "CSV"
    if v["m"]: return "LINES"
    return "SCALAR_REJECT"
