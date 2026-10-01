"""Regenerates packages/workflow-schema/*.json from the backend Pydantic models (the single source of truth).
Run: python scripts/export_schema.py   (CI fails if the committed files are stale)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from isocline.schemas.workflow import (  # noqa: E402
    CONFIG_MODELS, NODE_TYPES, SCHEMA_VERSION, WorkflowDocument, WorkflowGraph,
)

out = ROOT / "packages" / "workflow-schema"
out.mkdir(parents=True, exist_ok=True)
graph = WorkflowGraph.model_json_schema()
graph["$id"] = f"https://isocline.dev/schema/workflow-graph-{SCHEMA_VERSION}.json"
(out / "workflow-graph.schema.json").write_text(json.dumps(graph, indent=2) + "\n")
doc = WorkflowDocument.model_json_schema()
doc["$id"] = f"https://isocline.dev/schema/workflow-document-{SCHEMA_VERSION}.json"
(out / "workflow-document.schema.json").write_text(json.dumps(doc, indent=2) + "\n")
configs = {t: m.model_json_schema() for t, m in sorted(CONFIG_MODELS.items())}
(out / "node-configs.schema.json").write_text(json.dumps({"schema_version": SCHEMA_VERSION, "node_types": sorted(NODE_TYPES),
                                                          "configs": configs}, indent=2) + "\n")
print(f"wrote schema v{SCHEMA_VERSION} to {out}")
