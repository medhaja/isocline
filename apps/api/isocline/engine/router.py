"""AUTO model routing. Deterministic and explainable: candidates are filtered by hard requirements
(capabilities, context, policy, routing constraints, credentials, health) and ranked by a weighted score of
measured quality, cost and latency — falling back to registry priors when no measurements exist.
The explanation is built from those rules and metrics; no model is asked to choose a model."""
from __future__ import annotations

from dataclasses import dataclass, field

from isocline.engine.policy import evaluate_model
from isocline.engine.pricing import estimate_cost

WEIGHTS = {"quality": (0.7, 0.15, 0.15), "cost": (0.15, 0.7, 0.15), "latency": (0.15, 0.15, 0.7), "balanced": (0.4, 0.3, 0.3)}
CAP_LABEL = {"vision": "Vision", "tool_calling": "Tool calling", "structured_output": "Structured output",
             "reasoning": "Reasoning", "large_context": "Large context", "coding": "Coding", "text": "Text"}


@dataclass
class Candidate:
    provider: str
    model: str
    capabilities: dict
    context_window: int | None
    pricing: dict | None
    has_credential: bool
    metrics: dict = field(default_factory=dict)  # calls, success_rate, p50_latency_ms, eval_score, recent_error_rate


@dataclass
class RouteDecision:
    provider: str | None
    model: str | None
    reasons: list[str]
    candidates: list[dict]
    fallbacks: list[tuple[str, str]]

    def as_dict(self) -> dict:
        return {"provider": self.provider, "model": self.model, "reasons": self.reasons, "candidates": self.candidates}


def required_capabilities(contract_caps: list[str] | None, tools: list[str] | None, structured: bool, images: bool = False) -> list[str]:
    caps = set(contract_caps or [])
    if tools:
        caps.add("tool_calling")
    if structured:
        caps.add("structured_output")
    if images:
        caps.add("vision")
    caps.discard("text")
    return sorted(caps)


def capability_gaps(caps: dict, required: list[str], min_context: int | None, context_window: int | None) -> list[str]:
    gaps = []
    for c in required:
        if c == "large_context":
            if not context_window or context_window < 100_000:
                gaps.append("large context (100K+) not available")
        elif c == "coding":
            if caps.get("coding") not in ("medium", "high"):
                gaps.append("coding capability too low")
        elif caps.get(c) is not True:
            gaps.append(f"{CAP_LABEL.get(c, c)} {'not supported' if caps.get(c) is False else 'not confirmed in the registry'}")
    if min_context and (not context_window or context_window < min_context):
        gaps.append(f"context window {context_window or 'unknown'} < required {min_context:,}")
    return gaps


