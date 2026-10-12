"""Notebook visualization helpers for url4 graphs and execution (dev aid only).

This module is **not** part of the ``url4`` library — it exists purely so devs
running the examples notebook can *see* what an expression compiles into and how
it runs. It uses Graphviz for layout.

Requirements (install the notebook group): ``uv sync --group notebook`` for the
``graphviz`` Python package, plus the system Graphviz binary
(``apt install graphviz`` / ``brew install graphviz``). Without the binary, use
:func:`print_tree` (a zero-dependency ASCII fallback).

Functions
---------
- :func:`show_graph` — the compiled DAG: nodes colored by category, top→bottom
  layers = execution order (each layer runs after the one above; nodes in a
  layer run in parallel). Dashed edges are ``$name`` / ``$N`` *context* flow.
- :func:`show_run` — execute the expression, then show the same graph with each
  node badged by its real completion order and annotated with its output, plus a
  step-by-step table.
- :func:`print_tree` — ASCII dependency tree; no Graphviz needed.
"""

from __future__ import annotations

import html

import graphviz

from url4 import StaticIOLayer
from url4.dag import DagNode, Graph, compile_expression, run

# category -> (fill, border). Dark text on a light fill reads on any theme.
_STYLE = {
    "source": ("#d3e5ff", "#2b6cb0"),
    "literal": ("#ececec", "#666666"),
    "binding": ("#e9d8fd", "#6b46c1"),
    "dispatch": ("#ffe0b3", "#c05621"),
    "merge": ("#d5f5e3", "#276749"),
    "collection": ("#c9f0ee", "#2c7a7b"),
    "lazy": ("#fff3bf", "#b7791f"),
    "custom": ("#ffffff", "#333333"),
}
_STRUCT_EDGE, _CTX_EDGE = "#5b6470", "#9f7aea"


def _trunc(text: object, limit: int = 30) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _flatten(value: object) -> str:
    return "\n".join(value) if isinstance(value, list) else str(value)


# -- per-node label + category (data-driven to keep branching low) -----------


def _p_relurl(n) -> str:
    weight = f" w={n.weight:g}" if n.weight is not None else ""
    # a relative expression /path(...)!... vs a bare relative URI /path
    return _trunc(f"{n.path}(…){weight}" if n.is_expr else n.path)


def _p_map(n) -> str:
    extra = []
    if n.directives.concurrency:
        extra.append(f"conc={n.directives.concurrency}")
    if n.directives.on_error != "collect":
        extra.append(n.directives.on_error)
    tail = f"  ;{','.join(extra)}" if extra else ""
    return _trunc(n.body, 24) + tail


def _p_holdings(n) -> str:
    ref = f"@{n.identity}" if n.identity else "@"
    return _trunc(f"{ref}/{n.collection}" if n.collection else ref)


def _p_guard(n) -> str:
    parts = []
    if n.optional:
        parts.append("optional")
    if n.timeout is not None:
        parts.append(f"t={n.timeout:g}")
    if n.retries:
        parts.append(f"retry={n.retries}")
    return ";".join(parts)


# class name -> (display, category, param-formatter or None)
_TYPE_META = {
    "WebFetchNode": ("WebFetch", "source", lambda n: _trunc(n.url)),
    "RelUrlNode": ("RelUrl", "source", _p_relurl),
    "RemoteFetchNode": ("Remote", "source", lambda n: _trunc(f"{n.authority}{n.path}")),
    "HoldingsNode": ("Holdings", "source", _p_holdings),
    "TextNode": ("Text", "literal", lambda n: _trunc(repr(n.template))),
    "StructNode": ("Struct", "literal", lambda n: _trunc(n.raw)),
    "BindingNode": ("Binding", "binding", lambda n: f"{n.name} {n.kind}"),
    "FanoutReduceNode": ("FanoutReduce", "dispatch", lambda n: f"{len(n.meta)} call(s)"),
    "GuardNode": ("Guard", "dispatch", _p_guard),
    "LazyExprNode": ("LazyExpr", "lazy", lambda n: _trunc(n.text)),
    "MapNode": ("Map", "collection", _p_map),
    "ReduceNode": ("Reduce", "collection", lambda n: _trunc(n.reducer)),
    "CollectNode": ("Collect", "collection", None),
    "ExpandNode": ("Expand", "collection", None),
    "InlineCollectionNode": ("InlineColl", "collection", lambda n: f"{len(n.slots)} elem"),
    "MergeNode": ("Merge", "merge", None),
    "BroadcastCollectNode": ("Broadcast", "merge", lambda n: f"{len(n.names)} src"),
    "JoinNode": ("Join", "merge", None),
    "GatherNode": ("Gather", "merge", None),
    "ProcessNode": ("Process", "merge", None),
    "BarrierNode": ("Barrier", "merge", None),
}


