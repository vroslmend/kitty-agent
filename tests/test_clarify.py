"""The clarify and interrupt path.

The graph really pauses here: `ask_clarification` calls `interrupt()`, which
persists the run and raises, and the visitor's next message resumes the same
task rather than starting a new turn. All of it runs against InMemorySaver, so
the suite proves the mechanism without a database.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import app.agent.graph as graph_module
from app.agent.graph import build_graph
from app.config import Settings
from tests.fakes import ScriptedModel, clarification_call

FAKE_KEY = "not-a-real-key-nothing-here-calls-the-api"


@pytest.fixture
def scripted(monkeypatch):
    """Swap the model out where the graph reaches for it."""

    def install(*replies: AIMessage) -> ScriptedModel:
        model = ScriptedModel(*replies)
        monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda **kwargs: model)
        return model

    return install


def config(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


async def test_the_graph_pauses_when_the_model_asks_which_one(scripted) -> None:
    scripted(clarification_call("which one?", ["CUI Central", "Imaginify"]))
    graph = build_graph(Settings(llm_api_key=FAKE_KEY), checkpointer=InMemorySaver())

    await graph.ainvoke({"messages": [HumanMessage(content="the ai thing")]}, config("t1"))

    interrupts = (await graph.aget_state(config("t1"))).interrupts
    assert len(interrupts) == 1
    assert interrupts[0].value == {
        "question": "which one?",
        "options": ["CUI Central", "Imaginify"],
    }


async def test_the_visitors_reply_resumes_the_paused_tool_call(scripted) -> None:
    model = scripted(
        clarification_call("which one?", ["CUI Central", "Imaginify"]),
        AIMessage(content="CUI Central is a campus chatbot."),
    )
    graph = build_graph(Settings(llm_api_key=FAKE_KEY), checkpointer=InMemorySaver())
    await graph.ainvoke({"messages": [HumanMessage(content="the ai thing")]}, config("t2"))

    await graph.ainvoke(Command(resume="CUI Central"), config("t2"))

    state = await graph.aget_state(config("t2"))
    assert state.interrupts == ()
    # The answer arrives as the tool's result, not as a new question from the
    # visitor. That is what makes it a resume rather than a fresh turn.
    tool_results = [m for m in state.values["messages"] if m.type == "tool"]
    assert [m.content for m in tool_results] == ["CUI Central"]
    assert state.values["messages"][-1].content == "CUI Central is a campus chatbot."
    assert len(model.seen) == 2


async def test_without_a_checkpointer_the_clarification_tool_is_not_offered(scripted) -> None:
    # interrupt() needs somewhere to persist the paused run. An empty
    # DATABASE_URL is a supported state, so the tool has to disappear rather
    # than raise the first time a vague question arrives.
    model = scripted(AIMessage(content="hello"))
    build_graph(Settings(llm_api_key=FAKE_KEY))
    assert "ask_clarification" not in {t.name for t in model.tools}


async def test_with_a_checkpointer_it_is(scripted) -> None:
    model = scripted(AIMessage(content="hello"))
    build_graph(Settings(llm_api_key=FAKE_KEY), checkpointer=InMemorySaver())
    assert "ask_clarification" in {t.name for t in model.tools}
