"""Create-with-AI workflow generation, and graph operations shared with the optimizer.

Both produce the SAME WorkflowGraph schema used by the canvas. The model is asked for a compact
intermediate plan (node keys + edges), which is converted, laid out and validated server-side.
Graph changes from the assistant are returned as a proposed patch; nothing is applied without the
user's confirmation in the UI.

When the offline `local_test` provider is selected, a clearly-labelled keyword heuristic is used
instead of a model (method="heuristic") so the feature can be exercised without an API key."""
from __future__ import annotations

import copy
import re
import uuid
from collections import defaultdict

from isocline.engine.agent_templates import AGENT_TEMPLATES
from isocline.engine.graph import validate_structure
from isocline.schemas.workflow import (
    AGENT_TEMPLATES as TEMPLATE_IDS, NODE_TYPES, SCHEMA_VERSION, TOOL_NAMES, WorkflowGraph,
)

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "input_fields": {"type": "array", "items": {"type": "string"}},
        "nodes": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"}, "type": {"type": "string"}, "name": {"type": "string"},
            "template": {"type": "string"}, "prompt": {"type": "string"}, "instructions": {"type": "string"},
            "tools": {"type": "array", "items": {"type": "string"}}, "config": {"type": "object"}},
            "required": ["key", "type", "name"]}},
        "edges": {"type": "array", "items": {"type": "object", "properties": {
            "source": {"type": "string"}, "target": {"type": "string"}, "handle": {"type": "string"}},
            "required": ["source", "target"]}},
    },
    "required": ["name", "nodes", "edges"],
}

GENERATOR_SYSTEM = f"""You design multi-agent AI workflows for Isocline. Return ONLY JSON matching the schema.
Node types: {sorted(t for t in NODE_TYPES if t not in ('group', 'note'))}.
Agent templates (for type "agent", field "template"): {TEMPLATE_IDS}.
Agent tools: {TOOL_NAMES} (grant only what the agent needs; research agents usually need web_search).
Rules:
- keys are lowercase snake_case, unique, not one of: input, vars, loop, memory, run.
- Start with exactly one input node per input field (type input_text, config {{"field": "<field>"}}).
- End with at least one output node (output_text / output_report / output_json). Outputs have no outgoing edges.
- Independent work should run in PARALLEL (fan out from one node, then join with a "merge" node, config {{"strategy": "named"}}).
- Prompts may reference {{{{input.<field>}}}} and upstream outputs as {{{{<node_key>.output}}}} (only upstream nodes).
- condition nodes need config {{"rule": {{"left": "{{{{x.output.field}}}}", "operator": ">", "right": 0.8}}}} and edges with handle "true"/"false".
- human_approval edges use handle "approved"/"rejected". No cycles; use a loop node with max_iterations for repetition.
Keep it to what the user asked for; typically 4-10 nodes."""


def _slug(s: str, taken: set[str]) -> str:
    k = re.sub(r"[^a-z0-9_]+", "_", (s or "node").lower()).strip("_") or "node"
    if not k[0].isalpha():
        k = "n_" + k
    k = k[:40]
    if k in {"input", "vars", "loop", "memory", "run", "upstream", "env", "secrets"}:
        k += "_node"
    base, i = k, 2
    while k in taken:
        k, i = f"{base}_{i}", i + 1
    taken.add(k)
    return k


def layout(graph: dict) -> dict:
    """Layered left-to-right layout by longest-path depth (the canvas can re-run dagre auto-layout)."""
    nodes = graph["nodes"]
    preds = defaultdict(list)
    for e in graph["edges"]:
        preds[e["target"]].append(e["source"])
    depth: dict[str, int] = {}

    def d(nid, seen=()):
        if nid in depth:
            return depth[nid]
        if nid in seen:
            return 0
        depth[nid] = 0 if not preds[nid] else 1 + max(d(p, seen + (nid,)) for p in preds[nid])
        return depth[nid]
    rows = defaultdict(int)
    for n in nodes:
        col = d(n["id"])
        n["position"] = {"x": 80 + col * 290, "y": 100 + rows[col] * 150}
        rows[col] += 1
    for n in nodes:  # vertically centre each column
        col = depth[n["id"]]
        n["position"]["y"] += (max(rows.values()) - rows[col]) * 75
    return graph


