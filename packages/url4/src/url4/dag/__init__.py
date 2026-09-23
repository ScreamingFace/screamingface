"""The executable DAG — url4's execution model.

An expression compiles into a directed acyclic graph of typed nodes, each
owning its own piece of execution logic behind the :class:`DagNode` protocol
(``deps`` + ``resolve``). The :class:`Executor` schedules the graph as a
dataflow: one memoized task per node, independent nodes running in parallel.
Parsing is distributed — nested groups, iteration row bodies, and reducers are
compiled by their owning node at resolve time, not upfront.

Public surface: :func:`compile_expression` / :class:`Graph` (compiler),
:func:`run` / :class:`Executor` / :class:`ExecutionContext` (execution), the
built-in node classes, and :class:`LoweringRegistry` for extension.

The execution-time value semantics the nodes call (collection parsing, ``$``
substitution) live in :mod:`url4.dag.semantics`. See ``ARCHITECTURE.md`` for the
layer map and the import-direction rule.
"""

from __future__ import annotations

from url4.dag._run import run
from url4.dag.compiler import Graph, LoweringRegistry, compile_expression, default_registry
from url4.dag.executor import Executor, check_acyclic
from url4.dag.node import (
    DEFAULT_RUN_CONCURRENCY,
    BoundedIOLayer,
    DagNode,
    ExecutionContext,
    Payload,
    ProcessFn,
    SourceFailure,
    default_process,
)
from url4.dag.nodes import (
    DEFAULT_MAP_CONCURRENCY,
    BarrierNode,
    BindingNode,
    BroadcastCollectNode,
    CollectNode,
    ExpandNode,
    FanoutReduceNode,
    GatherNode,
    GuardNode,
    HoldingsNode,
    JoinNode,
    LazyExprNode,
    MapNode,
    MergeNode,
    ProcessNode,
    ReduceNode,
    RelUrlNode,
    RemoteFetchNode,
    StructNode,
    TextNode,
    WebFetchNode,
)

__all__ = [
    "DEFAULT_MAP_CONCURRENCY",
    "DEFAULT_RUN_CONCURRENCY",
    "BarrierNode",
    "BindingNode",
    "BoundedIOLayer",
    "BroadcastCollectNode",
    "CollectNode",
    "DagNode",
    "ExecutionContext",
    "Executor",
    "ExpandNode",
    "FanoutReduceNode",
    "GatherNode",
    "Graph",
    "GuardNode",
    "HoldingsNode",
    "JoinNode",
    "LazyExprNode",
    "LoweringRegistry",
    "MapNode",
    "MergeNode",
    "Payload",
    "ProcessFn",
    "ProcessNode",
    "ReduceNode",
    "RelUrlNode",
    "RemoteFetchNode",
    "SourceFailure",
    "StructNode",
    "TextNode",
    "WebFetchNode",
    "check_acyclic",
    "compile_expression",
    "default_process",
    "default_registry",
    "run",
]
