import pytest

from isocline.core.logging import redact
from isocline.core.security import decrypt_secret, encrypt_secret, hash_api_key, hash_password, verify_password
from isocline.engine.budget import Budget, BudgetExceeded, effective_settings
from isocline.engine.expressions import Scope, compare, evaluate_rule, render, resolve_value
from isocline.engine.structured import StructuredOutputError, extract_json, normalize_schema, parse_and_validate
from isocline.providers.base import ProviderError, classify_http
from isocline.tools.calculator import safe_eval
from isocline.tools.ssrf import check_url


# ------------------------------------------------------------------ variable resolution
def scope():
    return Scope({"company": "Acme", "n": 3}, {"research": {"summary": "good", "items": [1, 2]}, "writer": "plain text"},
                 variables={"tone": "formal"})


def test_render_and_shortcuts():
    s = scope()
    assert render("Co: {{input.company}} / {{research.summary}} / {{vars.tone}}", s) == "Co: Acme / good / formal"
    assert resolve_value("{{research.output.items[1]}}", s) == 2
    assert resolve_value("{{writer.output}}", s) == "plain text"


def test_missing_variable_renders_empty_or_raises_in_strict():
    s = scope()
    assert render("x{{nope.output}}y", s) == "xy"
    with pytest.raises(Exception):
        render("x{{nope.output}}y", s, strict=True)


# ------------------------------------------------------------------ conditions (no eval)
@pytest.mark.parametrize("left,op,right,expected", [
    (5, ">", 3, True), ("0.9", ">=", 0.8, True), (1, "<", 0, False), ("a", "==", "a", True),
    ("abc", "contains", "b", True), ([1, 2], "contains", 2, True), (None, "exists", None, False),
    ("x", "!=", "y", True), (2, "<=", "2", True),
])
def test_compare(left, op, right, expected):
    assert compare(left, op, right) is expected


def test_evaluate_rule_uses_scope_and_rejects_code():
    ok, left, _ = evaluate_rule({"left": "{{input.n}}", "operator": ">", "right": 2}, scope())
    assert ok and left == 3
    ok, _, _ = evaluate_rule({"left": "__import__('os').system('x')", "operator": "exists"}, scope())
    assert ok  # treated as a literal string; never evaluated


# ------------------------------------------------------------------ structured output
def test_simple_schema_normalized():
    js = normalize_schema({"company": "string", "revenue": "number"})
    assert js["type"] == "object" and js["properties"]["revenue"]["type"] == "number"
    assert set(js["required"]) == {"company", "revenue"}


