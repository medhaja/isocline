"""Structural validation and compilation of a WorkflowGraph into an executable DAG.

Environment checks (credentials, models, secrets) live in services.validation because they need
the database; this module is pure and fully unit-testable.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

from pydantic import ValidationError

from isocline.schemas.workflow import (
    OUTPUT_TYPES, Edge, Node, WorkflowGraph, CONFIG_MODELS, ENTRY_TYPES, WAIT_TYPES,
)

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w]*)((?:\.[\w\-]+|\[\d+\])*)\s*\}\}")


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    data: dict | None = None  # V2: machine-readable detail (e.g. a transform suggestion)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def allowed_source_handles(node: Node) -> set[str | None] | None:
    """None = any handle accepted. Otherwise the allowed set (None == default handle)."""
    t = node.type
    base: set[str | None] = {None, "out", "error"}
    if t == "condition":
        return {"true", "false", "error"}
    if t == "router":
        names = {r.get("name") for r in node.config.get("routes", []) if isinstance(r, dict)}
        return names | {"default", "error"}
    if t == "human_approval":
        return {"approved", "rejected", "timeout"}
    if t in WAIT_TYPES:
        return {None, "out", "timeout", "error"}
    if t in ("loop", "retry"):
        return {"body", "done", None, "out", "error"}
    if t in OUTPUT_TYPES:
        return set()
    return base


@dataclass
class CompiledGraph:
    graph: WorkflowGraph
    nodes: dict[str, Node]
    incoming: dict[str, list[Edge]]
    outgoing: dict[str, list[Edge]]
    order: list[str]  # topological order of top-level executable nodes
    loop_bodies: dict[str, list[str]] = field(default_factory=dict)  # loop node id -> body node ids (topo)
    body_owner: dict[str, str] = field(default_factory=dict)  # body node id -> loop node id
    key_to_id: dict[str, str] = field(default_factory=dict)

    def top_level(self) -> list[str]:
        return [n for n in self.order if n not in self.body_owner]

    def predecessors(self, node_id: str) -> list[str]:
        return [e.source for e in self.incoming.get(node_id, [])]


def _topo(node_ids: list[str], edges: list[Edge]) -> tuple[list[str], set[str]]:
    """Kahn's algorithm. Returns (order, nodes_in_cycles)."""
    ids = set(node_ids)
    indeg = {n: 0 for n in node_ids}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.source in ids and e.target in ids:
            adj[e.source].append(e.target)
            indeg[e.target] += 1
    q = deque([n for n in node_ids if indeg[n] == 0])
    order = []
    while q:
        n = q.popleft()
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    return order, ids - set(order)


def _reachable(start_edges: list[Edge], outgoing: dict[str, list[Edge]]) -> set[str]:
    seen: set[str] = set()
    stack = [e.target for e in start_edges]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(e.target for e in outgoing.get(n, []))
    return seen


def referenced_keys(text: str) -> set[str]:
    return {m.group(1) for m in VAR_RE.finditer(text or "")}