def _label_lines(node: DagNode) -> tuple[list[str], str]:
    """Return ``([display, param?], category)`` for ``node``."""
    display, category, param = _TYPE_META.get(
        type(node).__name__, (type(node).__name__, "custom", None)
    )
    lines = [display]
    if param is not None and (text := param(node)):
        lines.append(text)
    return lines, category


# -- graph traversal ----------------------------------------------------------


def _sink(target: str | DagNode | Graph) -> DagNode:
    if isinstance(target, Graph):
        return target.sink
    if isinstance(target, DagNode):
        return target
    return compile_expression(target).sink


def _collect(sink: DagNode) -> tuple[list[DagNode], list[tuple]]:
    """DFS-preorder unique nodes + every ``(parent, child, role)`` edge."""
    nodes: list[DagNode] = []
    seen: set[int] = set()
    edges: list[tuple] = []

    def dfs(node: DagNode) -> None:
        seen.add(id(node))
        nodes.append(node)
        for role, child in node.deps.items():
            edges.append((node, child, role))
            if id(child) not in seen:
                dfs(child)

    dfs(sink)
    return nodes, edges


# -- Graphviz rendering -------------------------------------------------------


def _html_label(node: DagNode, step: int | None, output: str | None) -> str:
    """A Graphviz HTML-like node label: type (bold), params, and run output."""
    lines, category = _label_lines(node)
    _, border = _STYLE[category]
    badge = (
        f'<b><font color="#ffffff" point-size="9"> {step} </font></b>' if step is not None else ""
    )
    rows = [f'<font color="{border}"><b>{html.escape(lines[0])}</b></font>{badge}']
    rows += [f'<font point-size="9">{html.escape(line)}</font>' for line in lines[1:]]
    if output is not None:
        preview = html.escape(_trunc(output, 30))
        rows.append(f'<font color="#276749" point-size="9">→ {preview}</font>')
    return "<" + "<br/>".join(rows) + ">"


def _add_node(
    dot: graphviz.Digraph, node: DagNode, steps: dict | None, results: dict | None
) -> None:
    _, category = _label_lines(node)
    fill, border = _STYLE[category]
    style = "rounded,filled,dashed" if category == "lazy" else "rounded,filled"
    step = steps.get(id(node)) if steps else None
    output = _flatten(results[id(node)]) if results and id(node) in results else None
    dot.node(
        str(id(node)),
        label=_html_label(node, step, output),
        fillcolor=fill,
        color=border,
        style=style,
    )


def _add_edge(dot: graphviz.Digraph, parent: DagNode, child: DagNode, role: str) -> None:
    is_ctx = role.startswith(("bind:", "pos:"))
    # Edge in data-flow direction (child feeds parent); TB layout puts the
    # dependency above its consumer, so layers read top→bottom as execution order.
    dot.edge(
        str(id(child)),
        str(id(parent)),
        label=role,
        color=_CTX_EDGE if is_ctx else _STRUCT_EDGE,
        fontcolor=_CTX_EDGE if is_ctx else _STRUCT_EDGE,
        style="dashed" if is_ctx else "solid",
    )


def build_dot(
    sink: DagNode, *, steps: dict | None = None, results: dict | None = None, caption: str = ""
) -> graphviz.Digraph:
    """Build a :class:`graphviz.Digraph` for the graph rooted at ``sink``."""
    dot = graphviz.Digraph("url4")
    dot.attr(
        rankdir="TB",
        bgcolor="white",
        fontname="sans-serif",
        labelloc="t",
        label=caption,
        fontsize="11",
        fontcolor="#555555",
    )
    dot.attr("node", shape="box", fontname="sans-serif", fontsize="11", margin="0.12,0.06")
    dot.attr("edge", fontname="monospace", fontsize="9", arrowsize="0.7")
    nodes, edges = _collect(sink)
    for node in nodes:
        _add_node(dot, node, steps, results)
    for parent, child, role in edges:
        _add_edge(dot, parent, child, role)
    return dot


# -- execution tracing --------------------------------------------------------