def plan_to_graph(plan: dict, model: dict) -> dict:
    taken: set[str] = set()
    key_map: dict[str, str] = {}
    nodes: list[dict] = []
    for raw in plan.get("nodes", []):
        t = raw.get("type") if raw.get("type") in NODE_TYPES else "agent"
        key = _slug(raw.get("key") or raw.get("name") or t, taken)
        key_map[raw.get("key") or key] = key
        cfg = dict(raw.get("config") or {})
        if t == "agent":
            tpl = raw.get("template") if raw.get("template") in AGENT_TEMPLATES else "general"
            base = AGENT_TEMPLATES[tpl]
            cfg = {"template": tpl, "role": base["role"], "instructions": raw.get("instructions") or base["instructions"],
                   "prompt": raw.get("prompt") or "", "model": dict(model), "params": {"temperature": 0.3},
                   "tools": [x for x in (raw.get("tools") if raw.get("tools") is not None else base["tools"]) if x in TOOL_NAMES],
                   "retry": {"retries": 2, "backoff": "exponential", "base_delay_seconds": 1}, **{k: v for k, v in cfg.items() if k in ("output_schema",)}}
        elif t.startswith("input_") and "field" not in cfg:
            cfg["field"] = key
        nodes.append({"id": f"n_{uuid.uuid4().hex[:10]}", "key": key, "type": t, "name": raw.get("name") or key.replace("_", " ").title(),
                      "position": {"x": 0, "y": 0}, "config": cfg})
    by_key = {n["key"]: n["id"] for n in nodes}
    edges, seen = [], set()
    for e in plan.get("edges", []):
        s, t = by_key.get(key_map.get(e.get("source"), e.get("source"))), by_key.get(key_map.get(e.get("target"), e.get("target")))
        if not s or not t or s == t or (s, t, e.get("handle")) in seen:
            continue
        seen.add((s, t, e.get("handle")))
        edges.append({"id": f"e_{uuid.uuid4().hex[:10]}", "source": s, "target": t, "source_handle": e.get("handle") or None, "target_handle": None})
    # rewrite {{old_key.…}} references to the final keys
    for n in nodes:
        for fld in ("prompt", "instructions"):
            if isinstance(n["config"].get(fld), str):
                n["config"][fld] = re.sub(r"\{\{\s*([a-zA-Z_]\w*)", lambda m: "{{" + key_map.get(m.group(1), m.group(1)), n["config"][fld])
    return layout({"schema_version": SCHEMA_VERSION, "nodes": nodes, "edges": edges, "settings": {}})


# ------------------------------------------------------------------------------ heuristic (offline) planner
_ROLE_WORDS = [
    ("research", "research", "Researcher", ["research", "investigate", "search", "look up"]),
    ("financial", "financial_analyst", "Financial Analyst", ["financ", "revenue", "valuation"]),
    ("risk", "critic", "Risk Analyst", ["risk", "challenge", "critic"]),
    ("python_analyst", "python", "Python Analyst", ["python", "calculat", "compute"]),
    ("data_analyst", "data_analyst", "Data Analyst", ["data", "dataset", "statistic"]),
    ("developer", "developer", "Developer", ["code", "develop", "implement"]),
    ("reviewer", "reviewer", "Reviewer", ["review", "check"]),
    ("writer", "writer", "Writer", ["write", "draft", "blog", "article"]),
    ("summarizer", "summarizer", "Summarizer", ["summar"]),
]


