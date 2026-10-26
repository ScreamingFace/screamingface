"""The one binding vocabulary for attributed operations; lock-step with the Engine (OME-1289)."""

import re

_BODY = r"(?:model|synthesis|judge|writer|gate|selector)_\d+"
# E4c: a reference ends at a word boundary, so a Gate helper name such as `$gate_3_after` or
# `$gate_3_decide` never decodes as the operation `gate_3` (branch-core BC-15).
_END = r"(?![A-Za-z0-9_])"
# INVARIANT: byte-identical to apps/screamingface-engine/.../benchmarks/operation_outputs.py
# `_BINDING` and to the "pattern" of the tests' combine_contract/binding_names.json
# (tests/unit/test_binding_pattern_conformance.py binds all three).
OPERATION_BINDING_PATTERN = rf"^{_BODY}$"
OPERATION_BINDING = re.compile(OPERATION_BINDING_PATTERN)
OPERATION_REFERENCE = re.compile(rf"\$({_BODY}){_END}")
# A corrective loop nests its whole gated chain as one inner expression bound under
# loop_candidate (OME-796), and a Gate its DECIDE/OPEN/JOIN chain under gate_N_block (E4c);
# everything else stays an operation binding.
TOPOLOGY_BINDING = re.compile(rf"{_BODY}|loop_candidate|gate_\d+_block")
# A reducer node is a combine call, and every combine call takes the next synthesis_N.
SYNTHESIS_BINDING = re.compile(r"synthesis_\d+")
# E4c: a Gate binds its DECIDE/OPEN/JOIN chain as gate_N_block; its JOIN call is gate_N.
GATE_BLOCK = re.compile(r"gate_(\d+)_block")


def gate_join(name: str) -> str:
    """A Gate block binding names its JOIN call ``gate_N``; any other name is itself."""

    block = GATE_BLOCK.fullmatch(name)
    return f"gate_{block.group(1)}" if block else name


# The model/combine call param that names the call for attribution (never forwarded by the Engine).
# Every attributed combine, judge and writer call carries it FIRST; a user param cannot use it.
OPERATION_BINDING_PARAM = "binding"

__all__: list[str] = []
