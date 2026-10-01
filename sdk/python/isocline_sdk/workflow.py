"""Programmatic workflow definition producing the same schema (v2.0) as the visual editor.

    wf = Workflow("analysis")
    company = wf.input("company")
    research = wf.agent("research", prompt="Research {{input.company}}", model="openai/gpt-4o-mini", tools=["web_search"])
    finance = wf.agent("finance", template="financial_analyst", prompt="Analyze using {{research.output}}", model="auto")
    report = wf.output("report", format="markdown")
    company >> research >> finance >> report
    client.workflows.create(project, "Analysis", wf)
"""
from __future__ import annotations

import re
import uuid

_KEY = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class Node:
    def __init__(self, wf: "Workflow", key: str, type_: str, name: str, config: dict, contract: dict | None = None, harness: dict | None = None):
        if not _KEY.match(key):
            raise ValueError(f"Invalid key '{key}': lowercase letters, digits, underscores; start with a letter")
        self.wf, self.key, self.type, self.name, self.config = wf, key, type_, name, config
        self.contract, self.harness = contract, harness or {}
        self.id = f"n_{key}"

    def __rshift__(self, other):
        targets = other if isinstance(other, (list, tuple)) else [other]
        for t in targets:
            self.wf.connect(self, t)
        return other

    def on(self, handle: str) -> "_Handle":
        """Branch output: cond.on("true") >> reviewer"""
        return _Handle(self, handle)


class _Handle:
    def __init__(self, node: Node, handle: str):
        self.node, self.handle = node, handle

    def __rshift__(self, other):
        for t in (other if isinstance(other, (list, tuple)) else [other]):
            self.node.wf.connect(self.node, t, handle=self.handle)
        return other


def _model(m: str | dict | None) -> dict:
    if m is None:
        return {"provider": "", "model": ""}
    if isinstance(m, dict):
        return m
    if m == "auto":
        return {"provider": "auto", "model": "auto"}
    provider, _, model = m.partition("/")
    return {"provider": provider, "model": model}


class Workflow:
    def __init__(self, name: str, **settings):
        self.name = name
        self.nodes: list[Node] = []
        self.edges: list[dict] = []
        self.settings = settings

    def _add(self, n: Node) -> Node:
        if any(x.key == n.key for x in self.nodes):
            raise ValueError(f"Duplicate key '{n.key}'")
        self.nodes.append(n)
        return n

    def input(self, field: str, kind: str = "text", key: str | None = None, **cfg) -> Node:
        return self._add(Node(self, key or field, f"input_{kind}", field.replace("_", " ").title(), {"field": field, **cfg}))

    def agent(self, key: str, *, prompt: str = "", model: str | dict | None = None, template: str = "general", tools: list[str] | None = None,
              output_schema: dict | None = None, contract: dict | None = None, harness: dict | None = None, name: str | None = None, **cfg) -> Node:
        config = {"template": template, "prompt": prompt, "model": _model(model), "tools": tools or [], "output_schema": output_schema, **cfg}
        return self._add(Node(self, key, "agent", name or key.replace("_", " ").title(), config, contract, harness))

    def node(self, key: str, type_: str, name: str | None = None, contract: dict | None = None, harness: dict | None = None, **config) -> Node:
        return self._add(Node(self, key, type_, name or key.replace("_", " ").title(), config, contract, harness))

    def merge(self, key: str = "merge", strategy: str = "named") -> Node:
        return self.node(key, "merge", strategy=strategy)

    def output(self, key: str = "output", format: str = "text", template: str = "") -> Node:
        t = {"json": "output_json", "markdown": "output_report", "file": "output_file"}.get(format, "output_text")
        return self.node(key, t, format=format, template=template)

    def connect(self, a: Node, b: Node, handle: str | None = None, port: str | None = None) -> None:
        self.edges.append({"id": f"e_{uuid.uuid4().hex[:10]}", "source": a.id, "target": b.id, "source_handle": handle, "target_handle": port})

    def to_graph(self) -> dict:
        depth: dict[str, int] = {}
        for n in self.nodes:
            preds = [e["source"] for e in self.edges if e["target"] == n.id]
            depth[n.id] = 0
        for _ in range(len(self.nodes)):
            for e in self.edges:
                depth[e["target"]] = max(depth[e["target"]], depth[e["source"]] + 1)
        rows: dict[int, int] = {}
        nodes = []
        for n in self.nodes:
            d = depth[n.id]
            r = rows.get(d, 0)
            rows[d] = r + 1
            nd = {"id": n.id, "key": n.key, "type": n.type, "name": n.name, "position": {"x": 80 + d * 280, "y": 100 + r * 140},
                  "config": {k: v for k, v in n.config.items() if v is not None}}
            if n.contract:
                nd["contract"] = n.contract
            if n.harness:
                nd["harness"] = n.harness
            nodes.append(nd)
        return {"schema_version": "2.0", "nodes": nodes, "edges": list(self.edges), "settings": dict(self.settings)}

    def to_document(self, description: str = "") -> dict:
        return {"schema_version": "2.0", "name": self.name, "description": description, "graph": self.to_graph()}