def _walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def validate_structure(graph: WorkflowGraph, max_loop_ceiling: int = 100) -> list[Issue]:
    issues: list[Issue] = []
    nodes = {n.id: n for n in graph.nodes if n.executable}
    all_ids = {n.id for n in graph.nodes}
    keys = {n.key: n.id for n in graph.nodes}

    if not nodes:
        return [Issue("error", "empty_workflow", "Add at least one node to run this workflow")]

    # Per-node config validation
    for n in nodes.values():
        model = CONFIG_MODELS.get(n.type)
        if model is None:
            continue
        try:
            model.model_validate(n.config)
        except ValidationError as ex:
            for err in ex.errors()[:5]:
                loc = ".".join(str(p) for p in err["loc"])
                issues.append(Issue("error", "invalid_config", f"{loc}: {err['msg']}", node_id=n.id))

    # Edge validity
    for e in graph.edges:
        if e.source not in all_ids or e.target not in all_ids:
            issues.append(Issue("error", "dangling_edge", "Edge points to a node that does not exist", edge_id=e.id))
            continue
        if e.source == e.target:
            issues.append(Issue("error", "self_loop", "A node cannot connect to itself", node_id=e.source, edge_id=e.id))
            continue
        src = nodes.get(e.source)
        tgt = nodes.get(e.target)
        if src is None or tgt is None:
            issues.append(Issue("error", "annotation_edge", "Groups and notes cannot be connected", edge_id=e.id))
            continue
        if tgt.type in ENTRY_TYPES:
            issues.append(Issue("error", "input_has_incoming", f"{tgt.name or tgt.key} is an entry point and cannot receive connections", node_id=tgt.id, edge_id=e.id))
        allowed = allowed_source_handles(src)
        if allowed is not None and e.source_handle not in allowed:
            if src.type in OUTPUT_TYPES:
                issues.append(Issue("error", "output_has_outgoing", f"{src.name or src.key} is an output and cannot connect onward", node_id=src.id, edge_id=e.id))
            else:
                issues.append(Issue("error", "invalid_handle", f"Unknown output '{e.source_handle}' on {src.name or src.key}", node_id=src.id, edge_id=e.id))

    valid_edges = [e for e in graph.edges if e.source in nodes and e.target in nodes and e.source != e.target]
    incoming: dict[str, list[Edge]] = defaultdict(list)
    outgoing: dict[str, list[Edge]] = defaultdict(list)
    for e in valid_edges:
        incoming[e.target].append(e)
        outgoing[e.source].append(e)

    # Cycles are illegal; repetition must use Loop/Retry nodes.
    _, cyc = _topo(list(nodes), valid_edges)
    for nid in cyc:
        issues.append(Issue("error", "illegal_cycle", "This node is part of a cycle. Use a Loop node for repetition.", node_id=nid))

    # Connectivity
    has_output = False
    for n in nodes.values():
        if n.type in ENTRY_TYPES:
            if not outgoing.get(n.id):
                issues.append(Issue("warning", "unused_input", "Input is not connected to anything", node_id=n.id))
            continue
        if n.type in OUTPUT_TYPES:
            has_output = True
        if not incoming.get(n.id):
            issues.append(Issue("error", "disconnected_input", "Input is disconnected", node_id=n.id))
        if n.type == "agent":
            cfg = n.config.get("model") or {}
            if not cfg.get("provider") or not cfg.get("model"):
                issues.append(Issue("error", "no_model", "No model configured", node_id=n.id))
        if n.type == "condition":
            rule = n.config.get("rule") or {}
            if not rule.get("left"):
                issues.append(Issue("error", "incomplete_condition", "Condition has no value to test", node_id=n.id))
            handles = {e.source_handle for e in outgoing.get(n.id, [])}
            if not handles & {"true", "false"}:
                issues.append(Issue("error", "condition_unrouted", "Connect the Yes and/or No branch", node_id=n.id))
        if n.type == "router" and not n.config.get("routes"):
            issues.append(Issue("error", "router_empty", "Router has no routes", node_id=n.id))
        if n.type in ("loop", "retry"):
            mi = n.config.get("max_iterations")
            if not isinstance(mi, int) or mi < 1:
                issues.append(Issue("error", "loop_unbounded", "Loops require a maximum iteration count", node_id=n.id))
            elif mi > max_loop_ceiling:
                issues.append(Issue("error", "loop_ceiling", f"Maximum iterations exceeds the server ceiling ({max_loop_ceiling})", node_id=n.id))
            if n.type == "loop" and not n.config.get("collection") and not n.config.get("stop_condition"):
                issues.append(Issue("warning", "loop_no_stop", "Loop has no collection or stop condition; it will run the maximum iterations", node_id=n.id))
            if n.type == "retry" and not n.config.get("stop_condition"):
                issues.append(Issue("error", "retry_no_condition", "Retry needs a success condition", node_id=n.id))
            body = [e for e in outgoing.get(n.id, []) if e.source_handle == "body"]
            if not body:
                issues.append(Issue("error", "loop_no_body", "Connect the loop body", node_id=n.id))
        if n.type == "agent" and n.config.get("on_failure") == "route_error":
            if not any(e.source_handle == "error" for e in outgoing.get(n.id, [])):
                issues.append(Issue("error", "error_route_missing", "On-failure is 'route to error output' but the error output is not connected", node_id=n.id))

    if not has_output:
        issues.append(Issue("error", "no_output", "Add an Output node so the run has a result"))

    # Loop body isolation: body nodes may only be fed from inside the body (or the loop itself)
    for n in nodes.values():
        if n.type not in ("loop", "retry"):
            continue
        body_start = [e for e in outgoing.get(n.id, []) if e.source_handle == "body"]
        body = _reachable(body_start, outgoing)
        if n.id in body:
            issues.append(Issue("error", "loop_body_cycle", "Loop body cannot connect back to its loop", node_id=n.id))
            continue
        for b in body:
            for e in incoming.get(b, []):
                if e.source != n.id and e.source not in body and nodes[e.source].type not in ENTRY_TYPES:
                    issues.append(Issue("error", "loop_body_leak", "Nodes inside a loop body can only receive data from the loop, inputs, or other body nodes", node_id=b, edge_id=e.id))
            for e in outgoing.get(b, []):
                if e.target not in body:
                    issues.append(Issue("error", "loop_body_escape", "Loop body results leave through the loop's Done output, not directly", node_id=b, edge_id=e.id))

    # Variable references must point to known keys
    known = set(keys) | {"input", "vars", "loop", "memory", "run", "upstream"}
    for n in nodes.values():
        for s in _walk_strings(n.config):
            for k in referenced_keys(s):
                if k == "secret":
                    issues.append(Issue("error", "secret_in_template",
                                        "Secrets can't be used in prompts or templates. The harness injects them only into tool "
                                        "calls (e.g. an HTTP header value {{secret:NAME}}), so models never see them.", node_id=n.id))
                elif k not in known:
                    issues.append(Issue("error", "unknown_variable", f"Unknown variable '{{{{{k}}}}}'", node_id=n.id))
                elif k in keys and keys[k] == n.id:
                    issues.append(Issue("error", "self_reference", "A node cannot reference its own output", node_id=n.id))

    # Referenced nodes must be ancestors, otherwise the value may not exist yet (race).
    if not cyc:
        ancestors: dict[str, set[str]] = {}
        order, _ = _topo(list(nodes), valid_edges)
        for nid in order:
            a: set[str] = set()
            for e in incoming.get(nid, []):
                a.add(e.source)
                a |= ancestors.get(e.source, set())
            ancestors[nid] = a
        for n in nodes.values():
            for s in _walk_strings(n.config):
                for k in referenced_keys(s):
                    if k in keys and keys[k] != n.id and keys[k] in nodes and keys[k] not in ancestors.get(n.id, set()):
                        issues.append(Issue("error", "not_upstream", f"'{k}' is not upstream of this node. Connect it first so its output exists.", node_id=n.id))
        # Human approval cannot pause inside a loop body
        for n in nodes.values():
            if n.type in ("loop", "retry"):
                body = _reachable([e for e in outgoing.get(n.id, []) if e.source_handle == "body"], outgoing)
                for b in body:
                    if nodes[b].type == "human_approval":
                        issues.append(Issue("error", "approval_in_loop", "Human approval cannot be placed inside a loop body", node_id=b))

    # Schema compatibility where known: variable path into an upstream output_schema
    for n in nodes.values():
        for s in _walk_strings(n.config):
            for m in VAR_RE.finditer(s):
                k, path = m.group(1), m.group(2)
                if k in keys and path.startswith(".output."):
                    src = nodes.get(keys[k])
                    schema = (src.config.get("output_schema") if src else None) or None
                    field_name = path.split(".")[2]
                    props = _schema_props(schema)
                    if props is not None and field_name not in props:
                        issues.append(Issue("warning", "schema_field_missing", f"'{k}' output schema has no field '{field_name}'", node_id=n.id))
    return issues


