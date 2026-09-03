"""Marks the direct-OpenAI unit suites as a package.

WHY the file exists at all: the sibling suites share small hand-written helper modules
(``ambient_state``, ``dispatch_harness``) the same way ``tests/unit`` shares
``_global_cache_registry_sweep`` — through RELATIVE imports, which pytest only resolves
for a real package. Every other provider test directory here already has one.
"""
