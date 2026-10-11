"""Probe pure functions for surprising semantics."""
import json
from url4.dag.semantics.collection import parse_collection
from url4.dag.semantics.ensemble import substitute_item, substitute_env_vars, substitute_response_vars, build_reducer_input, FanoutResponse
from url4.dag.nodes._shared import _rows_to_json, _substitute, _gather, _check_quorum, _ITEM_KEY
from url4.core.context import Context
from url4.core.errors import CollectionError

def pc(body, mt=None):
    try:
        return parse_collection(body, mt)
    except CollectionError as e:
        return f"ERR({e.code if hasattr(e,'code') else ''}: {str(e)[:60]})"

cases = [
  ("2-line prose pairs (valid CSV)", "red,green\nblue,yellow"),
  ("city list", "Paris,France\nTokyo,Japan\nLima,Peru"),
  ("dup header", "a,a\n1,2"),
  ("numeric text lines", "2.50\n3.10"),
  ("exp text", "1e3\n2"),
  ("NaN lines", "NaN\nInfinity"),
  ("quoted text lines", '"a"\n"b"'),
  ("json arr 1 elem", '["x"]'),
  ("json arr nested str vs obj 1", '[{"a":1}]'),
  ("json arr nested str vs obj 2", '["{\\"a\\": 1}"]'),
  ("num vs str 1", '[1]'),
  ("num vs str 2", '["1"]'),
  ("ndjson scalars", '1\n"x"\nnull'),
  ("single line scalar", 'hello'),
  ("single ndjson obj", '{"a":1}'),
  ("two ndjson objs", '{"a":1}\n{"a":2}'),
  ("html w/o doctype", '<head><title>x</title></head>\n<body>404</body>'),
  ("CR only", 'a\rb\rc'),
  ("header w/ quoted comma", '"a,b",c\n1,2'),
  ("pretty json obj", '{\n "a": 1\n}'),
  ("pretty json obj broken", '{\n "a": 1,\n}'),
  ("json arr with junk", '[1,2] trailing\nmore'),
]
for name, b in cases:
    print(f"{name:32} {b!r:40} -> {pc(b)!r}")
print()
for mt in ["application/jsonl", "application/json; charset=utf-8", "text/html", "application/ld+json", "text/csv"]:
    print(f"declared {mt:32} '[1]\\n' or csv -> {pc('a,b\n1,2' if 'csv' in mt else '[1]', mt)!r}")
print("declared csv ragged:", pc("a,b\n1,2,3\n4", "text/csv"))
print("declared csv dup:", pc("a,a\n1,2", "text/csv"))

print("\n--- substitute_item double substitution")
print(repr(substitute_item("A=$item.a B=$item", json.dumps({"a": "$item"}))))
print(repr(substitute_item("A=$item.a B=$item.b", json.dumps({"a": "$item.b", "b": "X"}))))
print("--- _substitute: row value re-scanned by env pass")
scope = Context(bindings={_ITEM_KEY: json.dumps({"q": "$secret"}), "secret": "TOPSECRET"}, parent=None)
class C: strict_fields=False
print(repr(_substitute("Q=$item.q", scope, C())))
scope2 = Context(bindings={_ITEM_KEY: "price $$5 and $1"}, parent=None)
print(repr(_substitute("row=$item", scope2, C())))
print("--- response vars: value containing $name")
print(repr(substitute_response_vars("A=$a B=$b", [FanoutResponse("says $b", "a"), FanoutResponse("BBB", "b")])))
print("--- blob spans shifted by inserted value: path value with '}' ")
t = '{"x": "$item.a", "y": "$item"}'
out = substitute_item(t, json.dumps({"a": "}"}))
print(repr(out));
try: json.loads(out); print("valid")
except Exception as e: print("INVALID JSON:", e)
t = '$item.a {"y": "$item"}'
out = substitute_item(t, json.dumps({"a": "{"}))
print(repr(out))
print("--- _rows_to_json")
print(_rows_to_json(["[NaN]", "1", '{"a":1}', "", "[x"]))
