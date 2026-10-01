from isocline.engine.graph import compile_graph, validate_structure
from isocline.schemas.workflow import WorkflowGraph
from tests.conftest import agent, edge, graph, node


def codes(g):
    return {i.code for i in validate_structure(WorkflowGraph.model_validate(g))}


def test_valid_sequential_graph():
    g = graph([node("inp", "input_text", field="topic"), agent("research"), node("out", "output_text")],
              [edge("inp", "research"), edge("research", "out")])
    errs = [i for i in validate_structure(WorkflowGraph.model_validate(g)) if i.severity == "error"]
    assert errs == []


def test_cycle_is_illegal():
    g = graph([node("inp", "input_text"), agent("a"), agent("b")],
              [edge("inp", "a"), edge("a", "b"), edge("b", "a")])
    assert "illegal_cycle" in codes(g)


def test_missing_model_and_disconnected_input():
    g = graph([node("inp", "input_text"), node("a", "agent", prompt="x"), node("out", "output_text")],
              [edge("inp", "out")])
    c = codes(g)
    assert "no_model" in c
    assert "disconnected_input" in c


def test_unknown_variable_reference():
    g = graph([node("inp", "input_text"), agent("a", prompt="{{nosuch.output}}")], [edge("inp", "a")])
    assert "unknown_variable" in codes(g)


def test_loop_requires_termination_limit_within_ceiling():
    g = graph([node("inp", "input_text"), node("lp", "loop", collection="{{input.items}}", max_iterations=1000), agent("b")],
              [edge("inp", "lp"), edge("lp", "b", "body")])
    assert any("loop" in c for c in codes(g))


def test_condition_handles_validated():
    g = graph([node("inp", "input_text"), node("c", "condition", rule={"left": "{{input.x}}", "operator": ">", "right": 1}),
               agent("a")], [edge("inp", "c"), edge("c", "a", "maybe")])
    assert "invalid_handle" in codes(g)


def test_compile_parallel_order():
    g = graph([node("a", "input_text"), agent("b"), agent("c"), node("d", "merge")],
              [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")])
    cg = compile_graph(WorkflowGraph.model_validate(g))
    assert cg.order[0] == "a" and cg.order[-1] == "d"
    assert set(cg.predecessors("d")) == {"b", "c"}
