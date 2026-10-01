from isocline.engine.router import Candidate, capability_gaps, required_capabilities, route

P = {"input_per_mtok": 1.0, "output_per_mtok": 4.0}


def cand(p, m, cost_scale=1.0, tier=3, lat=5, vision=True, tools=True, ctx=128000, cred=True, **metrics):
    return Candidate(p, m, {"text": True, "vision": vision, "tool_calling": tools, "structured_output": True, "quality_tier": tier, "latency_s": lat},
                     ctx, {"input_per_mtok": P["input_per_mtok"] * cost_scale, "output_per_mtok": P["output_per_mtok"] * cost_scale}, cred, metrics)


CANDS = [cand("openai", "big", 10, tier=5, lat=10), cand("openai", "small", 0.5, tier=3, lat=2), cand("anthropic", "mid", 3, tier=4, lat=5)]


def test_requirements_filter_and_explain():
    d = route(CANDS + [cand("x", "novision", vision=False)], required=["vision", "tool_calling"], est_input_tokens=2000,
              est_output_tokens=500, routing={"objective": "balanced"}, policy_snapshot=[])
    assert d.model is not None and any("Vision" in r for r in d.reasons)
    rej = {c["model"]: c for c in d.candidates if "rejected" in c}
    assert "novision" in rej and "Vision not supported" in rej["novision"]["rejected"][0]


def test_objectives_change_choice():
    kw = dict(required=[], est_input_tokens=2000, est_output_tokens=500, policy_snapshot=[])
    assert route(CANDS, routing={"objective": "cost"}, **kw).model == "small"
    assert route(CANDS, routing={"objective": "quality"}, **kw).model == "big"
    assert route(CANDS, routing={"objective": "latency"}, **kw).model == "small"


def test_measured_quality_beats_prior():
    cands = [cand("openai", "big", 10, tier=5, eval_score=0.60), cand("anthropic", "mid", 3, tier=4, eval_score=0.95)]
    d = route(cands, required=[], est_input_tokens=1000, est_output_tokens=200, routing={"objective": "quality"}, policy_snapshot=[])
    assert d.model == "mid" and "evaluations" in d.reasons[-1]


def test_constraints_policy_credentials_and_health():
    kw = dict(required=[], est_input_tokens=100_000, est_output_tokens=1000)
    d = route(CANDS, routing={"allowed_providers": ["anthropic"]}, policy_snapshot=[], **kw)
    assert d.model == "mid"
    d = route(CANDS, routing={"max_cost_per_call": 0.1}, policy_snapshot=[], **kw)
    assert d.model == "small"
    snap = [{"id": "r", "policy_id": "p", "policy_name": "Prod", "scope_type": "workspace", "kind": "model_allowlist",
             "subject": "*", "action": "*", "effect": "allow", "condition": {}, "value": ["anthropic/*"], "mandatory": True}]
    assert route(CANDS, routing={}, policy_snapshot=snap, **kw).model == "mid"
    assert route([cand("a", "m", cred=False)], routing={}, policy_snapshot=[], **kw).model is None
    sick = [cand("a", "sick", 0.1, recent_error_rate=0.9, recent_calls=10), cand("b", "ok", 5)]
    assert route(sick, routing={"objective": "cost"}, policy_snapshot=[], **kw).model == "ok"


def test_context_and_capability_inference():
    assert required_capabilities(["reasoning"], ["web_search"], True) == ["reasoning", "structured_output", "tool_calling"]
    assert capability_gaps({}, [], 200_000, 128_000)
    d = route(CANDS, required=[], est_input_tokens=150_000, est_output_tokens=1000, routing={}, policy_snapshot=[])
    assert d.model is None  # every model's 128K window is too small


def test_test_provider_needs_explicit_opt_in():
    c = [cand("local_test", "echo", 0.0)]
    assert route(c, required=[], est_input_tokens=10, est_output_tokens=10, routing={}, policy_snapshot=[]).model is None
    assert route(c, required=[], est_input_tokens=10, est_output_tokens=10, routing={"allowed_providers": ["local_test"]}, policy_snapshot=[]).model == "echo"
