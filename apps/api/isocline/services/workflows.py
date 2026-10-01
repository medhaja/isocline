"""Workflow document helpers: export/import sanitization and built-in workflow templates.

Templates produce the same WorkflowGraph schema as the canvas and the AI generator."""
from __future__ import annotations

import copy
import uuid
from typing import Any

from isocline.engine.agent_templates import AGENT_TEMPLATES
from isocline.schemas.workflow import SCHEMA_VERSION, WorkflowGraph

SECRET_FIELDS = {"credential_id", "api_key", "apikey", "password", "token", "secret"}


def strip_secrets(obj: Any) -> Any:
    """Removes credential references and any secret-looking field. Exported JSON never carries credentials."""
    if isinstance(obj, dict):
        return {k: strip_secrets(v) for k, v in obj.items() if str(k).lower() not in SECRET_FIELDS}
    if isinstance(obj, list):
        return [strip_secrets(v) for v in obj]
    return obj


def export_document(name: str, description: str, graph: dict) -> dict:
    g = WorkflowGraph.model_validate(graph).model_dump(mode="json")
    for n in g["nodes"]:
        n["config"].pop("library_agent_id", None)  # library agents are workspace-specific; config is already resolved
    return {"schema_version": SCHEMA_VERSION, "name": name, "description": description, "graph": strip_secrets(g)}


def fresh_ids(graph: dict) -> dict:
    """Re-ids nodes/edges (keys are preserved so {{variables}} keep working)."""
    g = copy.deepcopy(graph)
    mapping = {n["id"]: f"n_{uuid.uuid4().hex[:10]}" for n in g.get("nodes", [])}
    for n in g.get("nodes", []):
        n["id"] = mapping[n["id"]]
        if n.get("parent_id"):
            n["parent_id"] = mapping.get(n["parent_id"])
    for e in g.get("edges", []):
        e["id"] = f"e_{uuid.uuid4().hex[:10]}"
        e["source"] = mapping.get(e["source"], e["source"])
        e["target"] = mapping.get(e["target"], e["target"])
    return g


# ---------------------------------------------------------------------------------------- templates
class _B:
    def __init__(self, model: dict):
        self.model = model
        self.nodes: list[dict] = []
        self.edges: list[dict] = []

    def add(self, key: str, type_: str, name: str, col: int, row: float, **config) -> str:
        nid = f"n_{key}"
        self.nodes.append({"id": nid, "key": key, "type": type_, "name": name,
                           "position": {"x": 60 + col * 280, "y": 100 + row * 130}, "config": config})
        return nid

    def agent(self, key: str, template: str, col: int, row: float, prompt: str, **extra) -> str:
        t = AGENT_TEMPLATES[template]
        name = extra.pop("name", None) or t["name"]
        cfg = {"template": template, "role": t["role"], "instructions": t["instructions"], "prompt": prompt,
               "model": dict(self.model), "params": {"temperature": extra.pop("temperature", 0.3)},
               "tools": extra.pop("tools", list(t["tools"])), "retry": {"retries": 2, "backoff": "exponential", "base_delay_seconds": 1}}
        cfg.update(extra)
        return self.add(key, "agent", name, col, row, **cfg)

    def link(self, s: str, t: str, handle: str | None = None):
        self.edges.append({"id": f"e_{s}_{t}_{handle or 'o'}", "source": s, "target": t, "source_handle": handle, "target_handle": None})

    def graph(self, **settings) -> dict:
        return {"schema_version": SCHEMA_VERSION, "nodes": self.nodes, "edges": self.edges, "settings": settings}


def _company_research(m):
    b = _B(m)
    i = b.add("company", "input_text", "Company", 0, 0, field="company", label="Company name")
    r = b.agent("research", "research", 1, 0, "Research {{input.company}}: business model, products, market, recent news. Cite sources.")
    s = b.agent("summary", "summarizer", 2, 0, "Summarize the research on {{input.company}} for an executive in under 300 words.")
    o = b.add("report", "output_report", "Report", 3, 0, format="markdown")
    b.link(i, r); b.link(r, s); b.link(s, o)
    return b.graph()