def heuristic_plan(description: str) -> dict:
    text = description.lower()
    first = [r for r in _ROLE_WORDS if r[0] == "research" and any(w in text for w in r[3])]
    workers = [r for r in _ROLE_WORDS if r[0] not in ("research", "reviewer", "writer", "summarizer") and any(w in text for w in r[3])]
    manager = any(w in text for w in ("manager", "report", "synthes", "combine", "final"))
    approval = any(w in text for w in ("approv", "human", "sign off", "sign-off"))
    reviewer = [r for r in _ROLE_WORDS if r[0] in ("reviewer",) and any(w in text for w in r[3])]
    nodes = [{"key": "request", "type": "input_text", "name": "Input", "config": {"field": "request"}}]
    edges: list[dict] = []
    prev = ["request"]
    for key, tpl, name, _ in first:
        nodes.append({"key": key, "type": "agent", "name": name, "template": tpl, "prompt": "{{input.request}}"})
        edges += [{"source": p, "target": key} for p in prev]
        prev = [key]
    if not workers and not first:
        workers = [("general", "general", "General Agent", [])]
    for key, tpl, name, _ in workers:
        nodes.append({"key": key, "type": "agent", "name": name, "template": tpl,
                      "prompt": "Task: {{input.request}}", "tools": ["python"] if tpl == "python" else None})
        edges += [{"source": p, "target": key} for p in prev]
    if len(workers) > 1:
        nodes.append({"key": "merge", "type": "merge", "name": "Merge", "config": {"strategy": "named"}})
        edges += [{"source": w[0], "target": "merge"} for w in workers]
        prev = ["merge"]
    elif workers:
        prev = [workers[0][0]]
    for key, tpl, name, _ in reviewer:
        nodes.append({"key": key, "type": "agent", "name": name, "template": tpl, "prompt": "Review the work for: {{input.request}}"})
        edges += [{"source": p, "target": key} for p in prev]
        prev = [key]
    if approval:
        nodes.append({"key": "approval", "type": "human_approval", "name": "Human Approval", "config": {"title": "Approve before continuing"}})
        edges += [{"source": p, "target": "approval"} for p in prev]
        prev = ["approval"]
    if manager:
        nodes.append({"key": "manager", "type": "agent", "name": "Manager", "template": "manager",
                      "prompt": "Produce the final report for: {{input.request}}"})
        edges += [{"source": p, "target": "manager", "handle": "approved" if p == "approval" else None} for p in prev]
        prev = ["manager"]
    nodes.append({"key": "output", "type": "output_report", "name": "Report", "config": {"format": "markdown"}})
    edges += [{"source": p, "target": "output", "handle": "approved" if p == "approval" else None} for p in prev]
    return {"name": "Generated workflow", "description": description[:300], "nodes": nodes, "edges": edges}


def issues_for(graph: dict) -> list[dict]:
    try:
        g = WorkflowGraph.model_validate(graph)
    except Exception as e:
        return [{"severity": "error", "code": "schema", "message": str(e)[:500]}]
    return [i.as_dict() for i in validate_structure(g)]


async def generate_workflow(db, workspace_id, project_id, description: str, model: dict, agent_model: dict | None = None) -> dict:
    agent_model = agent_model or model
    if model.get("provider") == "local_test":
        graph = plan_to_graph(heuristic_plan(description), agent_model)
        plan_name = "Generated workflow"
        return {"name": plan_name, "description": description[:300], "graph": graph, "issues": issues_for(graph), "method": "heuristic",
                "note": "Generated by the offline keyword heuristic (local test provider), not by an AI model."}
    from isocline.services.llm import complete
    res = await complete(db, workspace_id, model, GENERATOR_SYSTEM, f"Design a workflow for:\n{description}", json_schema=PLAN_SCHEMA,
                         purpose="generator", project_id=project_id, temperature=0.2)
    plan = res.data or {}
    graph = plan_to_graph(plan, agent_model)
    issues = issues_for(graph)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:  # one repair round with the validator's feedback
        res2 = await complete(db, workspace_id, model, GENERATOR_SYSTEM,
                              f"Design a workflow for:\n{description}\n\nYour previous plan:\n{plan}\n\nIt failed validation:\n"
                              + "\n".join(f"- {e['message']}" for e in errors[:15]) + "\nReturn a corrected plan.",
                              json_schema=PLAN_SCHEMA, purpose="generator", project_id=project_id, temperature=0)
        plan2 = res2.data or {}
        g2 = plan_to_graph(plan2, agent_model)
        i2 = issues_for(g2)
        if len([i for i in i2 if i["severity"] == "error"]) < len(errors):
            plan, graph, issues = plan2, g2, i2
    return {"name": plan.get("name") or "Generated workflow", "description": plan.get("description") or description[:300],
            "graph": graph, "issues": issues, "method": "model", "model": f"{res.provider}/{res.model}"}


