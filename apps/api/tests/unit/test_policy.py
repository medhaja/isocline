from isocline.engine.policy import (
    apply_budget_clamps, approval_rules_triggered, evaluate_model, evaluate_tool, tool_action,
)


def rule(scope, kind, subject, effect, action="*", mandatory=False, condition=None, value=None, name=None):
    return {"id": f"{scope}-{subject}-{effect}", "policy_id": scope, "policy_name": name or f"{scope} policy", "scope_type": scope,
            "kind": kind, "subject": subject, "action": action, "effect": effect, "condition": condition or {},
            "value": value, "mandatory": mandatory}


def test_classification():
    assert tool_action("http_request", {"method": "GET"}) == "read"
    assert tool_action("http_request", {"method": "POST"}) == "external_write"
    assert tool_action("http_request", {"method": "DELETE"}) == "destructive"
    assert tool_action("mcp:github/merge_pr", {}, {"destructiveHint": True}) == "destructive"
    assert tool_action("mcp:github/get_issue", {}, {"readOnlyHint": True}) == "read"
    assert tool_action("mcp:unknown/thing") == "external_write"  # unknown = conservative


def test_default_allow_and_deny():
    assert evaluate_tool([], "web_search", "read").effect == "allow"
    snap = [rule("workspace", "tool", "http_request", "deny", action="write")]
    assert evaluate_tool(snap, "http_request", "external_write").effect == "deny"
    assert evaluate_tool(snap, "http_request", "read").effect == "allow"


def test_require_approval_for_external_writes():
    snap = [rule("project", "tool", "*", "require_approval", action="external_write")]
    d = evaluate_tool(snap, "mcp:crm/create_record", "external_write")
    assert d.effect == "require_approval" and "project" in d.reason


def test_more_specific_scope_wins_for_optional_rules():
    snap = [rule("workspace", "tool", "web_search", "deny"), rule("workflow", "tool", "web_search", "allow")]
    assert evaluate_tool(snap, "web_search", "read").effect == "allow"


def test_mandatory_parent_cannot_be_weakened():
    snap = [rule("workspace", "tool", "web_search", "deny", mandatory=True), rule("workflow", "tool", "web_search", "allow")]
    d = evaluate_tool(snap, "web_search", "read")
    assert d.effect == "deny" and "mandatory" in d.reason
    snap2 = [rule("workspace", "tool", "*", "require_approval", action="write", mandatory=True),
             rule("workflow", "tool", "http_request", "allow")]
    assert evaluate_tool(snap2, "http_request", "external_write").effect == "require_approval"
    # a lower scope may still tighten
    snap3 = [rule("workspace", "tool", "*", "require_approval", action="write", mandatory=True),
             rule("workflow", "tool", "http_request", "deny")]
    assert evaluate_tool(snap3, "http_request", "external_write").effect == "deny"


def test_conditions():
    snap = [rule("workspace", "tool", "web_search", "deny", condition={"agent_template_not_in": ["research"]}, mandatory=True)]
    assert evaluate_tool(snap, "web_search", "read", {"agent_template": "writer"}).effect == "deny"
    assert evaluate_tool(snap, "web_search", "read", {"agent_template": "research"}).effect == "allow"
    snap = [rule("workspace", "tool", "mcp:mail/send", "require_approval", condition={"arg": "to", "op": "count_gt", "value": 10})]
    many = ",".join(f"u{i}@x.com" for i in range(12))
    assert evaluate_tool(snap, "mcp:mail/send", "external_write", {"args": {"to": many}}).effect == "require_approval"
    assert evaluate_tool(snap, "mcp:mail/send", "external_write", {"args": {"to": "a@x.com"}}).effect == "allow"


def test_model_allowlist_and_deny():
    snap = [rule("workspace", "model_allowlist", "*", "allow", value=["openai/*", "anthropic/*"], mandatory=True)]
    assert evaluate_model(snap, "openai", "gpt-4o").effect == "allow"
    assert evaluate_model(snap, "ollama", "llama3").effect == "deny"
    snap.append(rule("project", "model", "openai/gpt-4o", "deny"))
    assert evaluate_model(snap, "openai", "gpt-4o").effect == "deny"
    assert evaluate_model(snap, "openai", "gpt-4o-mini").effect == "allow"


def test_budget_clamps_only_lower():
    snap = [rule("workspace", "budget", "max_run_cost", "limit", value=5), rule("workflow", "budget", "max_run_cost", "limit", value=10),
            rule("project", "budget", "max_parallel_nodes", "limit", value=4)]
    s = apply_budget_clamps({"max_cost": 20, "max_parallel_nodes": 10}, snap)
    assert s["max_cost"] == 5 and s["max_parallel_nodes"] == 4
    assert apply_budget_clamps({"max_cost": 1}, snap)["max_cost"] == 1


def test_run_approval_rules():
    snap = [rule("project", "approval", "run", "require_approval", condition={"metric": "projected_cost", "op": "gt", "value": 2})]
    assert approval_rules_triggered(snap, {"projected_cost": 2.5})
    assert not approval_rules_triggered(snap, {"projected_cost": 1.0})