def _financial_team(m):
    b = _B(m)
    i = b.add("company", "input_text", "Company", 0, 1, field="company")
    r = b.agent("research", "research", 1, 1, "Research {{input.company}}, focusing on financial performance and risks. Cite sources.")
    f = b.agent("financial", "financial_analyst", 2, 0, "Analyze the financial position of {{input.company}} using the research.", temperature=0.1)
    k = b.agent("risk", "critic", 2, 2, "Assess the key risks for {{input.company}}. Challenge optimistic assumptions.", name="Risk Analyst", temperature=0.1)
    g = b.add("merge", "merge", "Merge", 3, 1, strategy="named")
    mg = b.agent("manager", "manager", 4, 1, "Write the final analysis of {{input.company}} reconciling the financial and risk views.")
    o = b.add("report", "output_report", "Report", 5, 1, format="markdown")
    b.link(i, r); b.link(r, f); b.link(r, k); b.link(f, g); b.link(k, g); b.link(g, mg); b.link(mg, o)
    return b.graph()


def _software_team(m):
    b = _B(m)
    i = b.add("requirement", "input_text", "Requirement", 0, 0, field="requirement")
    pm = b.agent("pm", "product_manager", 1, 0, "Turn this into a spec with acceptance criteria: {{input.requirement}}")
    ar = b.agent("architect", "technical_product_manager", 2, 0, "Design the architecture, APIs and data model for the spec.", name="Architect")
    dev = b.agent("developer", "developer", 3, 0, "Implement the design. Provide complete code.", temperature=0.1)
    rv = b.agent("reviewer", "reviewer", 4, 0, "Review the implementation against the spec and design.")
    o = b.add("output", "output_text", "Output", 5, 0, format="markdown",
              template="## Implementation\n{{developer.output}}\n\n## Review\n{{reviewer.output}}")
    b.link(i, pm); b.link(pm, ar); b.link(ar, dev); b.link(dev, rv); b.link(rv, o)
    return b.graph()


def _research_team(m):
    b = _B(m)
    i = b.add("question", "input_text", "Question", 0, 1, field="question")
    p = b.agent("planner", "planner", 1, 1, "Plan the research for: {{input.question}}")
    w = b.agent("web_research", "research", 2, 0, "Carry out the web research parts of the plan.", name="Web Research")
    d = b.agent("data_research", "data_analyst", 2, 1, "Carry out the quantitative/data parts of the plan.", name="Data Research")
    sp = b.agent("specialist", "critic", 2, 2, "Give a domain-specialist perspective and challenge weak points.", name="Specialist")
    g = b.add("merge", "merge", "Merge", 3, 1, strategy="named")
    sy = b.agent("synthesizer", "writer", 4, 1, "Synthesize the findings into a final answer to: {{input.question}}", name="Synthesizer")
    o = b.add("answer", "output_report", "Answer", 5, 1, format="markdown")
    b.link(i, p); b.link(p, w); b.link(p, d); b.link(p, sp); b.link(w, g); b.link(d, g); b.link(sp, g); b.link(g, sy); b.link(sy, o)
    return b.graph()


def _data_analysis(m):
    b = _B(m)
    i = b.add("dataset", "input_text", "Dataset (CSV text)", 0, 0, field="dataset")
    a = b.agent("analyst", "data_analyst", 1, 0, "Describe this dataset and propose analyses:\n{{input.dataset}}")
    py = b.agent("python", "python", 2, 0, "Write and run Python to compute the proposed analyses on INPUTS['dataset'].",
                 tools=["python"], temperature=0)
    rv = b.agent("reviewer", "reviewer", 3, 0, "Review the analysis and computed results for errors.")
    o = b.add("report", "output_report", "Report", 4, 0, format="markdown")
    b.link(i, a); b.link(a, py); b.link(py, rv); b.link(rv, o)
    return b.graph()