# ------------------------------------------------------------------------------ graph operations (used by the optimizer)
def _deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def apply_operations(graph: dict, ops: list[dict], model: dict | None) -> tuple[dict, list[str]]:
    g = copy.deepcopy(graph)
    g.setdefault("nodes", []), g.setdefault("edges", []), g.setdefault("settings", {})
    log: list[str] = []

    def by_key(k):
        return next((n for n in g["nodes"] if n["key"] == k), None)
    for op in ops:
        kind = op.get("op")
        if kind == "add_node":
            raw = op.get("node") or {}
            default_model = model or next((n["config"].get("model") for n in g["nodes"] if n["type"] == "agent" and n["config"].get("model")), {})
            new = plan_to_graph({"nodes": [raw], "edges": []}, default_model or {"provider": "", "model": ""})["nodes"][0]
            new["position"] = {"x": 0, "y": 0}  # placed after edges are known
            taken = {n["key"] for n in g["nodes"]}
            if new["key"] in taken:
                new["key"] = _slug(new["key"], taken)
            g["nodes"].append(new)
            log.append(f"Add {new['type'].replace('_', ' ')} '{new['name']}' ({new['key']})")
        elif kind == "remove_node":
            n = by_key(op.get("node_key"))
            if n:
                g["nodes"].remove(n)
                g["edges"] = [e for e in g["edges"] if n["id"] not in (e["source"], e["target"])]
                log.append(f"Remove '{n['name']}'")
        elif kind == "update_node":
            n = by_key(op.get("node_key"))
            ch = op.get("changes") or {}
            if n:
                if ch.get("name"):
                    n["name"] = ch["name"]
                if isinstance(ch.get("config"), dict):
                    n["config"] = _deep_merge(n["config"], ch["config"])
                log.append(f"Update '{n['name']}': {', '.join(list((ch.get('config') or {}).keys()) + (['name'] if ch.get('name') else []))}")
        elif kind == "add_edge":
            s, t = by_key(op.get("source")), by_key(op.get("target"))
            if s and t and not any(e["source"] == s["id"] and e["target"] == t["id"] for e in g["edges"]):
                g["edges"].append({"id": f"e_{uuid.uuid4().hex[:10]}", "source": s["id"], "target": t["id"],
                                   "source_handle": op.get("handle") or None, "target_handle": None})
                log.append(f"Connect {s['key']} → {t['key']}" + (f" ({op['handle']})" if op.get("handle") else ""))
        elif kind == "remove_edge":
            s, t = by_key(op.get("source")), by_key(op.get("target"))
            if s and t:
                before = len(g["edges"])
                g["edges"] = [e for e in g["edges"] if not (e["source"] == s["id"] and e["target"] == t["id"])]
                if len(g["edges"]) < before:
                    log.append(f"Disconnect {s['key']} → {t['key']}")
        elif kind == "update_settings" and isinstance(op.get("settings"), dict):
            g["settings"] = {**g["settings"], **op["settings"]}
            log.append(f"Update settings: {', '.join(op['settings'].keys())}")
    # place newly added nodes without positions near their upstream
    ids_pos = {n["id"]: n["position"] for n in g["nodes"]}
    for n in g["nodes"]:
        if n["position"] == {"x": 0, "y": 0}:
            ups = [ids_pos[e["source"]] for e in g["edges"] if e["target"] == n["id"] and e["source"] in ids_pos]
            if ups:
                n["position"] = {"x": max(p["x"] for p in ups) + 290, "y": sum(p["y"] for p in ups) / len(ups) + 40}
    return g, log