def test_extract_json_from_fenced_text():
    assert extract_json('Here:\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(StructuredOutputError):
        extract_json("no json here")


def test_parse_and_validate_rejects_wrong_types():
    schema = normalize_schema({"score": "number"})
    assert parse_and_validate('{"score": 0.5}', None, schema) == {"score": 0.5}
    with pytest.raises(StructuredOutputError):
        parse_and_validate('{"score": "high"}', None, schema)


# ------------------------------------------------------------------ budget
async def test_budget_enforces_calls_tokens_cost():
    b = Budget(limits=effective_settings({"max_llm_calls": 2, "max_cost": 0.01, "max_total_tokens": 1000}))
    await b.reserve_llm_call(0.001, 10)
    await b.record_usage(100, 100, 0.005)
    with pytest.raises(BudgetExceeded) as e:
        await b.reserve_llm_call(0.009, 10)
    assert e.value.limit == "max_cost"
    await b.reserve_llm_call(0.001, 10)
    with pytest.raises(BudgetExceeded) as e:
        await b.reserve_llm_call(0.0, 10)
    assert e.value.limit == "max_llm_calls"


def test_settings_clamped_to_server_ceilings():
    eff = effective_settings({"max_llm_calls": 10**6, "max_loop_iterations": 10**6})
    assert eff["max_llm_calls"] <= 500 and eff["max_loop_iterations"] <= 100


# ------------------------------------------------------------------ tools
def test_calculator_safe():
    assert safe_eval("2 + 3 * (4 - 1) ** 2") == 29
    assert abs(safe_eval("sqrt(16) + log10(100)") - 6) < 1e-9
    for bad in ["__import__('os')", "open('x')", "(1).__class__", "9**9**9"]:
        with pytest.raises(Exception):
            safe_eval(bad)


@pytest.mark.parametrize("url", ["http://localhost/x", "http://127.0.0.1:8000", "http://169.254.169.254/latest/meta-data",
                                 "http://10.0.0.5/", "http://192.168.1.1", "http://[::1]/", "file:///etc/passwd",
                                 "http://metadata.google.internal/"])
async def test_ssrf_blocks_internal_targets(url):
    with pytest.raises(Exception):
        await check_url(url)


# ------------------------------------------------------------------ providers
def test_provider_error_classification():
    assert classify_http(429, "slow down").kind == "rate_limit"
    assert classify_http(404, "model not found").kind in ("model_unavailable", "not_found")
    assert classify_http(503, "").fallback_eligible
    assert not classify_http(400, "bad request").fallback_eligible
    assert ProviderError("rate_limit", "x").retryable


# ------------------------------------------------------------------ security
def test_secrets_and_keys():
    ct = encrypt_secret("sk-live-123456")
    assert b"sk-live" not in ct and decrypt_secret(ct) == "sk-live-123456"
    assert hash_api_key("isc_pat_example") != "isc_pat_example" and len(hash_api_key("isc_pat_example")) == 64
    pw = hash_password("correct horse")
    assert verify_password("correct horse", pw) and not verify_password("wrong", pw)


def test_redaction():
    out = redact({"api_key": "sk-abc", "nested": {"Authorization": "Bearer x"}, "text": "key sk-ant-abcdefghijklmnopqrstu"})
    assert out["api_key"] != "sk-abc" and out["nested"]["Authorization"] != "Bearer x"
    assert "sk-ant-abcdefghijklmnopqrstu" not in out["text"]
    assert redact({"note": "my token s3cr3t-value"}, ["s3cr3t-value"])["note"] == "my token [REDACTED]"


async def test_openai_retries_with_reasoning_effort_none_when_tools_are_rejected():
    """gpt-6-luna and similar reject function tools + reasoning_effort on /chat/completions (HTTP 400)."""
    import json as _json

    import httpx
    import respx

    from isocline.providers.base import Message, ProviderConfig, ToolSpec
    from isocline.providers.openai_compat import OpenAIProvider

    rejected = {"error": {"message": "Function tools with reasoning_effort are not supported for gpt-6-luna in "
                          "/v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to 'none'.",
                          "type": "invalid_request_error", "param": "reasoning_effort", "code": None}}
    ok = {"choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
          "usage": {"prompt_tokens": 5, "completion_tokens": 2}, "model": "gpt-6-luna"}
    prov = OpenAIProvider(ProviderConfig(api_key="sk-test", base_url=None))
    tool = ToolSpec(name="web_search", description="search", input_schema={"type": "object", "properties": {}})
    with respx.mock() as m:
        route = m.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[httpx.Response(400, json=rejected), httpx.Response(200, json=ok)])
        res = await prov.generate([Message(role="user", content="hi")], "gpt-6-luna", {"reasoning_effort": "medium"}, tools=[tool])
    sent = [_json.loads(c.request.content) for c in route.calls]
    assert [b.get("reasoning_effort") for b in sent] == ["medium", "none"]
    assert sent[1]["tools"], "tools must still be sent"
    assert res.text == "done" and any("reasoning_effort" in i for i in res.ignored_params)
    # The model's own default can trigger the same 400 when Isocline sends no reasoning_effort at all.
    with respx.mock() as m:
        route = m.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[httpx.Response(400, json=rejected), httpx.Response(200, json=ok)])
        await prov.generate([Message(role="user", content="hi")], "gpt-6-luna", {}, tools=[tool])
    sent = [_json.loads(c.request.content) for c in route.calls]
    assert [b.get("reasoning_effort") for b in sent] == [None, "none"]
    # Unrelated 400s are not retried.
    with respx.mock() as m:
        route = m.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(400, json={"error": {"message": "Invalid value for 'temperature'"}}))
        try:
            await prov.generate([Message(role="user", content="hi")], "gpt-6-luna", {}, tools=[tool])
        except Exception:
            pass
    assert len(route.calls) == 1


def test_logs_redact_access_tokens():
    from isocline.core.logging import _redact_processor
    ev = _redact_processor(None, "info", {"event": "x", "auth": "Bearer isc_pat_" + "a1" * 24})
    assert "isc_pat_a1a1" not in str(ev)