def _investment_team(m):
    """Flagship demo / V1 definition of done."""
    b = _B(m)
    i = b.add("company", "input_text", "Company", 0, 1, field="company", label="Company to analyze")
    r = b.agent("research", "research", 1, 1, "Research {{input.company}}: business, financials, competition, recent news. Cite source URLs.")
    f = b.agent("financial", "financial_analyst", 2, 0, "Analyze {{input.company}}'s financials from the research.", temperature=0.1,
                output_schema={"company": "string", "revenue_trend": "string", "key_metrics": "string", "summary": "string"})
    k = b.agent("risk", "critic", 2, 1, "Identify and score the main risks for {{input.company}} (0-1).", name="Risk Analyst",
                temperature=0.1, output_schema={"risk_score": "number", "top_risks": "string", "summary": "string"})
    py = b.agent("python_analyst", "python", 2, 2, "Use Python to compute any quantitative checks the research supports.",
                 name="Python Analyst", tools=["python"], temperature=0)
    g = b.add("merge", "merge", "Merge", 3, 1, strategy="named")
    ap = b.add("approval", "human_approval", "Human Approval", 4, 1, title="Approve analysis before final report",
               instructions="Review the combined analysis. Edit if needed, then approve or reject.", allow_edit=True)
    mg = b.agent("manager", "manager", 5, 0.5, "Write an executive investment research report on {{input.company}} from the approved analysis:\n{{approval.content}}")
    o = b.add("report", "output_report", "Report", 6, 0.5, format="markdown")
    rej = b.add("rejected", "output_text", "Rejected", 5, 2, template="Analysis rejected: {{approval.comment}}")
    b.link(i, r); b.link(r, f); b.link(r, k); b.link(r, py); b.link(f, g); b.link(k, g); b.link(py, g)
    b.link(g, ap); b.link(ap, mg, "approved"); b.link(ap, rej, "rejected"); b.link(mg, o)
    return b.graph(max_cost=2.0, max_llm_calls=30)


WORKFLOW_TEMPLATES: dict[str, dict] = {
    "investment_research_team": {"name": "AI Investment Research Team", "category": "Flagship",
                                 "description": "Research → Financial, Risk and Python analysts in parallel → merge → human approval → manager report.",
                                 "sample_input": {"company": "Example Corp"}, "build": _investment_team},
    "company_research": {"name": "Company Research", "category": "Research", "description": "Input → Research → Summary.",
                         "sample_input": {"company": "Example Corp"}, "build": _company_research},
    "financial_analysis_team": {"name": "Financial Analysis Team", "category": "Finance",
                                "description": "Research feeds a financial analyst and a risk analyst in parallel; a manager synthesizes.",
                                "sample_input": {"company": "Example Corp"}, "build": _financial_team},
    "software_development_team": {"name": "Software Development Team", "category": "Engineering",
                                  "description": "Requirement → PM → Architect → Developer → Reviewer.",
                                  "sample_input": {"requirement": "A CLI that converts CSV to JSON"}, "build": _software_team},
    "research_team": {"name": "Research Team", "category": "Research",
                      "description": "Planner fans out to web, data and specialist researchers; a synthesizer combines them.",
                      "sample_input": {"question": "What are the main approaches to grid-scale energy storage?"}, "build": _research_team},
    "data_analysis": {"name": "Data Analysis", "category": "Data", "description": "Dataset → Analyst → Python (sandbox) → Reviewer → Report.",
                      "sample_input": {"dataset": "month,revenue\nJan,100\nFeb,120\nMar,90"}, "build": _data_analysis},
}


def build_template(template_id: str, model: dict) -> dict:
    t = WORKFLOW_TEMPLATES[template_id]
    return fresh_ids(t["build"](model))


def _register_library() -> None:
    """Role-based templates (students, job seekers, HR, creators, managers, investors, executives, ...)."""
    from isocline.services.template_library import TEMPLATES, build
    for spec in TEMPLATES:
        WORKFLOW_TEMPLATES[spec["id"]] = {"name": spec["name"], "category": spec["category"], "description": spec["description"],
                                          "sample_input": spec["sample_input"], "build": lambda m, _s=spec: build(_s, m, _B)}


_register_library()


def list_templates() -> list[dict]:
    out = []
    for tid, t in WORKFLOW_TEMPLATES.items():
        g = t["build"]({"provider": "", "model": ""})
        out.append({"id": tid, "name": t["name"], "category": t["category"], "description": t["description"],
                    "sample_input": t["sample_input"], "node_count": len(g["nodes"]),
                    "agents": [n["name"] for n in g["nodes"] if n["type"] == "agent"], "graph_preview": g})
    return out