def _schema_props(schema) -> set[str] | None:
    if not isinstance(schema, dict):
        return None
    if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
        return set(schema["properties"])
    if "type" not in schema and all(isinstance(v, (str, dict)) for v in schema.values()):
        return set(schema)  # simple {"field": "type"} form
    return None


def compile_graph(graph: WorkflowGraph) -> CompiledGraph:
    nodes = {n.id: n for n in graph.nodes if n.executable}
    edges = [e for e in graph.edges if e.source in nodes and e.target in nodes]
    incoming: dict[str, list[Edge]] = defaultdict(list)
    outgoing: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        incoming[e.target].append(e)
        outgoing[e.source].append(e)
    order, cyc = _topo(list(nodes), edges)
    if cyc:
        raise ValueError("Graph contains cycles")
    cg = CompiledGraph(graph, nodes, incoming, outgoing, order, key_to_id={n.key: n.id for n in nodes.values()})
    for nid in order:
        n = nodes[nid]
        if n.type in ("loop", "retry"):
            body = _reachable([e for e in outgoing[nid] if e.source_handle == "body"], outgoing)
            cg.loop_bodies[nid] = [x for x in order if x in body]
            for b in body:
                cg.body_owner.setdefault(b, nid)
    return cg


# ============================================================================== V2: contracts & typed edges
PASSTHROUGH = {"condition", "router", "parallel"}


def effective_output_type(graph: WorkflowGraph, node_id: str, _seen: frozenset = frozenset()) -> str:
    """Output type of a node; pass-through logic nodes inherit the type of their single input."""
    from isocline.engine.types import default_output_type
    nodes = {n.id: n for n in graph.nodes}
    n = nodes[node_id]
    if n.type in PASSTHROUGH and not (n.contract and n.contract.output.type != "Any"):
        ups = [e.source for e in graph.edges if e.target == node_id and e.source in nodes]
        if len(ups) == 1 and ups[0] not in _seen:
            return effective_output_type(graph, ups[0], _seen | {node_id})
        return "Any"
    return default_output_type(n)


