"""The one binding vocabulary for attributed operations; lock-step with the Engine (OME-1289)."""

import re

_BODY = r"(?:model|synthesis|judge|writer)_\d+"
# INVARIANT: byte-identical to apps/screamingface-engine/.../benchmarks/operation_outputs.py
# `_BINDING` and to the "pattern" of the tests' combine_contract/binding_names.json
# (tests/unit/test_binding_pattern_conformance.py binds all three).
OPERATION_BINDING_PATTERN = rf"^{_BODY}$"
OPERATION_BINDING = re.compile(OPERATION_BINDING_PATTERN)
OPERATION_REFERENCE = re.compile(rf"\$({_BODY})")
# A corrective loop nests its whole gated chain as one inner expression bound under
# loop_candidate (OME-796); everything else stays an operation binding.
TOPOLOGY_BINDING = re.compile(rf"{_BODY}|loop_candidate")

__all__: list[str] = []