class _Traced:
    """A recording proxy that delegates ``resolve`` to a wrapped node.

    Identity is preserved one-to-one (each original node → one proxy), so the
    executor's per-node memoization is unaffected.
    """

    def __init__(self, node: DagNode, records: dict, clock: list) -> None:
        self._node = node
        self._records = records
        self._clock = clock
        self.wired: dict[str, _Traced] = {}

    @property
    def deps(self):
        return self.wired

    async def resolve(self, inputs, ctx):
        start = self._clock[0]
        self._clock[0] += 1
        result = await self._node.resolve(inputs, ctx)
        self._records[id(self._node)] = {"start": start, "end": self._clock[0], "result": result}
        self._clock[0] += 1
        return result


async def trace_run(target: str | DagNode | Graph, io=None, **run_kwargs):
    """Execute ``target`` with per-node tracing.

    Returns ``(result, sink, records)`` where ``records`` maps ``id(node)`` to
    ``{"start", "end", "result"}``.
    """
    sink = _sink(target)
    records: dict[int, dict] = {}
    clock = [0]
    wrapped: dict[int, _Traced] = {}

    def wrap(node: DagNode) -> _Traced:
        if id(node) not in wrapped:
            proxy = _Traced(node, records, clock)
            wrapped[id(node)] = proxy
            proxy.wired = {role: wrap(child) for role, child in node.deps.items()}
        return wrapped[id(node)]

    result = await run(wrap(sink), io, **run_kwargs)
    return result, sink, records


def _steps(records: dict) -> dict[int, int]:
    order = sorted(records, key=lambda i: records[i]["end"])
    return {node_id: rank + 1 for rank, node_id in enumerate(order)}


# -- step table (HTML) --------------------------------------------------------


def _inputs_preview(node: DagNode, records: dict) -> str:
    parts = [
        f"{role}={_trunc(_flatten(records[id(child)]['result']), 18)}"
        for role, child in node.deps.items()
        if id(child) in records
    ]
    return ", ".join(parts) or "—"


def _step_table(sink: DagNode, records: dict, steps: dict) -> str:
    by_id = {id(n): n for n in _collect(sink)[0]}
    head = (
        '<tr style="text-align:left;border-bottom:1px solid #ccc">'
        "<th>#</th><th>node</th><th>inputs</th><th>output</th></tr>"
    )
    rows = []
    for node_id in sorted(steps, key=lambda i: steps[i]):
        node, rec = by_id[node_id], records[node_id]
        name = " ".join(_label_lines(node)[0])
        rows.append(
            f'<tr style="border-bottom:1px solid #eee"><td>{steps[node_id]}</td>'
            f"<td>{html.escape(name)}</td>"
            f"<td><code>{html.escape(_inputs_preview(node, records))}</code></td>"
            f"<td><code>{html.escape(_trunc(_flatten(rec['result']), 40))}</code></td></tr>"
        )
    return (
        '<table style="border-collapse:collapse;font-size:12px;font-family:sans-serif">'
        f"{head}{''.join(rows)}</table>"
    )


# -- public entry points ------------------------------------------------------

_CAP_STATIC = "compiled DAG · top→bottom = execution order · dashed = $context flow"
_CAP_RUN = "executed DAG · badges = completion order · → = each node's output"


def show_graph(target: str | DagNode | Graph) -> graphviz.Digraph:
    """Render the compiled DAG (returns a Digraph; Jupyter displays it inline)."""
    return build_dot(_sink(target), caption=_CAP_STATIC)


async def show_run(target: str | DagNode | Graph, io=None, **run_kwargs) -> None:
    """Execute ``target`` and display the traced graph + step table + result.

    A display helper (returns ``None``); use :func:`trace_run` for the value.
    Renders inline in Jupyter; falls back to :func:`print_tree` without IPython.
    """
    result, sink, records = await trace_run(target, io, **run_kwargs)
    steps = _steps(records)
    results = {node_id: rec["result"] for node_id, rec in records.items()}
    dot = build_dot(sink, steps=steps, results=results, caption=_CAP_RUN)
    try:
        from IPython.display import HTML, display

        display(dot)
        display(HTML(_step_table(sink, records, steps)))
        display(HTML(f"<b>result:</b> <code>{html.escape(_trunc(_flatten(result), 140))}</code>"))
    except ImportError:
        print_tree(sink)


