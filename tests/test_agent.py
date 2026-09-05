"""Graph wiring, routing and tool behaviour.

Nothing here calls the model. CI has no API key, and a suite that needs one is a
suite that gets skipped. The one thing that would need a real call, whether the
model picks the right tool, is what the eval harness is for.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END

import app.agent.graph as graph_module
from app.agent.graph import build_graph, should_continue
from app.agent.prompts import build_system_prompt
from app.config import Settings
from tests.fakes import ScriptedModel

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


def test_model_calls_fail_fast_instead_of_hiding_quota_backoff(monkeypatch) -> None:
    captured = {}

    def model(**kwargs):
        captured.update(kwargs)
        return ScriptedModel(AIMessage(content="hello"))

    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", model)

    build_graph(settings_with_key())

    assert captured["max_retries"] == 1
    assert captured["timeout"] == 10


def test_system_prompt_includes_only_the_public_profile_facts() -> None:
    prompt = build_system_prompt(
        {
            "name": "Ammar Hassan",
            "role": "software engineer",
            "location": "lahore, pakistan",
            "email": "public@example.com",
            "now": "open to work",
            "private": "must not appear",
        }
    )

    assert "public@example.com" in prompt
    assert "open to work" in prompt
    assert "must not appear" not in prompt


def test_system_prompt_includes_validated_current_page_context() -> None:
    prompt = build_system_prompt(
        {
            "name": "Ammar Hassan",
            "role": "software engineer",
            "location": "lahore, pakistan",
            "email": "public@example.com",
            "now": "open to work",
        },
        {
            "route": "/writing/visitor-counter",
            "title": "counting visitors",
            "description": "How the visitor counter was built.",
        },
    )

    assert "Trusted current-page context" in prompt
    assert "/writing/visitor-counter" in prompt
    assert "still search the writing" in prompt


async def test_graph_ignores_an_unknown_page_path(monkeypatch) -> None:
    model = ScriptedModel(AIMessage(content="hello"))
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda **kwargs: model)
    graph = build_graph(settings_with_key())

    await graph.ainvoke(
        {"messages": [HumanMessage(content="what is this?")], "page_path": "/not-real"}
    )

    system_message = model.seen[0][0]
    assert "Trusted current-page context" not in system_message.content
    assert "/not-real" not in system_message.content