def route(candidates: list[Candidate], *, required: list[str], est_input_tokens: int, est_output_tokens: int,
          routing: dict, policy_snapshot: list[dict], min_context: int | None = None) -> RouteDecision:
    objective = routing.get("objective") or "balanced"
    allowed = set(routing.get("allowed_providers") or [])
    max_cost, max_lat, min_eval = routing.get("max_cost_per_call"), routing.get("max_latency_seconds"), routing.get("min_eval_score")
    need_ctx = max(min_context or 0, int((est_input_tokens + est_output_tokens) * 1.1))
    scored, rejected = [], []
    for c in candidates:
        ident = f"{c.provider}/{c.model}"
        why: list[str] = []
        if not c.has_credential:
            why.append("no credential configured")
        if allowed and c.provider not in allowed:
            why.append("provider not allowed by routing policy")
        if c.provider == "local_test" and "local_test" not in allowed:
            why.append("test provider is only used when explicitly allowed")
        pol = evaluate_model(policy_snapshot, c.provider, c.model)
        if pol.effect == "deny":
            why.append(f"blocked by policy: {pol.reason}")
        why += capability_gaps(c.capabilities or {}, required, need_ctx if need_ctx > 0 else None, c.context_window)
        cost = estimate_cost(c.pricing, est_input_tokens, est_output_tokens) if c.pricing else None
        if cost is None and c.provider not in ("ollama", "local_test"):
            cost_known = False
        else:
            cost_known = True
            cost = cost or 0.0
        latency_s = (c.metrics.get("p50_latency_ms") or 0) / 1000 or float((c.capabilities or {}).get("latency_s") or 8)
        if max_cost is not None and (not cost_known or cost > max_cost):
            why.append(f"estimated ${cost:.4f}/call exceeds ${max_cost}" if cost_known else "no price data to check the cost limit")
        if max_lat is not None and latency_s > max_lat:
            why.append(f"typical latency {latency_s:.1f}s exceeds {max_lat}s")
        quality = c.metrics.get("eval_score")
        if min_eval is not None and (quality is None or quality < min_eval):
            why.append(f"evaluation score {'unknown' if quality is None else f'{quality:.0%}'} below {min_eval:.0%}")
        if (c.metrics.get("recent_error_rate") or 0) > 0.5 and (c.metrics.get("recent_calls") or 0) >= 4:
            why.append(f"provider unhealthy: {c.metrics['recent_error_rate']:.0%} recent errors")
        entry = {"provider": c.provider, "model": c.model, "est_cost": round(cost, 6) if cost_known else None,
                 "latency_s": round(latency_s, 2), "quality": quality, "quality_prior": (c.capabilities or {}).get("quality_tier")}
        if why:
            rejected.append({**entry, "rejected": why})
            continue
        scored.append((c, entry, cost if cost_known else None, latency_s, quality))

    if not scored:
        return RouteDecision(None, None, ["No configured model satisfies the requirements"], rejected, [])

    wq, wc, wl = WEIGHTS[objective]
    costs = [x[2] for x in scored if x[2] is not None]
    lo_c, hi_c = (min(costs), max(costs)) if costs else (0, 0)
    lats = [x[3] for x in scored]
    lo_l, hi_l = min(lats), max(lats)

    def norm_inv(v, lo, hi):
        return 1.0 if hi == lo else 1 - (v - lo) / (hi - lo)

    def qabs(entry, q):
        return q if q is not None else ((entry["quality_prior"] or 2) / 5) * 0.9  # priors count slightly less than measurements
    qs = [qabs(e, q) for _, e, _, _, q in scored]
    lo_q, hi_q = min(qs), max(qs)
    ranked = []
    for c, entry, cost, lat, q in scored:
        qa = qabs(entry, q)
        qn = 1.0 if hi_q == lo_q else (qa - lo_q) / (hi_q - lo_q)
        cn = norm_inv(cost, lo_c, hi_c) if cost is not None else 0.3
        ln = norm_inv(lat, lo_l, hi_l)
        score = wq * qn + wc * cn + wl * ln
        ranked.append((score, c, {**entry, "score": round(score, 4), "quality_used": round(qa, 3),
                                  "quality_source": "evaluations" if q is not None else "registry prior"}))
    ranked.sort(key=lambda x: -x[0])
    best = ranked[0]
    reasons = [f"✓ {CAP_LABEL.get(r, r)} required" for r in required]
    reasons.append(f"✓ Context requirement satisfied (~{need_ctx:,} tokens)" if need_ctx else "✓ Context requirement satisfied")
    reasons.append(f"✓ {objective.capitalize()} objective: best score {best[2]['score']} of {len(ranked)} eligible model(s)")
    if best[2]["est_cost"] is not None:
        reasons.append(f"Estimated ${best[2]['est_cost']:.4f} per call; typical latency {best[2]['latency_s']}s")
    reasons.append(f"Quality from {best[2]['quality_source']}")
    return RouteDecision(best[1].provider, best[1].model, reasons, [r[2] for r in ranked] + rejected,
                         [(r[1].provider, r[1].model) for r in ranked[1:3]])