def print_tree(target: str | DagNode | Graph) -> None:
    """ASCII dependency tree — no Graphviz needed. Marks shared (diamond) nodes."""
    sink = _sink(target)
    seen: set[int] = set()

    def walk(node: DagNode, prefix: str, last: bool, role: str) -> None:
        label = " ".join(_label_lines(node)[0])
        tag = f"{role}: " if role else ""
        dup = "  ↑(shared)" if id(node) in seen else ""
        print(f"{prefix}{'└─' if last else '├─'} {tag}{label}{dup}")
        if id(node) in seen:
            return
        seen.add(id(node))
        items = list(node.deps.items())
        child_prefix = prefix + ("   " if last else "│  ")
        for i, (child_role, child) in enumerate(items):
            walk(child, child_prefix, i == len(items) - 1, child_role)

    walk(sink, "", True, "")


# -- notebook fixture: one offline IOLayer wired with realistic content -------


def _question_in(intent: str) -> str:
    """The text between the first "Re: " and the following " —" in ``intent``, or ""."""
    start = intent.find("Re: ")
    if start < 0:
        return ""
    end = intent.find(" —", start + 4)
    if end < 0:
        return ""
    return intent[start + 4 : end].strip()


def _fake_model(name: str):
    """A fake localhost model route — returns a plausible response by intent.

    A relative expression ``/claude(context)!intent`` is fetched as
    ``/claude?q=(context)!intent``; this handler receives the decoded
    ``(context, intent)``.
    """

    def route(context: str, intent: str) -> str:
        text = intent.lower()
        if (
            "merge" in text
            or "aggregate" in text
            or ("[instruction]" in text and "answer" not in text)
        ):
            return f"[{name}] Consensus: the sources broadly agree; key points reconciled."
        if "answer" in text:
            question = context.strip() or _question_in(intent) or "the request"
            return f"[{name}] Re: {question} — follow the documented steps; escalate if needed."
        headline = f"[{name}] EU advances landmark AI rules while funding a compute push."
        summary = f"[{name}] Summary: the main provisions, obligations, and who they affect."
        return headline if "headline" in text else summary

    return route


# The fetch map (URL / path -> document) — realistic, offline content.
_DOCS: dict[str, str] = {
    "https://news.example.com/ai-act": (
        "EU lawmakers gave final approval to the AI Act, the first broad law governing "
        "artificial intelligence. It ranks systems by risk, bans social scoring and "
        "manipulative uses, and requires transparency and human oversight for high-risk "
        "uses in hiring, credit, and healthcare. Most rules phase in over two years."
    ),
    "https://news.example.com/eu-funding": (
        "The European Commission unveiled a EUR 1.5 billion plan to boost homegrown AI, "
        "funding shared GPU 'AI factories' for startups and universities and grants tied "
        "to compliance with the new AI Act."
    ),
    "https://data.example.com/quarterly.json": (
        '{"quarter": "Q3", "revenue_bn": 4.2, "yoy_growth": 0.18, "region": "EU"}'
    ),
    "/api/patient/42": (
        "Vitals: BP 128/82 mmHg, HR 74 bpm, Temp 37.1 C, SpO2 98%. "
        "Alert and oriented, no acute distress."
    ),
    "https://data.example.com/support-tickets": (
        '[{"id": 1, "question": "How do I reset my password?"}, '
        '{"id": 2, "question": "Why was my card declined at checkout?"}, '
        '{"id": 3, "question": "Can I export my data as CSV?"}]'
    ),
    "https://data.example.com/tickets-messy": (
        '[{"id": 1, "question": "How do I reset my password?"}, '
        '{"id": 2, "note": "customer was satisfied"}]'
    ),
    "https://data.example.com/reading-list": (
        '["Attention Is All You Need", "The Bitter Lesson", "On the Dangers of Stochastic Parrots"]'
    ),
    "https://data.example.com/webpage": (
        "<!DOCTYPE html><html><body>Not a data file</body></html>"
    ),
}

# Localhost expression routes (path -> handler(context, intent)) — the fake models.
_ROUTES = {"/claude": _fake_model("claude"), "/llama": _fake_model("llama")}


class Demo(StaticIOLayer):
    """A fake, offline localhost node for the notebook.

    A :class:`~url4.StaticIOLayer` pre-wired with realistic content: the
    ``fetch_map`` serves static reads (news, data, patient vitals), and
    ``routes`` serves ``/path?q=…`` relative-expression endpoints (the fake
    ``/claude`` / ``/llama`` models). Use the shared module-level :data:`demo` —
    it covers every construct in the notebook, so examples share one ``io``.
    """


#: A ready-to-use IOLayer wired with the realistic demo content above.
demo = Demo(_DOCS, _ROUTES)


__all__ = ["Demo", "build_dot", "demo", "print_tree", "show_graph", "show_run", "trace_run"]
