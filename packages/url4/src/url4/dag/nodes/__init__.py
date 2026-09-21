"""The built-in executable node vocabulary — one Strategy per piece of execution logic.

Each class re-exported here is one Strategy: the piece of url4 execution logic it
owns, behind the uniform :class:`~url4.dag.node.DagNode` interface. Nodes hold
their *template* data (raw text fragments, paths, directives) and perform their
own substitution / dispatch / dynamic compilation at ``resolve`` time — this is
where "the whole expression is not parsed upfront" lives: :class:`LazyExprNode`
compiles its fragment on demand, :class:`MapNode` re-compiles its body per
collection row, and :class:`ReduceNode` parses its reducer only when the rows
exist.

The former single module is split by reason to change (report.md H1); the
public surface is unchanged — every name that lived here still imports from
here:

- :mod:`.fetch` — :class:`TextNode`, :class:`WebFetchNode`, :class:`RelUrlNode`,
  :class:`RemoteFetchNode`, :class:`HoldingsNode`, :class:`StructNode`, and the
  struct decoding they own;
- :mod:`.group` — :class:`BindingNode`, :class:`LazyExprNode`,
  :class:`BarrierNode`, :class:`GatherNode`, :class:`InlineCollectionNode`,
  :class:`ProcessNode`, :class:`MergeNode`, :class:`BroadcastCollectNode`,
  :class:`JoinNode`, :class:`CollectNode`, :class:`FanoutReduceNode`;
- :mod:`.guard` — :class:`GuardNode` (``;optional``/``;t=``/``;retry=``);
- :mod:`.iteration` — :class:`ExpandNode`, :class:`MapNode`,
  :class:`ReduceNode`;
- :mod:`._shared` — the helpers every family consumes (substitution, the
  reference-edge scope frame, the gather machinery, fetch plumbing, row
  serialization). Private to the package: a node module may import it, never
  the reverse.

Terminal-state additions (spec Part A / §10): :class:`GuardNode` wraps a
source's subtree with the per-source execution disposition and converts a
tolerated failure into a :class:`~url4.dag.node.SourceFailure` *value*;
:class:`ExpandNode` splices a collection-valued source into N sibling values
(§5.3.12); the group nodes (:class:`GatherNode` / :class:`ProcessNode`) skip
failures, flatten expansions, and enforce ``quorum=N``.

Classes are ``@dataclass(eq=False)``: node identity is object identity, which
is what lets the executor memoize shared nodes (diamond dependencies) by
construction.
"""

from __future__ import annotations

from url4.dag.nodes._shared import DEFAULT_MAP_CONCURRENCY, SlotSpec
from url4.dag.nodes.fetch import (
    HoldingsNode,
    RelUrlNode,
    RemoteFetchNode,
    StructNode,
    TextNode,
    WebFetchNode,
)
from url4.dag.nodes.group import (
    BarrierNode,
    BindingNode,
    BroadcastCollectNode,
    CollectNode,
    FanoutReduceNode,
    GatherNode,
    InlineCollectionNode,
    JoinNode,
    LazyExprNode,
    MergeNode,
    ProcessNode,
)
from url4.dag.nodes.guard import GuardNode
from url4.dag.nodes.iteration import ExpandNode, MapNode, ReduceNode

__all__ = [
    "DEFAULT_MAP_CONCURRENCY",
    "BarrierNode",
    "BindingNode",
    "BroadcastCollectNode",
    "CollectNode",
    "ExpandNode",
    "FanoutReduceNode",
    "GatherNode",
    "GuardNode",
    "HoldingsNode",
    "InlineCollectionNode",
    "JoinNode",
    "LazyExprNode",
    "MapNode",
    "MergeNode",
    "ProcessNode",
    "ReduceNode",
    "RelUrlNode",
    "RemoteFetchNode",
    "SlotSpec",
    "StructNode",
    "TextNode",
    "WebFetchNode",
]
