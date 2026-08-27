"""Graph wiring, routing and tool behaviour.

Nothing here calls the model. CI has no API key, and a suite that needs one is a
suite that gets skipped. The one thing that would need a real call, whether the
model picks the right tool, is what the eval harness is for.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END

from app.agent.graph import build_graph, should_continue
from app.config import Settings

FAKE_KEY = "not-a-real-key-nothing-here-calls-the-api"


def settings_with_key() -> Settings:
    return Settings(llm_api_key=FAKE_KEY)


def test_routes_to_tools_when_the_model_asked_for_one() -> None:
    message = AIMessage(
        content="",
        tool_calls=[{"name": "list_projects", "args": {}, "id": "call_1"}],
    )
    assert should_continue({"messages": [message]}) == "tools"


def test_routes_to_end_on_a_plain_answer() -> None:
    assert should_continue({"messages": [AIMessage(content="done")]}) == END


def test_routes_to_end_on_a_human_message() -> None:
    # A HumanMessage has no tool_calls attribute at all. getattr must not raise.
    assert should_continue({"messages": [HumanMessage(content="hi")]}) == END


def test_graph_compiles_with_the_loop_wired() -> None:
    graph = build_graph(settings_with_key())
    nodes = graph.get_graph().nodes
    assert "agent" in nodes
    assert "tools" in nodes


def test_graph_loops_from_tools_back_to_agent() -> None:
    # The edge that makes it an agent rather than one retrieval hop. If this
    # goes missing the graph still compiles and still answers, just never twice.
    edges = {(e.source, e.target) for e in build_graph(settings_with_key()).get_graph().edges}
    assert ("tools", "agent") in edges
