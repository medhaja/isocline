"""Pre-run validation: structure (pure) + environment (credentials, models, tools, secrets, knowledge)."""
from __future__ import annotations

import re

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from isocline.core.config import get_settings
from isocline.db.models import KnowledgeBase, ModelPricing, ProviderCredential
from isocline.engine.graph import Issue, validate_structure
from isocline.providers.registry import provider_classes
from isocline.schemas.workflow import WorkflowGraph

_SECRET_REF = re.compile(r"\{\{secret:([^}]+)\}\}")


def parse_graph(raw: dict) -> tuple[WorkflowGraph | None, list[Issue]]:
    try:
        return WorkflowGraph.model_validate(raw), []
    except ValidationError as e:
        return None, [Issue("error", "schema", f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}") for err in e.errors()[:20]]


async def validate_environment(db: AsyncSession, graph: WorkflowGraph, workspace_id, project_id) -> list[Issue]:
    issues: list[Issue] = []
    s = get_settings()
    providers = provider_classes()
    creds = (await db.execute(select(ProviderCredential).where(ProviderCredential.workspace_id == workspace_id))).scalars().all()
    by_id = {str(c.id): c for c in creds}
    by_provider: dict[str, list] = {}
    for c in creds:
        by_provider.setdefault(c.provider, []).append(c)
    names = {c.name for c in creds} | {c.provider for c in creds}
    kbs = {str(k) for k in (await db.execute(select(KnowledgeBase.id).where(KnowledgeBase.project_id == project_id))).scalars().all()}
    mcp_grants = [(n, t) for n in graph.nodes if n.type == "agent" for t in (n.config.get("tools") or []) if str(t).startswith("mcp:")]
    if mcp_grants:
        from isocline.db.models_v2 import McpServer
        servers = {m.name: m for m in (await db.execute(select(McpServer).where(McpServer.workspace_id == workspace_id))).scalars()}
        for n, t in mcp_grants:
            server, _, tool = t[4:].partition("/")
            srv = servers.get(server)
            if srv is None:
                issues.append(Issue("error", "mcp_server_missing", f"{t}: no MCP server named '{server}' is registered (Integrations)", node_id=n.id))
            elif tool not in (srv.allowed_tools or []):
                issues.append(Issue("error", "mcp_tool_not_allowed",
                                    f"{t}: not on the '{server}' server's allowlist (Integrations), so the agent could never use it", node_id=n.id))
    catalog: dict[str, set[str]] = {}
    for p, m in (await db.execute(select(ModelPricing.provider, ModelPricing.model))).all():
        catalog.setdefault(p, set()).add(m)

    from isocline.providers.env_credentials import provider_env as env_key

    def check_model(node, ref: dict, label: str):
        prov, model, cid = ref.get("provider"), ref.get("model"), ref.get("credential_id")
        if not prov or not model or prov == "auto":  # AUTO: the router only considers configured models
            return
        cls = providers.get(prov)
        if cls is None:
            issues.append(Issue("error", "unknown_provider", f"{label}: provider '{prov}' is not available", node_id=node.id))
            return
        if cid:
            c = by_id.get(str(cid))
            if c is None:
                issues.append(Issue("error", "credential_missing", f"{label}: the selected credential no longer exists", node_id=node.id))
            elif c.provider != prov:
                issues.append(Issue("error", "credential_mismatch", f"{label}: credential is for '{c.provider}', not '{prov}'", node_id=node.id))
        elif cls.requires_key and not by_provider.get(prov) and not env_key(prov)[0]:
            hint = f" or set {' / '.join(cls.env_api_key)} in the environment" if cls.env_api_key else ""
            issues.append(Issue("error", "credential_missing", f"{label}: no {cls.name} API key configured. Add one under Providers{hint}.", node_id=node.id))
        if prov == "openai_compatible" and not (cid and by_id.get(str(cid)) and by_id[str(cid)].base_url) \
                and not any(c.base_url for c in by_provider.get(prov, [])) and not env_key(prov)[1]:
            issues.append(Issue("error", "base_url_missing", f"{label}: OpenAI-compatible endpoint needs a base URL", node_id=node.id))
        known = catalog.get(prov)
        if known and model not in known and not any(model.startswith(k) for k in known) and prov not in ("ollama", "openai_compatible", "openrouter"):
            issues.append(Issue("warning", "model_unknown", f"{label}: '{model}' is not in the model catalog; it may be unavailable", node_id=node.id))

    for n in graph.nodes:
        if n.type == "agent":
            check_model(n, n.config.get("model") or {}, "Model")
            for i, fb in enumerate(n.config.get("fallbacks") or []):
                check_model(n, fb, f"Fallback {i + 1}")
            tools = n.config.get("tools") or []
            kb_ids = n.config.get("knowledge_base_ids") or []
        elif n.type.startswith("tool_"):
            tools = [{"tool_web_search": "web_search", "tool_python": "python", "tool_vector_search": "vector_search"}.get(n.type, "")]
            kb_ids = n.config.get("knowledge_base_ids") or []
        else:
            continue
        if "web_search" in tools and s.search_provider in ("tavily", "brave") and s.search_provider not in names:
            issues.append(Issue("error", "search_credential_missing", f"Web Search credential missing (add a '{s.search_provider}' secret)", node_id=n.id))
        if "python" in tools and not s.sandbox_url:
            issues.append(Issue("error", "sandbox_unavailable", "Python sandbox is not configured", node_id=n.id))
        if "vector_search" in tools and not kb_ids:
            issues.append(Issue("error", "kb_missing", "Vector Search needs at least one knowledge base", node_id=n.id))
        for k in kb_ids:
            if str(k) not in kbs:
                issues.append(Issue("error", "kb_not_found", "Attached knowledge base not found in this project", node_id=n.id))
        for ref in _SECRET_REF.findall(str(n.config)):
            if ref.strip() not in names:
                issues.append(Issue("error", "secret_missing", f"Secret '{ref.strip()}' is referenced but not defined", node_id=n.id))
    return issues


async def validate_all(db: AsyncSession, raw_graph: dict, workspace_id, project_id) -> tuple[WorkflowGraph | None, list[dict]]:
    graph, issues = parse_graph(raw_graph)
    if graph is None:
        return None, [i.as_dict() for i in issues]
    from isocline.engine.graph import validate_contracts
    from isocline.services.types_registry import custom_types_for
    issues = validate_structure(graph, get_settings().ceiling_loop_iterations)
    issues += validate_contracts(graph, await custom_types_for(db, workspace_id))
    issues += await validate_environment(db, graph, workspace_id, project_id)
    return graph, [i.as_dict() for i in issues]