def validate_contracts(graph: WorkflowGraph, custom_types: dict[str, dict] | None = None) -> list[Issue]:
    """Type-checks edges against declared input contracts and validates contract definitions.
    V1 graphs (no contracts) produce no issues: undeclared ports are Any."""
    from isocline.engine.types import TypeError_, compatible, input_port_type, parse_type
    issues: list[Issue] = []
    custom = custom_types or {}
    nodes = {n.id: n for n in graph.nodes if n.executable}

    # 1. contract definitions reference known types
    for n in nodes.values():
        if not n.contract:
            continue
        for p in [*n.contract.inputs, n.contract.output]:
            try:
                parse_type(p.type, custom)
            except TypeError_ as e:
                issues.append(Issue("error", "unknown_type", f"{n.name or n.key}: port '{p.name}': {e}", node_id=n.id))
        names = [p.name for p in n.contract.inputs]
        if len(names) != len(set(names)):
            issues.append(Issue("error", "duplicate_port", f"{n.name or n.key}: input port names must be unique", node_id=n.id))
        if n.type == "agent" and n.contract.allowed_tools is not None:
            extra = [t for t in (n.config.get("tools") or []) if t not in n.contract.allowed_tools]
            if extra:
                issues.append(Issue("error", "contract_tools", f"{n.name or n.key}: tools {extra} are not allowed by its contract", node_id=n.id))

    # 2. edges against declared input ports
    connected_ports: dict[str, set[str]] = defaultdict(set)
    for e in graph.edges:
        src, tgt = nodes.get(e.source), nodes.get(e.target)
        if not src or not tgt:
            continue
        port = input_port_type(tgt, e.target_handle)
        if tgt.contract and len(tgt.contract.inputs) > 1 and not e.target_handle:
            issues.append(Issue("error", "port_required", f"{tgt.name or tgt.key} has several inputs; choose which one this connection feeds",
                                node_id=tgt.id, edge_id=e.id))
            continue
        if tgt.contract and e.target_handle and e.target_handle not in {p.name for p in tgt.contract.inputs}:
            issues.append(Issue("error", "unknown_port", f"{tgt.name or tgt.key} has no input '{e.target_handle}'", node_id=tgt.id, edge_id=e.id))
            continue
        if port is None:
            continue
        dst_type, _ = port
        if e.source_handle == "error":
            src_type = "Error"
        elif e.source_handle == "timeout":
            src_type = "Any"
        else:
            src_type = effective_output_type(graph, src.id)
        try:
            c = compatible(parse_type(src_type, custom), parse_type(dst_type, custom), custom)
        except TypeError_:
            continue  # reported above
        name = e.target_handle or (tgt.contract.inputs[0].name if tgt.contract.inputs else "in")
        connected_ports[tgt.id].add(name)
        if not c.ok:
            issues.append(Issue("error", "type_mismatch",
                                f"{src.name or src.key} produces {src_type} but {tgt.name or tgt.key}.{name} expects {dst_type}"
                                + (f": {c.note}" if c.note else ""),
                                node_id=tgt.id, edge_id=e.id,
                                data={"source_type": src_type, "target_type": dst_type, "suggestion": c.suggestion}))
        elif c.note:
            issues.append(Issue("warning", "type_note", f"{src.name or src.key} → {tgt.name or tgt.key}: {c.note}", node_id=tgt.id, edge_id=e.id))

    # 3. required ports must be connected (single-port nodes count any incoming edge)
    for n in nodes.values():
        if not n.contract or not n.contract.inputs:
            continue
        has_incoming = any(e.target == n.id for e in graph.edges)
        for p in n.contract.inputs:
            if not p.required:
                continue
            if len(n.contract.inputs) == 1 and has_incoming:
                continue
            if p.name not in connected_ports.get(n.id, set()):
                issues.append(Issue("error", "port_unconnected", f"{n.name or n.key}: required input '{p.name}' ({p.type}) is not connected", node_id=n.id))
    return issues


def edge_types(graph: WorkflowGraph, custom_types: dict[str, dict] | None = None) -> dict[str, dict]:
    """Per-edge type info for the canvas (hover labels, red edges)."""
    from isocline.engine.types import TypeError_, compatible, input_port_type, parse_type
    custom = custom_types or {}
    nodes = {n.id: n for n in graph.nodes if n.executable}
    out: dict[str, dict] = {}
    for e in graph.edges:
        src, tgt = nodes.get(e.source), nodes.get(e.target)
        if not src or not tgt:
            continue
        st = "Error" if e.source_handle == "error" else effective_output_type(graph, src.id)
        port = input_port_type(tgt, e.target_handle)
        info = {"source_type": st, "source": f"{src.key}.output", "target": f"{tgt.key}.{e.target_handle or (port and 'in') or 'input'}"}
        if port:
            info["target_type"] = port[0]
            try:
                c = compatible(parse_type(st, custom), parse_type(port[0], custom), custom)
                info["ok"], info["note"], info["suggestion"] = c.ok, c.note, c.suggestion
            except TypeError_ as ex:
                info["ok"], info["note"] = False, str(ex)
        else:
            info["ok"] = True
        out[e.id] = info
    return out
