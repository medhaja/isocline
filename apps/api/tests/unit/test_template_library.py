"""Every library template builds a valid, compilable workflow whose variables resolve."""
from __future__ import annotations

import pytest

from isocline.engine.graph import compile_graph, validate_contracts, validate_structure
from isocline.schemas.workflow import WorkflowGraph
from isocline.services.template_library import TEMPLATES
from isocline.services.workflows import WORKFLOW_TEMPLATES, build_template, list_templates

MODEL = {"provider": "local_test", "model": "json"}


@pytest.mark.parametrize("spec", TEMPLATES, ids=[t["id"] for t in TEMPLATES])
def test_template_builds_valid_graph(spec):
    g = WorkflowGraph.model_validate(build_template(spec["id"], MODEL))
    errors = [i for i in validate_structure(g) + validate_contracts(g) if i.severity == "error"]
    assert not errors, [(i.code, i.message) for i in errors]
    compile_graph(g)
    assert set(spec["sample_input"]) == {f for f, _ in spec["inputs"]}, "sample input must cover every input"
    if spec.get("approval"):
        assert any(n.type == "human_approval" for n in g.nodes)


def test_library_size_and_categories():
    cats = {t["category"] for t in TEMPLATES}
    assert len(TEMPLATES) >= 40 and len(cats) >= 12
    assert len({t["id"] for t in TEMPLATES}) == len(TEMPLATES)
    listed = {t["id"] for t in list_templates()}
    assert {t["id"] for t in TEMPLATES} <= listed and set(WORKFLOW_TEMPLATES) == listed


def test_sensitive_templates_carry_safeguards():
    by_id = {t["id"]: t for t in TEMPLATES}
    for tid, t in by_id.items():
        text = str(t)
        if t["category"] == "Stock traders & investors":
            assert "not financial advice" in text.lower(), tid
        if tid in ("hr_resume_screening", "interviewer_scorecard"):
            assert t["approval"] and "Never make a final hiring decision" in text, tid


def test_test_provider_samples_respect_numeric_bounds():
    from isocline.providers.local_test import sample_for_schema
    assert sample_for_schema({"type": "number", "minimum": 1, "maximum": 5}) == 1
    assert sample_for_schema({"type": "integer", "minimum": 10}) == 10
    assert sample_for_schema({"type": "number", "maximum": 0.1}) == 0.1
    assert 0 < sample_for_schema({"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1}) < 1
