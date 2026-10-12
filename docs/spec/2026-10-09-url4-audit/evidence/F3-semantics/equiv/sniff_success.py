"""Q: which features decide whether sniffing SUCCEEDS (vs raises)?"""
from _sniff_common import VARS, ASSUME, cls
NAME = "_sniff succeeds (returns items, does not raise)"
def P(v):
    return cls(v) not in ("HTML_REJECT", "OBJ_REJECT", "SCALAR_REJECT")
